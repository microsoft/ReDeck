"""DeckPlanner - deck-level narrative planning via LLM.

Upgraded evidence flow:
  - For papers <80K chars: passes full paper_full.md to the planning LLM
  - For longer papers: section previews at 800 chars each
  - Table data previews included (not just captions)
  - Figure descriptions included
"""

import json
import logging
from pathlib import Path

from ..llm_client import LLMClient
from ..schemas.blueprint import DeckBlueprint
from ..schemas.evidence import EvidenceState
from ..schemas.experiment_config import ExperimentConfig
from ..schemas.intent import IntentState
from ..utils.io_utils import read_text

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "planner" / "deck_planner.system.md"

# Maximum paper_full.md size (chars) for direct inclusion in planner context.
# 80K chars ~ 20K tokens — fits comfortably in 128K context models.
FULL_TEXT_THRESHOLD = 80_000


class DeckPlanner:
    """Produces a DeckBlueprint from IntentState and EvidenceState."""

    def __init__(self, llm: LLMClient, config: ExperimentConfig):
        self.llm = llm
        self.config = config
        self.system_prompt = read_text(PROMPT_PATH)
        self._load_shared_rules()

    def _load_shared_rules(self) -> None:
        shared_dir = Path(__file__).parent.parent / "prompts" / "shared"
        json_rules = read_text(shared_dir / "json_output_rules.md")
        uncertainty = read_text(shared_dir / "uncertainty_policy.md")
        self.system_prompt = f"{self.system_prompt}\n\n{json_rules}\n\n{uncertainty}"

    def plan(
        self,
        intent: IntentState,
        evidence: EvidenceState,
        task_brief: str,
        paper_full_md: str | None = None,
        source_store=None,
    ) -> DeckBlueprint:
        """Generate a deck blueprint.

        Args:
            intent: Intent state with audience, page budget, etc.
            evidence: Indexed evidence state.
            task_brief: Task brief text.
            paper_full_md: Full markdown text of the paper (optional).
            source_store: SourceStore instance (optional). If provided,
                uses structured summary index for better planning context.
        """
        if source_store is not None:
            evidence_summary = self._build_planner_context(source_store, paper_full_md)
        else:
            evidence_summary = self._summarize_evidence(evidence, paper_full_md)
        user_content = json.dumps({
            "intent": intent.model_dump(),
            "task_brief": task_brief,
            "source_summary": evidence_summary,
            "page_budget": intent.page_budget,
            "must_cover": intent.must_cover,
            "must_avoid": intent.must_avoid,
        }, indent=2, ensure_ascii=False)

        model = self.config.models.get_model("deck_planner")

        strict_directive = (
            "\n\n[STRICT OUTPUT REQUIREMENT] You MUST return a complete "
            "DeckBlueprint JSON with fields: case_id (string), total_slides "
            "(int), narrative_arc (string), slides (list[BlueprintSlide]). "
            "DO NOT return {\"status\": \"need_more_context\"} or any escape "
            "hatch — the source_summary above contains enough context. "
            "Plan with what you have."
        )
        try:
            blueprint = self.llm.call_json(
                system_prompt=self.system_prompt + strict_directive,
                user_content=user_content,
                response_model=DeckBlueprint,
                model=model,
                module_name="deck_planner",
                prompt_version="deck_planner.system.v2",
                max_tokens=9182,
                input_packet={"intent": intent.model_dump()},
            )
        except Exception as e:
            # Last-ditch: if planner keeps returning need_more_context, fall
            # back to a minimal blueprint built from source_store structure.
            logger.error("DeckPlanner failed validation after retries: %s. "
                         "Falling back to skeletal blueprint.", str(e)[:300])
            blueprint = self._fallback_blueprint(intent, evidence, source_store)

        # Post-LLM: back-fill linked_evidence_ids from new fields (backward compat)
        if source_store is not None:
            self._backfill_linked_evidence_ids(blueprint, source_store)

        # Post-LLM: validate and fill figure assignments
        self._assign_figures(blueprint, evidence, source_store)

        # Post-LLM: validate slide count is within page budget
        page_budget = intent.page_budget or [10, 13]
        min_slides, max_slides = page_budget[0], page_budget[1]
        actual = blueprint.total_slides
        if actual < min_slides or actual > max_slides:
            logger.warning(
                "DeckPlanner produced %d slides (budget: %d-%d). "
                "Adjusting total_slides to match actual slide count.",
                actual, min_slides, max_slides,
            )
        # Always sync total_slides with actual slide list length
        blueprint.total_slides = len(blueprint.slides)

        logger.info("DeckPlanner produced %d slides", blueprint.total_slides)
        return blueprint

    def _fallback_blueprint(
        self,
        intent: IntentState,
        evidence: EvidenceState,
        source_store=None,
    ) -> DeckBlueprint:
        """Build a minimal skeletal blueprint when LLM repeatedly fails."""
        from ..schemas.blueprint import BlueprintSlide
        page_budget = intent.page_budget or [10, 13]
        n = max(page_budget[0], 10)
        roles = [
            ("title", "opening", "Title and authors"),
            ("context", "opening", "Problem motivation"),
            ("context", "body", "Background and prior work"),
            ("method", "body", "Approach overview"),
            ("method", "body", "Key technical contribution"),
            ("results", "body", "Main experimental results"),
            ("results", "body", "Comparison with baselines"),
            ("results", "body", "Ablations and analysis"),
            ("comparison", "body", "Discussion and limitations"),
            ("conclusion", "closing", "Summary and impact"),
        ]
        slides = []
        for i, (role, pos, prop) in enumerate(roles[:n], start=1):
            slides.append(BlueprintSlide(
                slide_id=i, role=role, primary_proposition=prop,
                narrative_position=pos,
            ))
        return DeckBlueprint(
            case_id=intent.case_id if hasattr(intent, 'case_id') else "fallback",
            total_slides=len(slides),
            narrative_arc="problem -> method -> results -> conclusion (fallback skeleton)",
            slides=slides,
            reasoning="Fallback skeleton blueprint (LLM planner returned need_more_context)",
        )

    @staticmethod
    def _assign_figures(
        blueprint: DeckBlueprint,
        evidence: EvidenceState,
        source_store=None,
    ) -> None:
        """Normalize figure references and assign one real asset per slide.

        SourceStore uses canonical A### IDs while legacy evidence and planner
        responses may use extractor IDs such as ``fig_p7_img0``. Treat the
        image stem and both ID namespaces as aliases, but always write a
        canonical SourceStore ID when one is available.
        """
        aliases: dict[str, str] = {}
        valid_ids: set[str] = set()

        def add_alias(alias: str | None, canonical: str) -> None:
            if not alias:
                return
            cleaned = str(alias).strip()
            if cleaned:
                aliases.setdefault(cleaned, canonical)
                aliases.setdefault(cleaned.lower(), canonical)

        if source_store is not None:
            for asset in source_store.assets:
                if (
                    asset.type != "figure"
                    or not asset.image_path
                    or not Path(asset.image_path).is_file()
                ):
                    continue
                valid_ids.add(asset.asset_id)
                add_alias(asset.asset_id, asset.asset_id)
                add_alias(Path(asset.image_path).stem, asset.asset_id)

        asset_by_path = {
            str(Path(asset.image_path).resolve()): asset.asset_id
            for asset in getattr(source_store, "assets", [])
            if asset.asset_id in valid_ids and asset.image_path
        }
        for figure in evidence.figures:
            if (
                figure.figure_type in ("page_screenshot", "table_screenshot")
                or not figure.image_path
                or not Path(figure.image_path).is_file()
            ):
                continue
            canonical = asset_by_path.get(str(Path(figure.image_path).resolve()))
            if canonical is None:
                stem_match = aliases.get(Path(figure.image_path).stem)
                canonical = stem_match or figure.figure_id
                if canonical == figure.figure_id:
                    valid_ids.add(canonical)
            add_alias(figure.figure_id, canonical)
            add_alias(Path(figure.image_path).stem, canonical)

        def canonicalize(candidate: str | None) -> str | None:
            if not candidate:
                return None
            cleaned = str(candidate).strip()
            canonical = aliases.get(cleaned) or aliases.get(cleaned.lower())
            return canonical if canonical in valid_ids else None

        # Normalize known aliases in asset_ids so source bundles use A### IDs.
        for slide in blueprint.slides:
            normalized_asset_ids: list[str] = []
            for asset_id in slide.asset_ids:
                normalized = canonicalize(asset_id) or asset_id
                if normalized not in normalized_asset_ids:
                    normalized_asset_ids.append(normalized)
            slide.asset_ids = normalized_asset_ids

        used: set[str] = set()

        # Pass 1: validate LLM assignments (keep first, clear duplicates/invalid)
        for slide in blueprint.slides:
            original = slide.assigned_figure_id
            fid = canonicalize(original)
            if fid and fid not in used:
                slide.assigned_figure_id = fid
                used.add(fid)
            elif original:
                logger.warning(
                    "Slide %d: clearing invalid/duplicate assigned_figure_id '%s'",
                    slide.slide_id, original,
                )
                slide.assigned_figure_id = ""

        doc_block_assets: dict[str, list[str]] = {}
        if source_store is not None:
            doc_block_assets = {
                block.doc_block_id: block.linked_asset_ids
                for block in source_store.doc_block_plan.blocks
            }

        # Pass 2: use all planner evidence fields in decreasing specificity.
        for slide in blueprint.slides:
            if slide.assigned_figure_id:
                continue
            candidates = [
                ("asset_ids", slide.asset_ids),
                ("linked_evidence_ids", slide.linked_evidence_ids),
                (
                    "source_doc_block_ids",
                    [
                        asset_id
                        for block_id in slide.source_doc_block_ids
                        for asset_id in doc_block_assets.get(block_id, [])
                    ],
                ),
            ]
            for source_name, source_ids in candidates:
                for source_id in source_ids:
                    fid = canonicalize(source_id)
                    if fid and fid not in used:
                        slide.assigned_figure_id = fid
                        used.add(fid)
                        logger.info(
                            "Slide %d: auto-assigned figure '%s' from %s",
                            slide.slide_id, fid, source_name,
                        )
                        break
                if slide.assigned_figure_id:
                    break

        # Keep the typed asset field consistent for source-bundle creation.
        for slide in blueprint.slides:
            fid = slide.assigned_figure_id
            if fid and fid not in slide.asset_ids:
                slide.asset_ids.append(fid)

        assigned_count = sum(1 for s in blueprint.slides if s.assigned_figure_id)
        logger.info(
            "Figure assignment: %d/%d slides have assigned figures (%d available)",
            assigned_count, len(blueprint.slides), len(valid_ids),
        )

    def _build_planner_context(
        self, source_store, paper_full_md: str | None = None
    ) -> str:
        """Build planner context from SourceStore's summary index.

        Uses the structured summary index for document blocks, assets, and
        tables. Optionally includes full paper text for short papers.
        """
        parts: list[str] = []

        # --- Full text for short papers ---
        if paper_full_md and len(paper_full_md) <= FULL_TEXT_THRESHOLD:
            parts.append("## Full Paper Text")
            parts.append(
                "Below is the complete paper text. Use doc_block IDs (DB###), "
                "asset IDs (A###), and table IDs (T###) from the index below "
                "for source_doc_block_ids, asset_ids, and table_ids.\n"
            )
            parts.append(paper_full_md)
            parts.append("")
            logger.info(
                "DeckPlanner: using full paper text (%d chars) in planning context",
                len(paper_full_md),
            )

        # --- Summary index (always included) ---
        summary_text = source_store.format_summary_index()
        if summary_text:
            parts.append(summary_text)

        # --- Anchored doc preview for long papers without full text ---
        if paper_full_md and len(paper_full_md) > FULL_TEXT_THRESHOLD:
            logger.info(
                "DeckPlanner: paper too long (%d chars > %d), using summary index only",
                len(paper_full_md), FULL_TEXT_THRESHOLD,
            )

        return "\n".join(parts)

    @staticmethod
    def _backfill_linked_evidence_ids(blueprint: DeckBlueprint, source_store) -> None:
        """Back-fill linked_evidence_ids from source_doc_block_ids for backward compat.

        Maps doc_block_ids → their constituent atomic block IDs, so downstream
        consumers that still read linked_evidence_ids get valid references.
        """
        # Build doc_block_id → atomic block_ids mapping
        db_to_atoms: dict[str, list[str]] = {}
        for db in source_store.doc_block_plan.blocks:
            db_to_atoms[db.doc_block_id] = list(db.included_atomic_block_ids)

        for slide in blueprint.slides:
            if slide.source_doc_block_ids and not slide.linked_evidence_ids:
                atom_ids: list[str] = []
                for dbid in slide.source_doc_block_ids:
                    atom_ids.extend(db_to_atoms.get(dbid, []))
                slide.linked_evidence_ids = atom_ids
                if atom_ids:
                    logger.debug(
                        "Slide %d: back-filled %d linked_evidence_ids from %d doc_blocks",
                        slide.slide_id, len(atom_ids), len(slide.source_doc_block_ids),
                    )

    def _summarize_evidence(
        self, evidence: EvidenceState, paper_full_md: str | None = None
    ) -> str:
        """Create a structured summary of available evidence for the planner.

        Strategy:
          - If paper_full_md is short (<80K chars): include full text directly.
            The planner sees the complete paper content for high-quality planning.
          - If paper_full_md is long: section headings + 800 char previews.
          - Always include chunk_id index for linking, table data previews,
            and figure descriptions.
        """
        parts = []

        # --- Full text or section previews ---
        if paper_full_md and len(paper_full_md) <= FULL_TEXT_THRESHOLD:
            # Short paper: include full text directly
            parts.append("## Full Paper Text")
            parts.append("Below is the complete paper text. Use chunk_ids from the ")
            parts.append("index below for linked_evidence_ids.\n")
            parts.append(paper_full_md)
            parts.append("")

            # Still provide chunk index for linking
            if evidence.chunks:
                parts.append(f"\n## Chunk Index ({len(evidence.chunks)} chunks)")
                parts.append("Use ONLY these chunk_ids in linked_evidence_ids:")
                for chunk in evidence.chunks:
                    section = chunk.metadata.get("section", chunk.metadata.get("heading", ""))
                    page_ref = chunk.page_ref or ""
                    if section:
                        parts.append(f"  - [{chunk.chunk_id}] **{section}** {page_ref}")
                    else:
                        parts.append(f"  - [{chunk.chunk_id}] {page_ref}")

            logger.info(
                "DeckPlanner: using full paper text (%d chars) in planning context",
                len(paper_full_md),
            )
        else:
            # Long paper or no full text: section previews (800 chars each)
            preview_len = 800 if paper_full_md else 500
            if evidence.chunks:
                parts.append(f"## Text Sections ({len(evidence.chunks)} available)")
                parts.append("Use ONLY these chunk_ids in linked_evidence_ids:")
                for chunk in evidence.chunks:
                    section = chunk.metadata.get("section", chunk.metadata.get("heading", ""))
                    page_ref = chunk.page_ref or ""
                    preview = chunk.content.strip()[:preview_len].replace("\n", " ")
                    if section:
                        parts.append(f"  - [{chunk.chunk_id}] **{section}** {page_ref}: {preview}...")
                    else:
                        parts.append(f"  - [{chunk.chunk_id}] {page_ref}: {preview}...")

            if paper_full_md:
                logger.info(
                    "DeckPlanner: paper too long (%d chars > %d), using %d-char previews",
                    len(paper_full_md), FULL_TEXT_THRESHOLD, preview_len,
                )

        # --- Figures ---
        if evidence.figures:
            # Separate content figures from screenshots
            content_figs = [f for f in evidence.figures if f.figure_type != "page_screenshot"]
            if content_figs:
                parts.append(f"\n## Figures ({len(content_figs)} available)")
                for fig in content_figs[:30]:
                    page_info = f" (p{fig.page_number})" if fig.page_number else ""
                    # Prefer VLM description > PDF caption > generic
                    if fig.description and "image from page" not in fig.description.lower():
                        desc = fig.description[:150]
                    elif fig.caption and len(fig.caption) > 10:
                        desc = f"Caption: \"{fig.caption[:120]}\""
                    else:
                        desc = f"{fig.figure_type} figure"
                    parts.append(f"  - [{fig.figure_id}]{page_info} {desc}")
                if len(content_figs) > 30:
                    parts.append(f"  ... and {len(content_figs) - 30} more figures")

        # --- Tables (with data previews) ---
        if evidence.tables:
            parts.append(f"\n## Tables ({len(evidence.tables)} available)")
            for tab in evidence.tables:
                hdrs = ", ".join(tab.headers[:5]) if tab.headers else "no headers"
                page_info = f" (p{tab.page_number})" if tab.page_number else ""
                cap = f" \"{tab.caption}\"" if tab.caption else ""
                parts.append(
                    f"  - [{tab.table_id}]{page_info}{cap} "
                    f"({tab.row_count} rows, columns: {hdrs})"
                )
                # Include VLM description if available
                if tab.description:
                    parts.append(f"    VLM: {tab.description[:200]}")
                # Include table data preview (first 300 chars of content)
                elif tab.content:
                    data_preview = tab.content[:300].replace("\n", " | ")
                    parts.append(f"    Data: {data_preview}")

        # --- Formulas ---
        if evidence.formulas:
            parts.append(f"\n## Formulas ({len(evidence.formulas)} available)")
            for f in evidence.formulas[:5]:
                parts.append(f"  - [{f.formula_id}] ${f.latex[:60]}$")

        return "\n".join(parts)
