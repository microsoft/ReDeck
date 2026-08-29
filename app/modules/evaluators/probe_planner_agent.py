"""ProbePlannerAgent — adaptive evaluation via per-probe scheduling.

Instead of running monolithic judges (one 800-line prompt per family),
this agent:
1. Sees rendered slide PNGs + previous issue history
2. Decides which SPECIFIC probes (e.g., B03, B13, D01) to run on which slides
3. Each probe tool = one focused LLM call via ProbeRunner
4. Collects all probe results and returns the combined issue list

This replaces the family-level tool approach (probe_visual, probe_correctness)
with per-probe-id granularity for better precision and less attention dilution.
"""

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...llm_client import LLMClient
from ...schemas.blueprint import DeckBlueprint
from ...schemas.evidence import EvidenceState
from ...schemas.experiment_config import ExperimentConfig
from ...schemas.extraction import SlideExtraction
from ...schemas.issue import Issue
from ...schemas.issue_types import (
    DECK_LEVEL_PROBES,
    PROBE_REGISTRY,
    IssueFamily,
    get_atomic_check_registry,
)
from ...schemas.common import IssueStatus, Verdict
from ...utils.image_ops import image_to_base64
from ...utils.issue_identity import issues_share_target
from .probe_runner import ProbeRunner

if TYPE_CHECKING:
    from ...orchestrator.eval_router import EvalRouter

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 12
_CONTENT_CHANGE_SENSITIVE_FAMILIES = frozenset({IssueFamily.D, IssueFamily.E})
_PROMPT_PATH = (
    Path(__file__).parent.parent.parent
    / "prompts" / "evaluator" / "probe_planner.system.md"
)


def _normalize_probe_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _quoted_wrong_candidates(issue: Issue, correct_norm: str) -> set[str]:
    evidence = getattr(issue, "evidence", None)
    fix_detail = getattr(issue, "fix_detail", None)
    fields = (
        getattr(evidence, "description", ""),
        getattr(issue, "why_this_fails", ""),
        getattr(issue, "planned_fix", ""),
        getattr(fix_detail, "target_location", "") if fix_detail else "",
    )
    candidates: set[str] = set()
    for field in fields:
        for raw in re.findall(r"[\"'\u201c\u201d]([^\"'\u201c\u201d]{3,160})[\"'\u201c\u201d]", str(field or "")):
            norm = _normalize_probe_text(raw)
            if not norm or norm == correct_norm or correct_norm in norm:
                continue
            candidates.add(norm)
    return candidates


class ProbePlannerAgent:
    """Agentic probe planner that selectively invokes per-probe evaluations."""

    def __init__(self, eval_router: "EvalRouter", llm: LLMClient, config: ExperimentConfig):
        self.router = eval_router
        self.llm = llm
        self.config = config
        self.system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
        self.probe_runner = ProbeRunner(llm, config)

    def evaluate(
        self,
        extractions: list[SlideExtraction],
        png_paths: list[str],
        task_brief: str,
        source_summary: str,
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
        modified_slides: set[int] | None = None,
        content_modified_slides: set[int] | None = None,
        spatial_signals: dict | None = None,
        source_store: Any = None,
    ) -> list[Issue]:
        """Run adaptive probe evaluation via agent loop."""
        # Store context for tool handlers
        self._extractions = extractions
        self._png_paths = png_paths
        self._task_brief = task_brief
        self._source_summary = source_summary
        self._blueprint = blueprint
        self._evidence = evidence
        self._source_store = source_store
        self._turn_index = turn_index
        self._modified_slides = modified_slides or set()
        self._content_modified_slides = content_modified_slides
        self._spatial_signals = spatial_signals
        self._previous_issues = previous_issues
        self._collected_issues: list[Issue] = []

        # Build initial message with slide images
        user_content = self._build_user_message(previous_issues)
        model = self.config.models.get_model("probe_planner")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        # Agent loop
        tool_calls = 0
        while tool_calls < MAX_TOOL_CALLS:
            try:
                response = self.llm.call_multiturn(
                    messages=messages,
                    model=model,
                    module_name="probe_planner",
                    prompt_version="probe_planner.v2",
                    max_tokens=2048,
                    temperature=0.2,
                )
            except Exception as e:
                logger.warning("ProbePlannerAgent LLM error: %s", str(e)[:200])
                return self._fallback_full_eval(previous_issues, turn_index)

            messages.append({"role": "assistant", "content": response})

            action = self._parse_action(response)
            if action is None:
                messages.append({"role": "user", "content":
                    "Error: could not parse your response. "
                    "Return a JSON object with a 'tool' field. "
                    "Available tools: run_probe, run_probes, submit_evaluation."
                })
                tool_calls += 1
                continue

            tool_name = action.get("tool", "")

            if tool_name == "submit_evaluation":
                reasoning = action.get("reasoning", "")
                logger.info(
                    "ProbePlannerAgent: submitted after %d tool calls. "
                    "Reasoning: %s. Total issues: %d",
                    tool_calls, reasoning[:200], len(self._collected_issues),
                )
                return self._finalize()

            # Execute tool
            handler = {
                "run_probe": self._handle_run_probe,
                "run_probes": self._handle_run_probes,
                "run_checks": self._handle_run_checks,
                # Legacy family-level tools (backward compat)
                "probe_visual": self._handle_legacy_probe,
                "probe_correctness": self._handle_legacy_probe,
                "probe_fidelity": self._handle_legacy_probe,
                "probe_completeness": self._handle_legacy_probe,
                "probe_narrative": self._handle_legacy_probe,
            }.get(tool_name)

            if handler is None:
                messages.append({"role": "user", "content":
                    f"Unknown tool: '{tool_name}'. "
                    f"Available: run_probe, run_probes, submit_evaluation."
                })
                tool_calls += 1
                continue

            try:
                result_text = handler(action)
            except Exception as e:
                result_text = f"Probe failed: {str(e)[:200]}"
                logger.warning("Probe tool %s failed: %s", tool_name, e)

            messages.append({"role": "user", "content":
                f"Probe result:\n\n{result_text}\n\n"
                f"Call more probes or submit_evaluation when done."
            })
            tool_calls += 1

        # Exhausted tool calls
        logger.warning(
            "ProbePlannerAgent exhausted %d tool calls. Returning %d issues.",
            MAX_TOOL_CALLS, len(self._collected_issues),
        )
        return self._finalize()

    # ================================================================
    # TOOL HANDLERS
    # ================================================================

    def _eligible_slide_ids(self, probe_id: str, requested: list[int]) -> list[int]:
        """Return valid slides on which this probe is meaningful this turn."""
        available = [ext.slide_id for ext in self._extractions]
        if probe_id in DECK_LEVEL_PROBES:
            slide_ids = available
        else:
            available_set = set(available)
            slide_ids = [
                sid for sid in dict.fromkeys(requested)
                if sid in available_set
            ]

        probe_def = PROBE_REGISTRY[probe_id]
        if (
            self._content_modified_slides is not None
            and probe_def.family in _CONTENT_CHANGE_SENSITIVE_FAMILIES
        ):
            slide_ids = [
                sid for sid in slide_ids
                if sid in self._content_modified_slides
            ]
        return slide_ids

    def _previous_issues_for_probe(
        self,
        probe_id: str,
        slide_ids: list[int],
    ) -> list[Issue] | None:
        """Scope prior findings to the same issue type and eligible slides."""
        if not self._previous_issues:
            return None
        issue_type = PROBE_REGISTRY[probe_id].name
        return [
            issue for issue in self._previous_issues
            if issue.issue_type == issue_type
            and any(sid in slide_ids for sid in (issue.affected_slides or []))
        ] or None

    def _handle_run_probe(self, action: dict) -> str:
        """Handle a single run_probe call."""
        probe_id = action.get("probe_id", "")
        slide_ids = action.get("slide_ids", [])

        if not probe_id or probe_id not in PROBE_REGISTRY:
            return f"Error: unknown probe_id '{probe_id}'. See probe catalog."

        slide_ids = self._eligible_slide_ids(probe_id, slide_ids)

        if not slide_ids:
            return f"SKIPPED: run_probe({probe_id}) has no eligible slides this turn."

        # Filter previous issues for this probe's issue type
        prev = self._previous_issues_for_probe(probe_id, slide_ids)

        issues = self.probe_runner.run_probe(
            probe_id=probe_id,
            slide_ids=slide_ids,
            extractions=self._extractions,
            png_paths=self._png_paths,
            spatial_signals=self._spatial_signals,
            source_summary=self._source_summary,
            task_brief=self._task_brief,
            blueprint=self._blueprint,
            evidence=self._evidence,
            source_store=self._source_store,
            previous_issues=prev,
            turn_index=self._turn_index,
        )
        self._collected_issues.extend(issues)
        return self._format_probe_result(probe_id, slide_ids, issues)

    def _handle_run_probes(self, action: dict) -> str:
        """Handle batched run_probes call — runs probes in parallel."""
        probes = action.get("probes", [])
        if not probes:
            return "Error: run_probes requires a 'probes' list."

        results: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}
            for spec in probes:
                pid = spec.get("probe_id", "")
                if not pid or pid not in PROBE_REGISTRY:
                    results[pid] = f"SKIPPED: unknown probe_id '{pid}'"
                    continue

                sids = self._eligible_slide_ids(pid, spec.get("slide_ids", []))
                if not sids:
                    results[pid] = "SKIPPED: no eligible slides this turn"
                    continue

                prev = self._previous_issues_for_probe(pid, sids)

                fut = pool.submit(
                    self.probe_runner.run_probe,
                    probe_id=pid,
                    slide_ids=sids,
                    extractions=self._extractions,
                    png_paths=self._png_paths,
                    spatial_signals=self._spatial_signals,
                    source_summary=self._source_summary,
                    task_brief=self._task_brief,
                    blueprint=self._blueprint,
                    evidence=self._evidence,
                    source_store=self._source_store,
                    previous_issues=prev,
                    turn_index=self._turn_index,
                )
                futures[fut] = pid

            for fut in as_completed(futures):
                pid = futures[fut]
                try:
                    issues = fut.result()
                    self._collected_issues.extend(issues)
                    issue_summary = ", ".join(
                        f"S{iss.affected_slides[0]}:{iss.severity.value}"
                        for iss in issues[:5]
                    )
                    results[pid] = f"{len(issues)} issues" + (f" ({issue_summary})" if issues else "")
                except Exception as e:
                    results[pid] = f"FAILED: {str(e)[:100]}"
                    logger.warning("Probe %s failed in batch: %s", pid, e)

        # Format summary
        lines = ["Batch probe results:"]
        for pid, summary in sorted(results.items()):
            lines.append(f"  {pid}: {summary}")
        return "\n".join(lines)

    def _handle_run_checks(self, action: dict) -> str:
        """Handle run_checks: map atomic check IDs → parent probes, deduplicate, execute."""
        checks = action.get("checks", [])
        if not checks:
            return "Error: run_checks requires a 'checks' list."

        atomic_reg = get_atomic_check_registry()

        # One parent probe must run at most once per planner action. Atomic checks
        # can request different slide subsets, but splitting those subsets into
        # concurrent calls would triage and mutate the same previous Issue object
        # multiple times in one repair turn.
        groups: dict[str, dict[str, set]] = {}
        unknown = []

        for spec in checks:
            check_id = spec.get("check_id", "")
            slide_ids = spec.get("slide_ids", [])

            # Resolve parent probe: try atomic registry first, then treat as bare probe_id
            parent = atomic_reg.get(check_id)
            if parent is None:
                # Maybe it's already a probe_id like "B03"
                bare = check_id.rsplit(".", 1)[0] if "." in check_id else check_id
                if bare in PROBE_REGISTRY:
                    parent = bare
                else:
                    unknown.append(check_id)
                    continue

            slide_ids = self._eligible_slide_ids(parent, slide_ids)

            group = groups.setdefault(
                parent,
                {"slide_ids": set(), "check_ids": set()},
            )
            group["slide_ids"].update(slide_ids)
            group["check_ids"].add(check_id)

        if not groups and unknown:
            return f"Error: unknown check_ids: {unknown}. Use IDs from the catalog (e.g., B03.1)."

        # Execute one probe per group in parallel
        results: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}
            for probe_id, group in groups.items():
                sids = sorted(group["slide_ids"])
                check_ids = sorted(group["check_ids"])
                if not sids:
                    results[f"{probe_id}({','.join(check_ids)})"] = "SKIPPED: no slide_ids"
                    continue

                prev = self._previous_issues_for_probe(probe_id, sids)

                fut = pool.submit(
                    self.probe_runner.run_probe,
                    probe_id=probe_id,
                    slide_ids=sids,
                    extractions=self._extractions,
                    png_paths=self._png_paths,
                    spatial_signals=self._spatial_signals,
                    source_summary=self._source_summary,
                    task_brief=self._task_brief,
                    blueprint=self._blueprint,
                    evidence=self._evidence,
                    source_store=self._source_store,
                    previous_issues=prev,
                    turn_index=self._turn_index,
                    selected_check_ids=check_ids,
                )
                futures[fut] = (probe_id, check_ids, sids)

            for fut in as_completed(futures):
                probe_id, check_ids, sids = futures[fut]
                label = f"{probe_id}[{','.join(check_ids)}] on S{sids}"
                try:
                    issues = fut.result()
                    self._collected_issues.extend(issues)
                    issue_summary = ", ".join(
                        f"S{iss.affected_slides[0]}:{iss.severity.value}"
                        for iss in issues[:5]
                    )
                    results[label] = f"{len(issues)} issues" + (f" ({issue_summary})" if issues else "")
                except Exception as e:
                    results[label] = f"FAILED: {str(e)[:100]}"
                    logger.warning("Probe %s (checks %s) failed: %s", probe_id, check_ids, e)

        # Format summary
        lines = ["Check results:"]
        for label, summary in sorted(results.items()):
            lines.append(f"  {label}: {summary}")
        if unknown:
            lines.append(f"  Unknown check_ids skipped: {unknown}")
        return "\n".join(lines)

    def _handle_legacy_probe(self, action: dict) -> str:
        """Handle legacy family-level probe calls by delegating to the router's judges."""
        tool_name = action.get("tool", "")
        # Map legacy tool to family
        family_map = {
            "probe_visual": "B_visual",
            "probe_correctness": "D",
            "probe_fidelity": "E",
            "probe_completeness": "C",
            "probe_narrative": "A",
        }
        family = family_map.get(tool_name, "")

        # Suggest using run_probes instead
        return (
            f"Legacy tool '{tool_name}' is deprecated. "
            f"Use run_probes with specific probe IDs instead. "
            f"For {family} family, available probes: "
            + ", ".join(
                pid for pid, d in sorted(PROBE_REGISTRY.items())
                if d.family.value == family
            )
        )

    # ================================================================
    # HELPERS
    # ================================================================

    def _dedup_collected(self) -> list[Issue]:
        """Deduplicate repeated probe results by semantic repair target."""
        result: list[Issue] = []
        for iss in self._collected_issues:
            if not any(issues_share_target(iss, existing) for existing in result):
                result.append(iss)
        return result

    def _finalize(self) -> list[Issue]:
        """Finalize evaluation: dedup + carry forward un-triaged previous issues.

        CRITICAL: If the planner didn't run a probe for a particular issue_type,
        the previous issues of that type on modified slides would be silently
        dropped. This method ensures ALL previous issues get a fate:
        - Triaged by a probe → already in _collected_issues (RESOLVED/PERSISTED/etc)
        - NOT triaged → carried forward as PERSISTED (conservative default)

        Without this, planner selectivity would cause issue lifecycle breaks.
        """
        deduped = self._dedup_collected()

        if not self._previous_issues:
            return deduped

        # Find which previous issue IDs were already handled by probes
        handled_ids = {iss.issue_id for iss in deduped}

        # Carry forward any un-triaged previous issues as PERSISTED
        untriaged_count = 0
        for prev_iss in self._previous_issues:
            if prev_iss.issue_id in handled_ids:
                continue
            if prev_iss.issue_type == "svg_visual_defect":
                # EvalRouter always runs the focused, enlarged B20 probe after
                # the adaptive planner. Carrying an untriaged B20 here would
                # incorrectly mark its slide as already evaluated and suppress
                # that mandatory current-render check.
                continue
            if prev_iss.status in (IssueStatus.RESOLVED, IssueStatus.WONT_FIX,
                                   IssueStatus.DEFERRED):
                # Terminal status — don't carry forward
                continue

            if self._untriaged_content_issue_now_resolved(prev_iss):
                prev_iss.status = IssueStatus.RESOLVED
                prev_iss.verdict = Verdict.PASS
                prev_iss.resolved_at_turn = self._turn_index
                prev_iss.planned_fix = (
                    f"[RESOLVED] (fallback text check at turn {self._turn_index}: "
                    "judge-verified correction is present in current slide text)"
                )
                deduped.append(prev_iss)
                handled_ids.add(prev_iss.issue_id)
                continue

            # This issue was on a modified slide but no probe triaged it.
            # Carry forward as PERSISTED so it doesn't disappear.
            prev_iss.planned_fix = (
                f"[PERSISTED] (not triaged by probe planner at turn "
                f"{self._turn_index})"
            )
            # Planner omission is not evidence that a repair persisted. Only
            # an actually executed probe may increment persisted_turns or
            # escalate an issue to regen/WONT_FIX.
            deduped.append(prev_iss)
            handled_ids.add(prev_iss.issue_id)
            untriaged_count += 1

        if untriaged_count:
            logger.warning(
                "ProbePlannerAgent: %d previous issues were not triaged by any "
                "probe — carried forward as PERSISTED to prevent lifecycle break",
                untriaged_count,
            )

        return deduped

    def _untriaged_content_issue_now_resolved(self, issue: Issue) -> bool:
        """Resolve simple untriaged C/D/E text fixes from current extraction.

        The planner deliberately carries untriaged issues forward, but that can
        create stale false positives when a content patch was already applied
        and the planner skipped the matching C/D/E probe. Use only exact,
        judge-provided correction text and quoted bad-string evidence; anything
        ambiguous remains open for normal probe triage.
        """
        family = (getattr(issue, "rubric_id", "") or "")[:1].upper()
        if family not in {"C", "D", "E"}:
            return False

        fix_detail = getattr(issue, "fix_detail", None)
        correct = getattr(fix_detail, "correct_content", "") if fix_detail else ""
        correct_norm = _normalize_probe_text(correct)
        if not correct_norm:
            return False

        current_norm = _normalize_probe_text(self._current_slide_text(issue))
        if correct_norm not in current_norm:
            return False

        wrong_candidates = _quoted_wrong_candidates(issue, correct_norm)
        if wrong_candidates:
            return not any(candidate in current_norm for candidate in wrong_candidates)

        issue_type = getattr(issue, "issue_type", "") or ""
        if family == "C" or issue_type.startswith("missing_"):
            return True

        # For D/E corrections without an identifiable bad string, stay
        # conservative; the correct text might have been added while the wrong
        # claim remains elsewhere on the slide.
        return False

    def _current_slide_text(self, issue: Issue) -> str:
        slide_ids = set(getattr(issue, "affected_slides", []) or [])
        fragments: list[str] = []
        for extraction in getattr(self, "_extractions", []) or []:
            if slide_ids and extraction.slide_id not in slide_ids:
                continue
            title = getattr(extraction, "title", "") or ""
            if title:
                fragments.append(title)
            for obj in getattr(extraction, "objects", []) or []:
                text = getattr(obj, "text_content", "") or ""
                if text:
                    fragments.append(text)
        return "\n".join(fragments)

    def _build_user_message(self, previous_issues: list[Issue] | None) -> list[dict]:
        """Build multimodal user message: slide PNGs + text context."""
        content: list[dict] = []
        text_parts = []

        # Previous issues summary
        if previous_issues:
            text_parts.append(f"## Previous Issues ({len(previous_issues)} total)\n")
            by_slide: dict[int, list[Issue]] = {}
            for iss in previous_issues:
                for sid in (iss.affected_slides or []):
                    by_slide.setdefault(sid, []).append(iss)
            for sid in sorted(by_slide):
                issues = by_slide[sid]
                text_parts.append(f"### Slide {sid}")
                for iss in issues:
                    text_parts.append(
                        f"- [{iss.status.value}] {iss.issue_type} ({iss.rubric_id}, "
                        f"{iss.severity.value}): {iss.why_this_fails[:80]}"
                    )
            text_parts.append("")

        # Modified slides info
        if self._modified_slides:
            text_parts.append(
                f"## Modified slides this turn: {sorted(self._modified_slides)}\n"
            )
            # B09 is mandatory on all modified slides — repair often fixes
            # overflow/overlap but introduces new whitespace/density imbalance.
            text_parts.append(
                "## MANDATORY: Run B09.1 and B09.14 on ALL modified slides.\n"
                "Repair frequently compresses content (fixing overflow) but leaves "
                "unbalanced whitespace — especially in multi-column layouts where "
                "one column ends much higher than another. Look carefully at:\n"
                "- Large empty regions in any corner or side of the slide\n"
                "- Columns that end at very different heights\n"
                "- Content clustered in one area while another area is empty\n"
                "- Elements that could be enlarged to fill available space\n"
                "Report B09 even if the slide has many words — density imbalance "
                "is about spatial distribution, not word count.\n"
            )
        if self._content_modified_slides is not None:
            text_parts.append(
                f"Content-modified slides (text changed): "
                f"{sorted(self._content_modified_slides)}\n"
            )

        # Slide metadata
        text_parts.append("## Slide Summary\n")
        for ext in self._extractions:
            marker = " [MODIFIED]" if ext.slide_id in self._modified_slides else ""
            text_parts.append(
                f"- Slide {ext.slide_id}{marker}: {ext.title or '(no title)'} "
                f"({len(ext.objects)} objects)"
            )

        text_parts.append(
            f"\nTurn index: {self._turn_index}. "
            f"Decide which probes to run and call them."
        )

        content.append({"type": "text", "text": "\n".join(text_parts)})

        # Slide images (modified slides + slides with open issues for repair turns, all for T0)
        if self._png_paths:
            slide_id_to_png = {}
            for ext, png in zip(self._extractions, self._png_paths):
                slide_id_to_png[ext.slide_id] = png

            if self._modified_slides:
                # Always include slides that have open issues from previous turns
                # so the probe planner can verify/triage them.
                open_issue_slides = set()
                if previous_issues:
                    for iss in previous_issues:
                        if iss.status == IssueStatus.OPEN:
                            for sid in (iss.affected_slides or []):
                                open_issue_slides.add(sid)
                target_slides = sorted(self._modified_slides | open_issue_slides)
            else:
                target_slides = [ext.slide_id for ext in self._extractions]

            for sid in target_slides:
                png_path = slide_id_to_png.get(sid)
                if png_path and Path(png_path).exists():
                    try:
                        b64 = image_to_base64(png_path, max_size=768)
                        content.append({"type": "text", "text": f"\n[Slide {sid}]"})
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": b64},
                        })
                    except Exception as e:
                        logger.warning("Failed to encode slide %d PNG: %s", sid, e)

        return content

    @staticmethod
    def _format_probe_result(
        probe_id: str,
        slide_ids: Any,
        issues: list[Issue],
    ) -> str:
        """Format probe results as text for the agent."""
        lines = [f"{probe_id} on slides {slide_ids}: {len(issues)} issues."]
        if not issues:
            lines.append("No issues detected.")
        else:
            for iss in issues[:10]:
                lines.append(
                    f"- [{iss.severity.value}] {iss.issue_type} "
                    f"(slides {iss.affected_slides}): "
                    f"{iss.why_this_fails[:120]}"
                )
            if len(issues) > 10:
                lines.append(f"... and {len(issues) - 10} more.")
        return "\n".join(lines)

    @staticmethod
    def _parse_action(response: str) -> dict | None:
        """Parse a tool call JSON from LLM response.

        Handles nested JSON structures (e.g., run_checks with nested check objects).
        When multiple tool calls appear in one response, returns the FIRST one
        (run_checks before submit_evaluation).
        """
        # Strategy 1: ```json ... ``` blocks
        for m in re.finditer(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL):
            try:
                data = json.loads(m.group(1))
                if "tool" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # Strategy 2: balanced-brace extraction — find all top-level { } blocks
        # This handles nested structures like {"tool":"run_checks","checks":[{...}]}
        candidates = []
        i = 0
        while i < len(response):
            if response[i] == '{':
                depth = 0
                start = i
                while i < len(response):
                    if response[i] == '{':
                        depth += 1
                    elif response[i] == '}':
                        depth -= 1
                        if depth == 0:
                            candidates.append(response[start:i+1])
                            break
                    # Skip string contents to avoid counting braces inside strings
                    elif response[i] == '"':
                        i += 1
                        while i < len(response) and response[i] != '"':
                            if response[i] == '\\':
                                i += 1  # skip escaped char
                            i += 1
                    i += 1
            else:
                i += 1

        # Return the FIRST valid tool call (prioritizes run_checks over submit)
        for block in candidates:
            try:
                data = json.loads(block)
                if isinstance(data, dict) and "tool" in data:
                    return data
            except json.JSONDecodeError:
                continue

        return None

    def _fallback_full_eval(
        self,
        previous_issues: list[Issue] | None,
        turn_index: int,
    ) -> list[Issue]:
        """Fall back to full evaluation if agent loop fails."""
        logger.warning("ProbePlannerAgent: falling back to full eval")
        return self.router._eval_family_plus_slide(
            self._extractions, self._png_paths,
            self._task_brief, self._source_summary,
            self._blueprint, self._evidence,
            previous_issues=previous_issues,
            turn_index=turn_index,
            modified_slides=self._modified_slides,
            content_modified_slides=self._content_modified_slides,
            _skip_planner=True,
        )
