"""ProbeRunner — single-probe executor for the probe architecture.

Loads a probe-specific prompt (preamble + rubric + output schema),
executes a single LLM call, and returns a list of Issue objects.

Each probe evaluates ONE issue_type on a specified set of slides.
This replaces the monolithic judge approach where 18 rubrics were
crammed into a single 800+ line system prompt.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

from ...llm_client import LLMClient
from ...schemas.blueprint import DeckBlueprint
from ...schemas.common import Confidence, IssueStatus, RepairAction, Severity, Verdict
from ...schemas.evidence import EvidenceState
from ...schemas.experiment_config import ExperimentConfig
from ...schemas.extraction import SlideExtraction
from ...schemas.issue import FixDetail, Issue, IssueEvidence
from ...schemas.issue_types import (
    PROBE_REGISTRY,
    IssueTypeDef,
    SpatialThresholds,
    VALID_ISSUE_TYPES,
    get_atomic_check_details,
)
from ...utils.io_utils import read_text
from ...utils.json_utils import strip_code_fences
from ...utils.image_ops import (
    get_image_dimensions,
    image_regions_to_base64,
    image_to_base64,
)
from ...utils.issue_identity import issues_share_target, stable_issue_id

logger = logging.getLogger(__name__)

_PROBES_DIR = Path(__file__).parent.parent.parent / "prompts" / "probes"
_SHARED_DIR = _PROBES_DIR / "_shared"
_GLOBAL_SHARED_DIR = Path(__file__).parent.parent.parent / "prompts" / "shared"
_REPO_ROOT = Path(__file__).resolve().parents[3]


class ProbeRunner:
    """Executes a single probe on specified slides."""

    def __init__(self, llm: LLMClient, config: ExperimentConfig):
        self.llm = llm
        self.config = config
        self._prompt_cache: dict[str, str] = {}

    # ================================================================
    # PUBLIC API
    # ================================================================

    def run_probe(
        self,
        probe_id: str,
        slide_ids: list[int],
        extractions: list[SlideExtraction],
        png_paths: list[str] | None = None,
        spatial_signals: dict | None = None,
        source_summary: str = "",
        task_brief: str = "",
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        source_store: Any = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
        system_prompt_suffix: str = "",
        prompt_variant: str = "",
        selected_check_ids: list[str] | None = None,
    ) -> list[Issue]:
        """Run a single probe and return issues.

        Args:
            probe_id: e.g. "B03", "D01", "A03"
            slide_ids: which slides to evaluate (ignored for deck-level probes)
            extractions: slide extraction data
            png_paths: paths to rendered slide PNGs (aligned with extractions)
            spatial_signals: {slide_id: SlideState} for spatial probes
            source_summary: full source text for content probes
            task_brief: task brief for completeness probes
            blueprint: deck blueprint for evidence lookup
            evidence: evidence state for evidence lookup
            source_store: SourceStore for V2 evidence bundling
            previous_issues: issues from prior turn for triage
            turn_index: current repair turn
            selected_check_ids: atomic conditions that constrain fresh discovery;
                previous-issue triage still uses the complete probe rubric

        Returns:
            List of Issue objects found by this probe.
        """
        probe_def = PROBE_REGISTRY.get(probe_id)
        if not probe_def:
            logger.warning("Unknown probe_id: %s", probe_id)
            return []

        system_prompt = self._build_system_prompt(probe_def)
        if system_prompt_suffix:
            system_prompt = f"{system_prompt}\n\n{system_prompt_suffix}"
        module_suffix = f"_{prompt_variant}" if prompt_variant else ""

        # --- STEP 1: Triage previous issues of this probe's type ---
        triaged_issues: list[Issue] = []
        if turn_index > 0 and previous_issues:
            relevant_prev = [
                iss for iss in previous_issues
                if iss.issue_type == probe_def.name
            ]
            if relevant_prev:
                triaged_issues = self._triage_previous(
                    probe_def, system_prompt, relevant_prev,
                    slide_ids, extractions, png_paths, spatial_signals,
                    source_summary, blueprint, evidence, source_store,
                    turn_index,
                )

        selected_focus = self._format_selected_check_focus(
            probe_id,
            selected_check_ids or [],
        )
        fresh_system_prompt = (
            f"{system_prompt}\n\n{selected_focus}"
            if selected_focus else system_prompt
        )

        # --- STEP 2: Fresh evaluation ---
        user_content = self._build_user_content(
            probe_def, slide_ids, extractions, png_paths,
            spatial_signals, source_summary, task_brief,
            blueprint, evidence, source_store,
        )

        # Inject persistent issue awareness (don't re-report triaged open issues)
        if triaged_issues:
            persistent_ctx = self._format_persistent_context(triaged_issues)
            if persistent_ctx:
                if isinstance(user_content, str):
                    user_content = user_content + persistent_ctx
                else:
                    # multimodal content (list of dicts)
                    user_content.append({"type": "text", "text": persistent_ctx})

        model = self.config.models.get_model("probe_runner")

        # LLM call
        try:
            if probe_def.requires_vision and png_paths:
                image_urls = self._encode_slide_images(
                    slide_ids, extractions, png_paths,
                    probe_id=probe_id,
                    spatial_signals=spatial_signals,
                )
                text_part = user_content if isinstance(user_content, str) else \
                    "\n".join(c["text"] for c in user_content if c.get("type") == "text")
                raw = self.llm.call_vision(
                    system_prompt=fresh_system_prompt,
                    text_content=text_part,
                    image_urls=image_urls,
                    model=model,
                    module_name=f"probe_{probe_id}{module_suffix}",
                    prompt_version=f"probe.{probe_id}{module_suffix}.v1",
                    max_tokens=8192 if probe_id == "B20" else 4096,
                    temperature=0.2,
                )
            else:
                text_part = user_content if isinstance(user_content, str) else \
                    "\n".join(c["text"] for c in user_content if c.get("type") == "text")
                raw = self.llm.call_text(
                    system_prompt=fresh_system_prompt,
                    user_content=text_part,
                    model=model,
                    module_name=f"probe_{probe_id}{module_suffix}",
                    prompt_version=f"probe.{probe_id}{module_suffix}.v1",
                    max_tokens=4096,
                    temperature=0.2,
                )
        except Exception as e:
            logger.warning("Probe %s LLM call failed: %s", probe_id, str(e)[:200])
            return triaged_issues

        # Parse new issues
        new_issues = self._parse_probe_output(raw, probe_def, slide_ids, turn_index)

        # Dedup new against triaged
        if triaged_issues:
            new_issues = self._dedup_new_against_triaged(new_issues, triaged_issues)

        return triaged_issues + new_issues

    @staticmethod
    def _format_selected_check_focus(
        probe_id: str,
        selected_check_ids: list[str],
    ) -> str:
        """Constrain fresh findings to the atomic checks selected by the planner."""
        details = get_atomic_check_details()
        selected = [
            (check_id, details[check_id]["text"])
            for check_id in selected_check_ids
            if check_id in details and details[check_id]["probe_id"] == probe_id
        ]
        if not selected:
            return ""
        lines = [
            "## Selected atomic checks for this invocation",
            "For fresh issue discovery, evaluate only the conditions below. "
            "Do not report other new failures from the same probe family. "
            "The full rubric remains available only for definitions, boundaries, "
            "and severity calibration.",
        ]
        lines.extend(f"- {check_id}: {text}" for check_id, text in selected)
        return "\n".join(lines)

    # ================================================================
    # PROMPT ASSEMBLY
    # ================================================================

    def _build_system_prompt(self, probe_def: IssueTypeDef) -> str:
        """Assemble system prompt: preamble + probe rubric + output schema + shared rules."""
        cache_key = probe_def.probe_id
        if cache_key in self._prompt_cache:
            return self._prompt_cache[cache_key]

        # Select preamble by family
        family = probe_def.family.value
        if family == "B_visual":
            preamble_file = "visual_preamble.md"
        elif family == "A":
            preamble_file = "narrative_preamble.md"
        else:  # C, D, E
            preamble_file = "content_preamble.md"

        preamble = read_text(_SHARED_DIR / preamble_file)
        rubric = read_text(_PROBES_DIR / probe_def.probe_file)
        output_schema = read_text(_SHARED_DIR / "output_schema.md")

        # Global shared rules (same as BaseJudge)
        judgment_rules = read_text(_GLOBAL_SHARED_DIR / "global_judgment_rules.md")
        json_rules = read_text(_GLOBAL_SHARED_DIR / "json_output_rules.md")
        uncertainty = read_text(_GLOBAL_SHARED_DIR / "uncertainty_policy.md")

        prompt = (
            f"{preamble}\n\n"
            f"---\n\n"
            f"## Rubric\n\n{rubric}\n\n"
            f"---\n\n"
            f"{output_schema}\n\n"
            f"---\n\n"
            f"{judgment_rules}\n\n{json_rules}\n\n{uncertainty}"
        )

        self._prompt_cache[cache_key] = prompt
        return prompt

    # ================================================================
    # USER CONTENT BUILDERS
    # ================================================================

    def _build_user_content(
        self,
        probe_def: IssueTypeDef,
        slide_ids: list[int],
        extractions: list[SlideExtraction],
        png_paths: list[str] | None,
        spatial_signals: dict | None,
        source_summary: str,
        task_brief: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
        source_store: Any,
    ) -> str:
        """Build user content appropriate for the probe type."""

        if probe_def.is_deck_level:
            # Deck-level probes: full deck outline
            return self._build_deck_level_content(
                probe_def, extractions, task_brief, source_summary,
                blueprint, evidence, source_store,
            )

        family = probe_def.family.value

        if family == "B_visual":
            return self._build_visual_content(
                probe_def, slide_ids, extractions, spatial_signals,
            )
        else:
            # Content probes (C, D, E) and per-slide A probes
            return self._build_content_probe_content(
                probe_def, slide_ids, extractions,
                source_summary, blueprint, evidence, source_store,
            )

    @staticmethod
    def _resolve_image_path(image_path: str) -> Path | None:
        if not image_path:
            return None
        raw = Path(image_path)
        candidates = [raw] if raw.is_absolute() else [Path.cwd() / raw, _REPO_ROOT / raw]
        for candidate in candidates:
            try:
                if candidate.is_file():
                    return candidate
            except OSError:
                continue
        return None

    @classmethod
    def _build_object_inventory(cls, ext: SlideExtraction) -> list[dict[str, Any]]:
        """Return compact per-object affordances for visual probes.

        The rendered image is still the primary evidence. This inventory gives
        the judge enough structure to avoid impossible fix plans, especially for
        indivisible embedded image assets whose internals cannot be rearranged.
        """
        inventory: list[dict[str, Any]] = []
        for obj in ext.objects[:80]:
            entry: dict[str, Any] = {
                "object_id": obj.object_id,
                "object_type": obj.object_type,
                "shape_name": obj.shape_name,
                "bbox_emu": obj.bbox_emu,
                "z_order": obj.z_order,
            }
            if obj.text_content:
                preview = re.sub(r"\s+", " ", obj.text_content).strip()
                entry["text_preview"] = preview[:180]
            if obj.has_image:
                entry.update({
                    "has_image": True,
                    "image_path": obj.image_path,
                    "embedded_image_asset": True,
                    "internal_content_editable": False,
                    "image_affordance": (
                        "The whole image can be moved, resized, cropped, or "
                        "recomposed from source; internal labels, panels, marks, "
                        "and curves cannot be rearranged by normal layout repair."
                    ),
                })
                image_file = cls._resolve_image_path(obj.image_path)
                if image_file:
                    try:
                        width_px, height_px = get_image_dimensions(image_file)
                    except Exception:
                        width_px = height_px = 0
                    if width_px > 0 and height_px > 0:
                        aspect = width_px / height_px
                        entry.update({
                            "natural_width_px": width_px,
                            "natural_height_px": height_px,
                            "natural_aspect_ratio": round(aspect, 3),
                        })
                        if aspect >= 2.0:
                            entry["image_shape_note"] = (
                                "wide_shallow_image: adding height to the outer "
                                "slot may create letterbox or overlap instead of "
                                "making the figure content more useful."
                            )
            inventory.append(entry)
        return inventory

    def _build_visual_content(
        self,
        probe_def: IssueTypeDef,
        slide_ids: list[int],
        extractions: list[SlideExtraction],
        spatial_signals: dict | None,
    ) -> str:
        """Build user content for B-series visual probes."""
        slide_info = []
        for ext in extractions:
            if ext.slide_id not in slide_ids:
                continue
            total_words = 0
            min_font = 999
            max_font = 0
            has_image = False
            for obj in ext.objects:
                if obj.has_image:
                    has_image = True
                if obj.text_content:
                    total_words += len(obj.text_content.split())
                if obj.font_sizes_pt:
                    for fs in obj.font_sizes_pt:
                        if fs > 0:
                            min_font = min(min_font, fs)
                            max_font = max(max_font, fs)

            info: dict[str, Any] = {
                "slide_id": ext.slide_id,
                "title": ext.title,
                "object_count": ext.total_objects,
                "total_words": total_words,
                "has_image": has_image,
                "object_inventory": self._build_object_inventory(ext),
            }
            if min_font < 999:
                info["min_font_pt"] = round(min_font, 1)
                info["max_font_pt"] = round(max_font, 1)
            if total_words < 15 and not has_image:
                info["WARNING"] = f"Only {total_words} words — likely over-condensed"
            slide_info.append(info)

        data: dict[str, Any] = {
            "probe_id": probe_def.probe_id,
            "issue_type": probe_def.name,
            "scope_slides": slide_ids,
            "slide_info": slide_info,
        }

        # Add spatial signals if the probe requires them
        if probe_def.requires_spatial and spatial_signals:
            from .visual_judge import _format_spatial_signal
            spatial_ctx = {}
            for sid in slide_ids:
                state = spatial_signals.get(sid)
                if state:
                    spatial_ctx[sid] = _format_spatial_signal(state)
            if spatial_ctx:
                data["spatial_signals"] = spatial_ctx
                if probe_def.probe_id == "B20":
                    data["inspection_image_order"] = [
                        {
                            "slide_id": sid,
                            "images": ["full_slide"] + [
                                label
                                for i, _ in enumerate(
                                    getattr(spatial_signals.get(sid), "svg_regions", [])
                                )
                                for label in (
                                    f"svg_region_{i + 1}_enlarged",
                                    f"svg_region_{i + 1}_detail_tiles_top_left_top_right_bottom_left_bottom_right",
                                )
                            ],
                        }
                        for sid in slide_ids
                        if spatial_signals.get(sid)
                    ]

        return json.dumps(data, indent=2, ensure_ascii=False)

    def _build_content_probe_content(
        self,
        probe_def: IssueTypeDef,
        slide_ids: list[int],
        extractions: list[SlideExtraction],
        source_summary: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
        source_store: Any,
    ) -> str:
        """Build user content for C/D/E and per-slide A probes."""
        claims = []
        for ext in extractions:
            if ext.slide_id not in slide_ids:
                continue
            slide_claims = [
                obj.text_content.strip()
                for obj in ext.objects
                if obj.text_content.strip()
            ]
            entry: dict[str, Any] = {
                "slide_id": ext.slide_id,
                "title": ext.title,
                "content": slide_claims,
            }
            # Per-slide evidence for source probes
            if probe_def.requires_source:
                slide_text = " ".join(slide_claims)
                slide_ev = self._build_slide_evidence(
                    ext.slide_id, blueprint, evidence,
                    source_store, slide_text,
                )
                if slide_ev:
                    entry["source_evidence"] = slide_ev
            claims.append(entry)

        data: dict[str, Any] = {
            "probe_id": probe_def.probe_id,
            "issue_type": probe_def.name,
            "scope_slides": slide_ids,
            "slide_content": claims,
        }
        if probe_def.probe_id in {"C03", "C04"}:
            # Coverage is a deck-level property even when the repair target is
            # local. Give the probe enough context to avoid demanding that a
            # metric, example, or caveat be repeated on every related slide.
            data["deck_context"] = [
                {
                    "slide_id": ext.slide_id,
                    "title": ext.title,
                    "content": [
                        obj.text_content.strip()
                        for obj in ext.objects
                        if obj.text_content.strip()
                    ],
                }
                for ext in extractions
            ]
        if probe_def.requires_source:
            data["source_materials"] = source_summary

        return json.dumps(data, indent=2, ensure_ascii=False)

    def _build_deck_level_content(
        self,
        probe_def: IssueTypeDef,
        extractions: list[SlideExtraction],
        task_brief: str,
        source_summary: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
        source_store: Any,
    ) -> str:
        """Build user content for deck-level probes (A01-A03, A06, C01, C05)."""
        outline = []
        for ext in extractions:
            slide_text = []
            for obj in ext.objects:
                if obj.text_content.strip():
                    slide_text.append(obj.text_content.strip())
            outline.append({
                "slide_id": ext.slide_id,
                "title": ext.title,
                "text_content": slide_text,
            })

        data: dict[str, Any] = {
            "probe_id": probe_def.probe_id,
            "issue_type": probe_def.name,
            "deck_outline": outline,
        }
        if task_brief:
            data["task_brief"] = task_brief
        if probe_def.requires_source:
            data["source_materials"] = source_summary

        return json.dumps(data, indent=2, ensure_ascii=False)

    # ================================================================
    # TRIAGE
    # ================================================================

    def _triage_previous(
        self,
        probe_def: IssueTypeDef,
        system_prompt: str,
        previous_issues: list[Issue],
        slide_ids: list[int],
        extractions: list[SlideExtraction],
        png_paths: list[str] | None,
        spatial_signals: dict | None,
        source_summary: str,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
        source_store: Any,
        turn_index: int,
    ) -> list[Issue]:
        """Triage previous issues of this probe's type.

        Uses the same two-call pattern as BaseJudge:
        Call 1 = verdict-only triage, Call 2 = fresh eval.
        """
        # Separate already-resolved issues (don't re-triage)
        resolved = [i for i in previous_issues if i.status == IssueStatus.RESOLVED]
        open_issues = [i for i in previous_issues if i.status != IssueStatus.RESOLVED]
        if not open_issues:
            return list(resolved)

        # Build triage prompt
        prev_ctx = self._format_prev_issues_for_triage(open_issues, slide_ids)
        base_content = self._build_user_content(
            probe_def, slide_ids, extractions, png_paths,
            spatial_signals, source_summary, "",
            blueprint, evidence, source_store,
        )
        triage_prompt = (
            base_content + prev_ctx
            + "\n\n## IMPORTANT — Verdict-Only Mode\n"
            "Treat each previous issue as a hypothesis to re-check against the "
            "CURRENT rendered pixels, not as evidence that the defect persists. "
            "A spatial candidate or bounding-box intersection is only an attention "
            "hint and cannot by itself justify PERSISTED: paint order, masking, "
            "clipping, and transparent whitespace can make geometric boxes overlap "
            "without any visible interference. Inspect the named target in the "
            "current full-slide image and crop. If the reported visual symptom is "
            "no longer visible, return RESOLVED even when metadata still lists a "
            "candidate.\n"
            "Return ONLY `previous_issue_verdicts`. Do NOT report new issues.\n"
            f"You MUST return a verdict for ALL {len(open_issues)} issues.\n"
            '```json\n{"previous_issue_verdicts": [...]}\n```'
        )

        model = self.config.models.get_model("probe_runner")

        try:
            if probe_def.requires_vision and png_paths:
                image_urls = self._encode_slide_images(
                    slide_ids, extractions, png_paths,
                    probe_id=probe_def.probe_id,
                    spatial_signals=spatial_signals,
                )
                raw = self.llm.call_vision(
                    system_prompt=system_prompt,
                    text_content=triage_prompt,
                    image_urls=image_urls,
                    model=model,
                    module_name=f"probe_{probe_def.probe_id}_triage",
                    prompt_version=f"probe.{probe_def.probe_id}.triage.v1",
                    max_tokens=4096,
                    temperature=0.2,
                )
            else:
                raw = self.llm.call_text(
                    system_prompt=system_prompt,
                    user_content=triage_prompt,
                    model=model,
                    module_name=f"probe_{probe_def.probe_id}_triage",
                    prompt_version=f"probe.{probe_def.probe_id}.triage.v1",
                    max_tokens=4096,
                    temperature=0.2,
                )
        except Exception as e:
            logger.warning("Probe %s triage failed: %s", probe_def.probe_id, str(e)[:200])
            return resolved + open_issues

        # Parse verdicts
        text = strip_code_fences(raw)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Probe %s triage JSON parse failed", probe_def.probe_id)
            return resolved + open_issues

        verdicts = data.get("previous_issue_verdicts", [])
        verdict_map = {v["issue_id"]: v for v in verdicts if isinstance(v, dict) and "issue_id" in v}

        for iss in open_issues:
            vdata = verdict_map.get(iss.issue_id)
            if vdata:
                verdict_str = vdata.get("verdict", "PERSISTED").upper()
                already_triaged = getattr(iss, "last_triaged_turn", None) == turn_index
                if verdict_str == "RESOLVED":
                    iss.status = IssueStatus.RESOLVED
                    iss.resolved_at_turn = turn_index
                    iss.verdict = Verdict.PASS
                    iss.persisted_turns = 0
                elif verdict_str == "WORSENED":
                    updated_desc = vdata.get("updated_description")
                    if isinstance(updated_desc, str) and updated_desc.strip():
                        desc = updated_desc.strip()
                        iss.why_this_fails = desc
                        if iss.evidence:
                            iss.evidence.description = desc
                    iss.planned_fix = f"[WORSENED] {vdata.get('reasoning', '')}"
                    if not already_triaged:
                        iss.persisted_turns = max(iss.persisted_turns, 0) + 1
                else:
                    label = "PARTIALLY_MITIGATED" if "PARTIAL" in verdict_str else "PERSISTED"
                    updated_desc = vdata.get("updated_description")
                    if isinstance(updated_desc, str) and updated_desc.strip():
                        desc = updated_desc.strip()
                        iss.why_this_fails = desc
                        if iss.evidence:
                            iss.evidence.description = desc
                    iss.planned_fix = f"[{label}] {vdata.get('reasoning', '')}"
                    if not already_triaged:
                        iss.persisted_turns += 1

                # Triage persistence is not evidence that two distinct repair
                # strategies failed. Keep lifecycle state open here; the repair
                # dispatcher owns escalation from structured attempt outcomes.
                iss.last_triaged_turn = turn_index

                updated_fix = vdata.get("updated_planned_fix")
                if isinstance(updated_fix, str) and updated_fix.strip():
                    iss.planned_fix = updated_fix.strip()
                updated_correct = vdata.get("updated_correct_content")
                if isinstance(updated_correct, str):
                    iss.fix_detail.correct_content = updated_correct.strip()
                elif updated_fix:
                    # A changed semantic correction invalidates an old exact-text
                    # contract unless the current triage explicitly refreshes it.
                    iss.fix_detail.correct_content = ""

        return resolved + open_issues

    # ================================================================
    # PARSING
    # ================================================================

    def _parse_probe_output(
        self,
        raw_response: str,
        probe_def: IssueTypeDef,
        scope_slides: list[int],
        turn_index: int,
    ) -> list[Issue]:
        """Parse probe LLM output into Issue objects."""
        text = strip_code_fences(raw_response)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Probe %s response not valid JSON: %s",
                           probe_def.probe_id, text[:300])
            return []

        issues_data = data.get("new_issues", data.get("issues", []))
        result: list[Issue] = []

        for i, item in enumerate(issues_data):
            raw_type = item.get("issue_type", probe_def.name)
            # Normalize but prefer the probe's expected type
            if raw_type != probe_def.name:
                logger.debug(
                    "Probe %s returned issue_type=%r, expected %r — using expected",
                    probe_def.probe_id, raw_type, probe_def.name,
                )
                raw_type = probe_def.name

            affected = item.get("affected_slides", scope_slides)

            raw_evidence = item.get("evidence", "")
            if isinstance(raw_evidence, dict):
                issue_evidence = IssueEvidence(
                    render_ref=str(raw_evidence.get("render_ref", "")),
                    object_refs=[str(ref) for ref in raw_evidence.get("object_refs", [])],
                    source_refs=[str(ref) for ref in raw_evidence.get("source_refs", [])],
                    description=str(raw_evidence.get("description", "")),
                )
            else:
                issue_evidence = IssueEvidence(description=str(raw_evidence or ""))

            issue = Issue(
                issue_id="pending",
                rubric_id=item.get("rubric_id", probe_def.probe_id),
                issue_type=raw_type,
                sub_type=item.get("sub_type", ""),
                severity=Severity(item.get("severity", "minor")),
                confidence=Confidence(item.get("confidence", "medium")),
                affected_slides=affected,
                evidence=issue_evidence,
                suspected_module="unknown",
                verdict=Verdict.FAIL,
                why_this_fails=item.get("why_this_fails", ""),
                fixability=item.get("fixability", "unknown"),
                planned_fix=item.get("planned_fix", ""),
                fix_detail=self._parse_fix_detail(item.get("fix_detail")),
                recommended_action=RepairAction(
                    item.get("recommended_action", "PATCH")
                ),
                action_rationale=item.get("action_rationale", ""),
                source_probe_id=f"probe_{probe_def.probe_id}",
            )
            issue.issue_id = stable_issue_id(issue, probe_def.probe_id)

            # Handle B09 sub_type
            sub_type = item.get("sub_type")
            if sub_type and hasattr(issue, 'sub_type'):
                issue.sub_type = sub_type

            result.append(issue)

        return result

    # ================================================================
    # HELPERS
    # ================================================================

    @staticmethod
    def _parse_fix_detail(raw: Any) -> FixDetail:
        if not raw or not isinstance(raw, dict):
            return FixDetail()

        def text_value(key: str) -> str:
            value = raw.get(key)
            return value if isinstance(value, str) else ""

        return FixDetail(
            correct_content=text_value("correct_content"),
            source_ref=text_value("source_ref"),
            target_location=text_value("target_location"),
            action_type=text_value("action_type"),
        )

    @staticmethod
    def _encode_slide_images(
        slide_ids: list[int],
        extractions: list[SlideExtraction],
        png_paths: list[str],
        probe_id: str = "",
        spatial_signals: dict | None = None,
    ) -> list[str]:
        """Encode slide PNGs as base64 for vision LLM calls."""
        image_urls = []
        for ext, png_path in zip(extractions, png_paths):
            if ext.slide_id in slide_ids and Path(png_path).exists():
                try:
                    state = spatial_signals.get(ext.slide_id) if spatial_signals else None
                    regions = getattr(state, "svg_regions", []) if state else []
                    if probe_id == "B20" and regions:
                        image_urls.extend(image_regions_to_base64(png_path, regions))
                    else:
                        image_urls.append(image_to_base64(png_path, max_size=1920))
                except Exception as e:
                    logger.warning("Failed to encode slide %d: %s", ext.slide_id, e)
        return image_urls

    @staticmethod
    def _format_persistent_context(triaged_issues: list[Issue]) -> str:
        """Format triaged issues as 'do not re-report' context."""
        open_issues = [
            iss for iss in triaged_issues
            if iss.status not in (IssueStatus.RESOLVED, IssueStatus.WONT_FIX, IssueStatus.DEFERRED)
        ]
        if not open_issues:
            return ""
        lines = [
            "\n\n## Known Persistent Issues (DO NOT re-report)",
            "These issues are tracked. Only report genuinely NEW issues.\n",
        ]
        for iss in open_issues:
            desc = (iss.evidence.description[:120] if iss.evidence and iss.evidence.description else "")
            slides = ",".join(str(s) for s in (iss.affected_slides or []))
            lines.append(f"- [{iss.issue_id}] {iss.issue_type} slide(s) {slides}: {desc}")
        return "\n".join(lines)

    @staticmethod
    def _format_prev_issues_for_triage(
        issues: list[Issue], scope_slides: list[int],
    ) -> str:
        """Format previous issues for triage verdict call."""
        lines = [
            "\n\n## Previous Issues (triage required)",
            f"Evaluate each issue against the CURRENT state. {len(issues)} issues:\n",
        ]
        for iss in issues:
            slides = ", ".join(str(s) for s in iss.affected_slides)
            desc = (iss.evidence.description[:200] if iss.evidence and iss.evidence.description else "")
            lines.append(
                f"### Issue `{iss.issue_id}` [{iss.issue_type}] "
                f"Slide(s) {slides} ({iss.severity.value})"
            )
            if desc:
                lines.append(f"Description: {desc}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _dedup_new_against_triaged(
        new_issues: list[Issue], triaged_issues: list[Issue],
    ) -> list[Issue]:
        """Remove new issues that duplicate triaged previous issues."""
        open_previous = [
            issue for issue in triaged_issues
            if issue.status != IssueStatus.RESOLVED
        ]
        return [
            issue for issue in new_issues
            if not any(issues_share_target(issue, previous) for previous in open_previous)
        ]

    def _build_slide_evidence(
        self,
        slide_id: int,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
        source_store: Any,
        slide_text: str,
    ) -> str:
        """Build per-slide source evidence. Reuses BaseJudge logic."""
        # Use source_store V2 if available
        if source_store is not None:
            bundle = source_store.get_bundle(slide_id)
            if bundle and bundle.source_text:
                parts = [bundle.source_text]
                parts.extend(bundle.asset_summaries)
                parts.extend(bundle.table_summaries)
                return "\n\n".join(parts)

        # Legacy fallback — simplified version
        if not blueprint or not evidence:
            return ""
        bp_slide = next(
            (s for s in blueprint.slides if s.slide_id == slide_id), None
        )
        if not bp_slide:
            return ""

        parts: list[str] = []
        matched_ids: set[str] = set()

        # Build search keywords
        search_kw: set[str] = set()
        for item in (bp_slide.must_cover_subset or []):
            for word in re.split(r'[\s_]+', item):
                cl = re.sub(r'[^a-zA-Z]', '', word).lower()
                if len(cl) > SpatialThresholds.KEYWORD_MIN_LEN:
                    search_kw.add(cl)
        if hasattr(bp_slide, 'primary_proposition') and bp_slide.primary_proposition:
            for word in bp_slide.primary_proposition.split():
                cl = re.sub(r'[^a-zA-Z]', '', word).lower()
                if len(cl) > SpatialThresholds.KEYWORD_MIN_LEN_PROP:
                    search_kw.add(cl)

        # Linked evidence chunks
        for chunk in evidence.chunks:
            if chunk.chunk_id in (bp_slide.linked_evidence_ids or []):
                parts.append(f"[{chunk.chunk_id}] {chunk.content[:SpatialThresholds.CHUNK_MAX_CHARS]}")
                matched_ids.add(chunk.chunk_id)
            if len(matched_ids) >= SpatialThresholds.MAX_EVIDENCE_CHUNKS:
                break

        # Keyword fallback
        if len(matched_ids) < SpatialThresholds.MAX_EVIDENCE_CHUNKS and search_kw:
            for chunk in evidence.chunks:
                if chunk.chunk_id in matched_ids:
                    continue
                sec = chunk.metadata.get("section", "").lower()
                clow = chunk.content[:300].lower()
                words = (
                    set(re.sub(r'[^a-zA-Z\s]', '', sec).split())
                    | set(re.sub(r'[^a-zA-Z\s]', '', clow).split())
                )
                if search_kw & words and len(chunk.content.strip()) > SpatialThresholds.MIN_CONTENT_LEN:
                    parts.append(f"[{chunk.chunk_id}] {chunk.content[:SpatialThresholds.CHUNK_MAX_CHARS]}")
                    matched_ids.add(chunk.chunk_id)
                if len(matched_ids) >= SpatialThresholds.MAX_EVIDENCE_CHUNKS:
                    break

        return "\n\n".join(parts)
