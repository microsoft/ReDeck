"""Base judge class for LLM-based evaluation."""

import json
import logging
import re
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from ...llm_client import LLMClient
from ...schemas.blueprint import DeckBlueprint
from ...schemas.common import Confidence, IssueStatus, RepairAction, Severity, Verdict
from ...schemas.evidence import EvidenceState
from ...schemas.experiment_config import ExperimentConfig
from ...schemas.issue import FixDetail, Issue, IssueEvidence
from ...schemas.issue_types import VALID_ISSUE_TYPES, ALL_VALID_TYPES, SpatialThresholds
from ...utils.io_utils import read_text
from ...utils.json_utils import strip_code_fences
from ...utils.issue_identity import issues_share_target, stable_issue_id

logger = logging.getLogger(__name__)

# Flattened set used when rubric_family is unknown
_ALL_VALID_ISSUE_TYPES = ALL_VALID_TYPES


class BaseJudge:
    """Base class for all LLM-based judges."""

    rubric_family: str = ""
    module_name: str = ""
    prompt_filename: str = ""

    def __init__(self, llm: LLMClient, config: ExperimentConfig):
        self.llm = llm
        self.config = config
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = (
            Path(__file__).parent.parent.parent
            / "prompts" / "evaluator" / self.prompt_filename
        )
        prompt = read_text(prompt_path)
        # Append shared rules
        shared_dir = Path(__file__).parent.parent.parent / "prompts" / "shared"
        judgment_rules = read_text(shared_dir / "global_judgment_rules.md")
        json_rules = read_text(shared_dir / "json_output_rules.md")
        uncertainty = read_text(shared_dir / "uncertainty_policy.md")
        return f"{prompt}\n\n{judgment_rules}\n\n{json_rules}\n\n{uncertainty}"

    def _build_slide_evidence(
        self,
        slide_id: int,
        blueprint: DeckBlueprint | None,
        evidence: EvidenceState | None,
        source_store=None,
        slide_text: str = "",
        paper_text: str = "",
    ) -> str:
        """Build per-slide evidence mirroring BOTH codegen paths.

        If source_store is available, uses bundle for this slide directly.
        Otherwise falls back to legacy linked_evidence_ids matching.

        Must match the evidence selection from BOTH:
        - codegen_compiler._build_slide_prompt() (initial generation)
        - codegen_compiler._build_evidence_context() (repair)

        The key differences vs the old implementation:
        1. Keywords now include primary_proposition (not just must_cover_subset)
        2. Tables use keyword fallback (not just linked_evidence_ids)
        This prevents false "fabricated" / "numeric_error" issues when the
        evaluator can't find data that codegen legitimately used.
        """
        # --- V2: use bundle if available ---
        if source_store is not None:
            bundle = source_store.get_bundle(slide_id)
            if bundle and bundle.source_text:
                ev_parts = [bundle.source_text]
                for s in bundle.asset_summaries:
                    ev_parts.append(s)
                for s in bundle.table_summaries:
                    ev_parts.append(s)

                # Augment with full-paper search for slide-specific terms.
                # This closes the gap where codegen/repair used search_source
                # to find content outside the per-slide bundle, but the judge
                # only sees the bundle and may flag valid claims as fabricated.
                if slide_text and hasattr(source_store, 'anchored_doc') and source_store.anchored_doc:
                    paper = source_store.anchored_doc
                    # Extract distinctive terms from the slide text
                    _aug_terms: set[str] = set()
                    # Numbers with decimals or 3+ digits (likely specific data)
                    for m in re.finditer(r'\b\d+\.\d+\b|\b\d{3,}\b', slide_text):
                        _aug_terms.add(m.group())
                    # Capitalized multi-word phrases (proper nouns, method names)
                    for m in re.finditer(r'\b[A-Z][a-z]{2,}(?:[- ][A-Z][a-z]{2,})*\b', slide_text):
                        term = m.group()
                        if term.lower() not in {
                            "the", "this", "that", "figure", "table",
                            "slide", "section", "results", "method",
                        }:
                            _aug_terms.add(term)
                    # Search full paper for each term
                    _seen_pos: set[int] = set()
                    _aug_excerpts: list[str] = []
                    bundle_text = "\n".join(ev_parts).lower()
                    for term in sorted(_aug_terms)[:20]:
                        # Skip if already in the bundle
                        if term.lower() in bundle_text:
                            continue
                        pos = paper.lower().find(term.lower())
                        if pos < 0:
                            continue
                        if any(abs(pos - s) < 300 for s in _seen_pos):
                            continue
                        _seen_pos.add(pos)
                        start = max(0, pos - 200)
                        end = min(len(paper), pos + len(term) + 200)
                        excerpt = paper[start:end].replace("\n", " ").strip()
                        _aug_excerpts.append(f"[paper_search] ...{excerpt}...")
                        if len(_aug_excerpts) >= 8:
                            break
                    if _aug_excerpts:
                        ev_parts.append(
                            "\n## Additional source context (full-paper search)\n"
                            + "\n".join(_aug_excerpts)
                        )

                return "\n\n".join(ev_parts)

        # --- Legacy fallback ---
        if not blueprint or not evidence:
            return ""
        bp_slide = next(
            (s for s in blueprint.slides if s.slide_id == slide_id), None
        )
        if not bp_slide:
            return ""

        parts: list[str] = []
        matched_ids: set[str] = set()

        # Build search keywords from BOTH must_cover_subset AND
        # primary_proposition — mirrors codegen_compiler._build_slide_prompt()
        search_kw: set[str] = set()
        for item in (bp_slide.must_cover_subset or []):
            for word in re.split(r'[\s_]+', item):
                cl = re.sub(r'[^a-zA-Z]', '', word).lower()
                if len(cl) > SpatialThresholds.KEYWORD_MIN_LEN:
                    search_kw.add(cl)
        # Also add keywords from primary_proposition (was missing before!)
        if hasattr(bp_slide, 'primary_proposition') and bp_slide.primary_proposition:
            for word in bp_slide.primary_proposition.split():
                cl = re.sub(r'[^a-zA-Z]', '', word).lower()
                if len(cl) > SpatialThresholds.KEYWORD_MIN_LEN_PROP:
                    search_kw.add(cl)

        # Pass 1: linked evidence chunks (max CHUNK_MAX_CHARS each, max MAX_EVIDENCE_CHUNKS)
        for chunk in evidence.chunks:
            if chunk.chunk_id in (bp_slide.linked_evidence_ids or []):
                parts.append(f"[{chunk.chunk_id}] {chunk.content[:SpatialThresholds.CHUNK_MAX_CHARS]}")
                matched_ids.add(chunk.chunk_id)
            if len(matched_ids) >= SpatialThresholds.MAX_EVIDENCE_CHUNKS:
                break

        # Pass 2: keyword fallback (using full keyword set including
        # primary_proposition)
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
                    parts.append(
                        f"[{chunk.chunk_id}] {chunk.content[:SpatialThresholds.CHUNK_MAX_CHARS]}"
                    )
                    matched_ids.add(chunk.chunk_id)
                if len(matched_ids) >= SpatialThresholds.MAX_EVIDENCE_CHUNKS:
                    break

        # Pass 3: slide-text-derived keyword search
        # When the agent used search_source to find specific facts (entity
        # names, dataset names, numbers), those terms may not appear in the
        # blueprint's generic keywords.  Extract specific terms from the
        # slide text and search for matching evidence chunks.
        if (
            slide_text
            and len(matched_ids) < SpatialThresholds.MAX_EVIDENCE_CHUNKS
            and evidence
        ):
            # Extract potential proper nouns, dataset names, numbers
            # that are likely specific claims needing source backing
            slide_terms: set[str] = set()
            # Capitalized words (likely proper nouns / dataset names)
            for m in re.finditer(r'\b[A-Z][A-Za-z]{3,}\b', slide_text):
                slide_terms.add(m.group().lower())
            # Alphanumeric identifiers (e.g., "AlpacaEval", "GSM8K")
            for m in re.finditer(r'\b[A-Za-z]+\d+[A-Za-z]*\b', slide_text):
                slide_terms.add(m.group().lower())
            # Remove generic words that would match too many chunks
            _GENERIC = {
                "this", "that", "with", "from", "have", "each",
                "more", "most", "also", "only", "both", "does",
                "then", "when", "what", "will", "were", "been",
                "fine", "data", "loss", "step", "used", "model",
                "table", "slide", "figure", "section", "method",
                "score", "training", "results", "approach", "defense",
                "booster", "harmful", "tuning", "alignment",
            }
            slide_terms -= _GENERIC
            if slide_terms:
                for chunk in evidence.chunks:
                    if chunk.chunk_id in matched_ids:
                        continue
                    clow = chunk.content.lower()
                    # Require at least 2 slide-specific terms to match,
                    # or 1 highly specific term (len >= 6)
                    hits = [t for t in slide_terms if t in clow]
                    if len(hits) >= 2 or any(len(h) >= 6 for h in hits):
                        parts.append(
                            f"[{chunk.chunk_id}] {chunk.content[:SpatialThresholds.CHUNK_MAX_CHARS]}"
                        )
                        matched_ids.add(chunk.chunk_id)
                    if len(matched_ids) >= SpatialThresholds.MAX_EVIDENCE_CHUNKS:
                        break

        # Linked tables (1500 chars each) — by linked_evidence_ids
        matched_table_ids: set[str] = set()
        for tbl in evidence.tables:
            if tbl.table_id in (bp_slide.linked_evidence_ids or []):
                desc = f" — {tbl.description}" if tbl.description else ""
                parts.append(
                    f"[{tbl.table_id}]{desc}\n{tbl.content[:1500]}"
                )
                matched_table_ids.add(tbl.table_id)

        # Table keyword fallback — mirrors codegen_compiler._build_slide_prompt()
        # Without this, evaluator can't see tables that codegen found via
        # keyword matching, causing false "fabricated" issues.
        if not matched_table_ids and search_kw and evidence.tables:
            for tbl in evidence.tables:
                if tbl.table_id in matched_table_ids:
                    continue
                caption_lower = (tbl.caption or "").lower()
                content_lower = (tbl.content or "")[:200].lower()
                if any(kw in caption_lower or kw in content_lower
                       for kw in search_kw):
                    desc = f" — {tbl.description}" if tbl.description else ""
                    parts.append(
                        f"[{tbl.table_id}]{desc}\n{tbl.content[:1500]}"
                    )
                    matched_table_ids.add(tbl.table_id)
                    if len(matched_table_ids) >= 2:
                        break

        # Figure captions and descriptions — mirrors codegen_compiler.
        # _build_slide_prompt() which also provides figures to the code
        # generator.  Without this, data visible in figure captions
        # (e.g., win-rates, metric values) is invisible to the evaluator,
        # causing false "fabricated" / "numeric_error" judgments.
        if evidence.figures:
            embedded_figs = [
                f for f in evidence.figures
                if f.figure_type not in ("page_screenshot", "table_screenshot")
            ]
            fig_parts: list[str] = []

            # Pass 1: linked figures
            for fig in embedded_figs:
                if fig.figure_id in (bp_slide.linked_evidence_ids or []):
                    cap = fig.caption or ""
                    desc = fig.description or ""
                    if cap or desc:
                        fig_parts.append(
                            f"[{fig.figure_id}] (figure) "
                            f"Caption: {cap[:500]} "
                            f"{desc[:500]}"
                        )

            # Pass 2: keyword-matched figures (same as codegen)
            if not fig_parts and search_kw:
                for fig in embedded_figs:
                    text_pool = f"{fig.caption or ''} {fig.description or ''}".lower()
                    text_words = set(
                        re.sub(r'[^a-zA-Z\s]', '', text_pool).split()
                    )
                    if search_kw & text_words:
                        cap = fig.caption or ""
                        desc = fig.description or ""
                        if cap or desc:
                            fig_parts.append(
                                f"[{fig.figure_id}] (figure) "
                                f"Caption: {cap[:500]} "
                                f"{desc[:500]}"
                            )
                        if len(fig_parts) >= 3:
                            break

            parts.extend(fig_parts)

        # Pass 4: Full-paper search augmentation
        # When the slide contains specific terms (numbers, proper nouns) that
        # weren't found in the per-slide bundle/chunks, search the full paper
        # text directly. This closes the gap where codegen/repair used
        # search_source to find content beyond the per-slide evidence window,
        # but the judge couldn't see it and flagged valid claims as fabricated.
        _paper = paper_text
        if not _paper and source_store and hasattr(source_store, 'anchored_doc'):
            _paper = source_store.anchored_doc or ""
        if slide_text and _paper:
            _aug_terms: set[str] = set()
            # Numbers with decimals or 3+ digits
            for m in re.finditer(r'\b\d+\.\d+\b|\b\d{3,}\b', slide_text):
                _aug_terms.add(m.group())
            # Hyphenated proper nouns (e.g., Menzerath-Altmann, Zipf-like)
            for m in re.finditer(r'\b[A-Z][a-z]+(?:[- ][A-Z][a-z]+)+\b', slide_text):
                _aug_terms.add(m.group())
            # Single capitalized words ≥5 chars (distinctive proper nouns)
            for m in re.finditer(r'\b[A-Z][a-z]{4,}\b', slide_text):
                term = m.group()
                if term.lower() not in {
                    "figure", "table", "slide", "section", "results",
                    "method", "there", "these", "their", "about",
                    "under", "using", "based", "shown", "given",
                }:
                    _aug_terms.add(term)

            existing_text = "\n".join(parts).lower()
            _seen_pos: set[int] = set()
            _aug_excerpts: list[str] = []
            for term in sorted(_aug_terms)[:20]:
                if term.lower() in existing_text:
                    continue
                pos = _paper.lower().find(term.lower())
                if pos < 0:
                    continue
                if any(abs(pos - s) < 300 for s in _seen_pos):
                    continue
                _seen_pos.add(pos)
                start = max(0, pos - 200)
                end = min(len(_paper), pos + len(term) + 200)
                excerpt = _paper[start:end].replace("\n", " ").strip()
                _aug_excerpts.append(f"[paper_search] ...{excerpt}...")
                if len(_aug_excerpts) >= 8:
                    break
            if _aug_excerpts:
                parts.append(
                    "\n## Additional source context (full-paper search)\n"
                    + "\n".join(_aug_excerpts)
                )

        return "\n\n".join(parts)

    @staticmethod
    def _format_persistent_context(persistent_issues: list[Issue]) -> str:
        """Format persistent issues as context for fresh eval (Call 2).

        Tells the LLM which issues are already known and still open,
        so it should NOT re-report them. Only genuinely new issues
        should be returned.
        """
        if not persistent_issues:
            return ""

        open_issues = [
            iss for iss in persistent_issues
            if iss.status not in (IssueStatus.RESOLVED, IssueStatus.WONT_FIX, IssueStatus.DEFERRED)
        ]
        if not open_issues:
            return ""

        lines = [
            "\n\n## Known Persistent Issues (DO NOT re-report)",
            "The following issues are already tracked and still open. "
            "Do NOT report them again under any issue type or description. "
            "Only report genuinely NEW issues not covered below.\n",
        ]
        for iss in open_issues:
            desc = ""
            if iss.evidence and iss.evidence.description:
                desc = iss.evidence.description[:120]
            slides_str = ",".join(str(s) for s in (iss.affected_slides or []))
            lines.append(
                f"- [{iss.issue_id}] {iss.issue_type} on slide(s) {slides_str}: {desc}"
            )
        return "\n".join(lines)

    def _format_previous_issues(
        self,
        previous_issues: list[Issue],
        scope_slides: list[int] | None = None,
        repair_summaries: dict[int, dict] | None = None,
    ) -> str:
        """Format previous issues as context for differential evaluation.

        When provided, the judge must triage each previous issue
        (RESOLVED / PERSISTED / WORSENED) AND report genuinely new issues.

        Args:
            previous_issues: Issues from the prior turn on the slides being evaluated.
            scope_slides: If given, only include issues affecting these slides.
            repair_summaries: Per-slide repair summaries generated by the repair agent.
                If not provided, falls back to ``self._repair_summaries`` (set by
                eval_router before evaluation).

        Returns:
            Formatted markdown string to append to the user message.
        """
        if repair_summaries is None:
            repair_summaries = getattr(self, '_repair_summaries', None)
        if not previous_issues:
            return ""

        # Filter to scope slides if specified
        if scope_slides:
            scope_set = set(scope_slides)
            previous_issues = [
                iss for iss in previous_issues
                if any(s in scope_set for s in (iss.affected_slides or []))
            ]

        if not previous_issues:
            return ""

        lines = [
            "\n\n## Previous Issues — Triage Required",
            "",
            "⚠ **CRITICAL: Judge each issue based ONLY on the CURRENT screenshot.**",
            "Old descriptions are included only to identify WHICH problem to look for.",
            "Do NOT let old descriptions anchor your judgment — the slide may have changed significantly.",
            "",
            "You MUST triage EVERY issue below. For each one, determine:",
            "",
            "- **RESOLVED**: The SPECIFIC problem originally described NO LONGER EXISTS. "
            "Judge only whether the original issue type is gone. "
            "If the fix introduced a DIFFERENT problem (e.g., fixing 'too dense' made it 'too sparse'), "
            "the original issue is still RESOLVED — report the new problem as a new_issue.",
            "- **PERSISTED**: The same category of problem still exists, possibly in modified form. "
            "You MUST provide `updated_description` and `updated_planned_fix` reflecting "
            "the CURRENT state (not copy-pasting old text).",
            "- **WORSENED**: The SAME problem got worse IN ITS OWN DIRECTION "
            "(e.g., more overflow than before, worse contrast). "
            "A DIFFERENT problem appearing is NOT 'worsened'. "
            "You MUST provide `updated_description` and `updated_planned_fix`.",
            "",
            "### Issue Independence Principle",
            "Judge each issue INDEPENDENTLY on its own terms:",
            "- Fixing issue A may cause issue B. That means A = RESOLVED + B = new_issue.",
            "- Do NOT keep A open because B appeared. They are different problems.",
            "- The question per issue: 'Does THIS SPECIFIC problem still exist?' — not 'Is the slide perfect?'",
            "",
            f"There are {len(previous_issues)} previous issues. Your `previous_issue_verdicts` ",
            f"array MUST contain exactly {len(previous_issues)} entries.",
            "If unsure, provide a verdict with confidence='low'.",
            "",
            "Return triage in `previous_issue_verdicts`, then report genuinely NEW issues in `new_issues`.",
            "",
        ]

        for iss in previous_issues:
            slides_str = ", ".join(str(s) for s in iss.affected_slides)
            lines.append(
                f"### Issue `{iss.issue_id}` [{iss.issue_type}] "
                f"Slide(s) {slides_str} | rubric: {iss.rubric_id} | severity: {iss.severity.value}"
            )
            # Minimal context: only tell the LLM WHAT to look for, not
            # what the old state was.  Full old descriptions cause
            # anchoring bias where the LLM confirms PERSISTED without
            # actually inspecting the current screenshot.
            lines.append(
                f"Look for: Does a **{iss.issue_type}** problem exist on slide(s) {slides_str}?"
            )

            # Issue-type-specific triage hints (direction-aware)
            if iss.issue_type == "text_overflow":
                lines.append(
                    "**Hint**: Check if text touches or extends beyond its container bottom/right edge. "
                    "If all text is fully visible with ≥8px gap to container edge → RESOLVED."
                )
            elif iss.issue_type in ("text_density", "density_imbalance",
                                    "misallocated_detail"):
                sub_type = getattr(iss, 'sub_type', '') or ''
                direction = f" (direction: {sub_type})" if sub_type else ""
                lines.append(
                    f"**Hint**: This was a density/allocation issue{direction}. "
                    "Check if the SPECIFIC direction still applies. "
                    "If the slide was 'too dense' but is now 'too sparse', "
                    "the original issue is RESOLVED — report sparseness as a new_issue "
                    "(density_imbalance sub_type: sparse_content)."
                )
            elif iss.issue_type == "overlap":
                lines.append(
                    "**Hint**: Check if the originally overlapping elements are now "
                    "visually separated. If overlap is gone → RESOLVED, even if "
                    "spacing/density changed."
                )

            # Inject previous fix attempt (not self-report — just the planned_fix
            # that was GIVEN to the agent) so the triage judge can suggest something
            # different if the issue persisted. This does NOT bias the RESOLVED/PERSISTED
            # verdict — it only influences the updated_planned_fix.
            if iss.planned_fix:
                # Strip [PERSISTED]/[WORSENED] prefix from previous rounds
                prev_fix = iss.planned_fix
                for prefix in ("[PERSISTED] ", "[WORSENED] ", "[ATTEMPT ", ):
                    if prev_fix.startswith(prefix):
                        # Find end of bracket for [ATTEMPT N FAILED: ...]
                        bracket_end = prev_fix.find("] ", len(prefix) - 1)
                        if bracket_end > 0:
                            prev_fix = prev_fix[bracket_end + 2:]
                        else:
                            prev_fix = prev_fix[len(prefix):]
                lines.append(
                    f"**Previous fix attempted**: {prev_fix[:200]}\n"
                    "If PERSISTED, your `updated_planned_fix` MUST be a DIFFERENT strategy."
                )

            lines.append("")

        lines.extend([
            "### Output Format",
            "",
            "```json",
            "{",
            '  "previous_issue_verdicts": [',
            "    {",
            '      "issue_id": "...",',
            '      "verdict": "RESOLVED|PERSISTED|WORSENED",',
            '      "confidence": "high|medium|low",',
            '      "reasoning": "What you observe in the CURRENT screenshot",',
            '      "updated_description": "(REQUIRED for PERSISTED/WORSENED) Describe the problem as it exists NOW in the current slide",',
            '      "updated_planned_fix": "(REQUIRED for PERSISTED/WORSENED) Appropriate fix plan for the CURRENT state"',
            "    }",
            "  ],",
            '  "new_issues": [',
            "    { ...genuinely new problems only... }",
            "  ]",
            "}",
            "```",
        ])

        return "\n".join(lines)

    def _triage_previous_issues(
        self,
        previous_issues: list[Issue],
        scope_slides: list[int],
        user_content: str,
        model: str,
        turn_index: int,
        image_urls: list[str] | None = None,
    ) -> list[Issue]:
        """Verdict-only triage of previous issues (Call 1 of the two-call pattern).

        Sends previous issues + current slide state to the LLM, asking ONLY for
        ``previous_issue_verdicts``.  No new-issue detection happens here.

        RESOLVED issues are passed through without LLM triage — re-triaging
        them risks noisy resurrection (LLM says PERSISTED on a genuinely
        fixed issue). Regression detection is handled by fresh judge + dedup.

        Returns a list of the same Issue objects with statuses updated
        (RESOLVED / PERSISTED / WORSENED).
        """
        if not previous_issues:
            return []

        # Separate RESOLVED issues — don't send to LLM (they'd just add noise)
        resolved_passthrough = [
            iss for iss in previous_issues
            if iss.status == IssueStatus.RESOLVED
        ]
        open_issues = [
            iss for iss in previous_issues
            if iss.status != IssueStatus.RESOLVED
        ]
        if resolved_passthrough:
            logger.info(
                "%s triage: passing through %d RESOLVED issues without LLM re-triage",
                self.module_name, len(resolved_passthrough),
            )
        if not open_issues:
            return resolved_passthrough

        prev_ctx = self._format_previous_issues(open_issues, scope_slides)
        if not prev_ctx:
            return resolved_passthrough + list(open_issues)

        # Build explicit issue_id checklist so the LLM knows exactly which IDs to verdict
        scope_set = set(scope_slides) if scope_slides else None
        scoped_issues = [
            iss for iss in open_issues
            if not scope_set or any(s in scope_set for s in (iss.affected_slides or []))
        ]
        id_list = ", ".join(f'"{iss.issue_id}"' for iss in scoped_issues)

        triage_prompt = (
            user_content + prev_ctx
            + "\n\n## IMPORTANT — Verdict-Only Mode\n"
            "Return ONLY the `previous_issue_verdicts` array.  "
            "Do NOT report any new issues.\n\n"
            f"You MUST return a verdict for ALL {len(scoped_issues)} issues: [{id_list}]\n"
            "Any issue_id missing from your response will be treated as PERSISTED, "
            "which wastes repair budget. If unsure, return PERSISTED with confidence='low'.\n\n"
            "For PERSISTED or WORSENED verdicts, you MUST provide:\n"
            "- `updated_description`: Describe the problem as it exists NOW in the current state\n"
            "- `updated_planned_fix`: A FRESH, DIFFERENT fix strategy for the current state. "
            "Do NOT repeat the same fix that was already attempted — "
            "the previous fix attempt failed, so propose an alternative approach.\n"
            "  - For PERSISTED text_overflow: if the previous fix was CSS-based "
            "(font-size, padding, container resize), the new fix MUST be TEXT CONDENSATION "
            "(shorten text, merge bullets, remove least-important content).\n"
            "  - For PERSISTED missing_evidence/missing_entity on a dense slide: "
            "consider marking as 'RESOLVED' if the slide already has too much content, "
            "or suggest replacing existing low-value content instead of adding more.\n\n"
            "Your response must be a JSON object:\n"
            '```json\n{"previous_issue_verdicts": [\n'
            '  {"issue_id": "...", "verdict": "RESOLVED|PERSISTED|WORSENED", '
            '"reasoning": "brief reason", "confidence": "high|medium|low", '
            '"updated_description": "(for PERSISTED/WORSENED) current problem description", '
            '"updated_planned_fix": "(for PERSISTED/WORSENED) new fix strategy"},\n'
            '  ... (one entry per issue)\n]}\n```'
        )

        try:
            if image_urls:
                raw = self.llm.call_vision(
                    system_prompt=self.system_prompt,
                    text_content=triage_prompt,
                    image_urls=image_urls,
                    model=model,
                    module_name=f"{self.module_name}_triage",
                    prompt_version=f"{self.module_name}.triage.v1",
                    max_tokens=16384,
                    temperature=0.2,
                )
            else:
                raw = self.llm.call_text(
                    system_prompt=self.system_prompt,
                    user_content=triage_prompt,
                    model=model,
                    module_name=f"{self.module_name}_triage",
                    prompt_version=f"{self.module_name}.triage.v2",
                    max_tokens=16384,
                    temperature=0.2,
                )
        except Exception as e:
            logger.warning(
                "%s triage LLM call failed: %s — carrying all as PERSISTED",
                self.module_name, str(e)[:200],
            )
            return resolved_passthrough + list(open_issues)

        # Parse verdicts from response
        text = strip_code_fences(raw)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "%s triage response not valid JSON — carrying all as PERSISTED",
                self.module_name,
            )
            return resolved_passthrough + list(open_issues)

        verdicts = data.get("previous_issue_verdicts", [])
        if not verdicts:
            logger.warning(
                "%s triage returned no verdicts — carrying all as PERSISTED",
                self.module_name,
            )
            return resolved_passthrough + list(open_issues)

        verdict_map: dict[str, dict] = {}
        for v in verdicts:
            if isinstance(v, dict) and "issue_id" in v:
                verdict_map[v["issue_id"]] = v

        # Build set of issue IDs that were actually sent to the LLM
        scoped_ids = {iss.issue_id for iss in scoped_issues}

        result: list[Issue] = list(resolved_passthrough)
        for prev_iss in open_issues:
            if prev_iss.issue_id not in scoped_ids:
                # Not in this batch's scope — pass through unchanged
                result.append(prev_iss)
                continue
            vdata = verdict_map.get(prev_iss.issue_id)
            if vdata:
                verdict_str = vdata.get("verdict", "PERSISTED").upper()
                if verdict_str == "RESOLVED":
                    prev_iss.status = IssueStatus.RESOLVED
                    prev_iss.resolved_at_turn = turn_index
                    prev_iss.verdict = Verdict.PASS
                    logger.info(
                        "Triage: %s [%s] → RESOLVED at turn %d",
                        prev_iss.issue_id, prev_iss.issue_type, turn_index,
                    )
                elif verdict_str == "WORSENED":
                    # Update description and plan from current observation
                    if vdata.get("updated_description"):
                        prev_iss.why_this_fails = vdata["updated_description"]
                        if prev_iss.evidence:
                            prev_iss.evidence.description = vdata["updated_description"]
                    if vdata.get("updated_planned_fix"):
                        prev_iss.planned_fix = f"[WORSENED] {vdata['updated_planned_fix']}"
                    else:
                        prev_iss.planned_fix = (
                            f"[WORSENED] {vdata.get('reasoning', '')}"
                        )
                    logger.warning(
                        "Triage: %s [%s] → WORSENED at turn %d",
                        prev_iss.issue_id, prev_iss.issue_type, turn_index,
                    )
                else:
                    # PERSISTED (or PARTIALLY_MITIGATED → treated as PERSISTED)
                    label = "PERSISTED"
                    # Update description and plan from current observation
                    # so repair agent sees the CURRENT state, not stale T0 text
                    if vdata.get("updated_description"):
                        prev_iss.why_this_fails = vdata["updated_description"]
                        if prev_iss.evidence:
                            prev_iss.evidence.description = vdata["updated_description"]
                    if vdata.get("updated_planned_fix"):
                        prev_iss.planned_fix = f"[{label}] {vdata['updated_planned_fix']}"
                    else:
                        prev_iss.planned_fix = (
                            f"[{label}] {vdata.get('reasoning', '')}"
                        )
            else:
                logger.warning(
                    "Triage: %s not in verdicts — treating as PERSISTED",
                    prev_iss.issue_id,
                )
            result.append(prev_iss)

        resolved_count = sum(1 for r in result if r.status == IssueStatus.RESOLVED)
        logger.info(
            "%s triage: %d/%d open issues got verdicts, %d resolved, %d resolved passthrough",
            self.module_name,
            len(verdict_map), len(scoped_issues), resolved_count,
            len(resolved_passthrough),
        )
        coverage = len(verdict_map) / len(scoped_issues) if scoped_issues else 1.0
        if coverage < SpatialThresholds.TRIAGE_COVERAGE_WARN:
            logger.warning(
                "%s triage coverage %.0f%% — %d issues defaulted to PERSISTED. "
                "This may cause unnecessary repair work.",
                self.module_name, coverage * 100,
                len(scoped_issues) - len(verdict_map),
            )
        return result

    @staticmethod
    def _dedup_new_against_triaged(
        new_issues: list[Issue],
        triaged_issues: list[Issue],
    ) -> list[Issue]:
        """Remove new issues that duplicate triaged previous issues.

        IMPORTANT: Only dedup against OPEN/PERSISTED triaged issues.
        RESOLVED issues must NOT block new detections — if the judge
        marks an old issue RESOLVED but the fresh judge re-detects the
        same problem, the fresh detection should win (the problem is real).
        """
        open_previous = [
            issue for issue in triaged_issues
            if issue.status != IssueStatus.RESOLVED
        ]
        deduped = []
        for iss in new_issues:
            if any(issues_share_target(iss, previous) for previous in open_previous):
                logger.info(
                    "Dedup: new issue %s [%s] matches triaged issue — skipping",
                    iss.issue_id, iss.issue_type,
                )
                continue
            deduped.append(iss)
        return deduped

    def _parse_issues(
        self,
        raw_response: str,
        scope_slides: list[int],
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
    ) -> list[Issue]:
        """Parse LLM response into Issue objects.

        When previous_issues is provided, handles the dual-format response:
        - previous_issue_verdicts → update status of prior issues
        - new_issues → create new Issue objects

        Returns a combined list of triaged previous issues + new issues.
        """
        text = strip_code_fences(raw_response)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse judge response as JSON: %s", text[:300])
            # If previous issues were passed, carry them forward instead of
            # silently dropping everything.
            if previous_issues:
                logger.warning(
                    "Carrying %d previous issues forward due to JSON parse failure",
                    len(previous_issues),
                )
                return list(previous_issues)
            return []

        result_issues: list[Issue] = []

        # --- Handle previous issue verdicts ---
        if previous_issues and "previous_issue_verdicts" in data:
            verdicts = data.get("previous_issue_verdicts", [])
            verdict_map: dict[str, dict] = {}
            for v in verdicts:
                if isinstance(v, dict) and "issue_id" in v:
                    verdict_map[v["issue_id"]] = v

            prev_by_id = {iss.issue_id: iss for iss in previous_issues}
            for issue_id, prev_iss in prev_by_id.items():
                vdata = verdict_map.get(issue_id)
                if vdata:
                    verdict_str = vdata.get("verdict", "PERSISTED").upper()
                    if verdict_str == "RESOLVED":
                        prev_iss.status = IssueStatus.RESOLVED
                        prev_iss.resolved_at_turn = turn_index
                        prev_iss.verdict = Verdict.PASS
                        logger.info(
                            "Issue %s [%s] → RESOLVED at turn %d",
                            issue_id, prev_iss.issue_type, turn_index,
                        )
                    elif verdict_str == "WORSENED":
                        # Keep open but escalate severity if possible
                        prev_iss.planned_fix = (
                            f"[WORSENED] {vdata.get('reasoning', '')}"
                        )
                        logger.warning(
                            "Issue %s [%s] → WORSENED at turn %d",
                            issue_id, prev_iss.issue_type, turn_index,
                        )
                    else:
                        # PERSISTED or PARTIALLY_MITIGATED — keep as-is (open)
                        label = "PARTIALLY_MITIGATED" if "PARTIAL" in verdict_str else "PERSISTED"
                        prev_iss.planned_fix = (
                            f"[{label}] {vdata.get('reasoning', '')}"
                        )
                else:
                    # Judge didn't mention this issue — treat as persisted
                    logger.warning(
                        "Issue %s not in verdicts (judge skipped it), treating as PERSISTED",
                        issue_id,
                    )

                result_issues.append(prev_iss)

        elif previous_issues:
            # SAFETY NET: Judge LLM did NOT return previous_issue_verdicts.
            # This happens when the LLM ignores the differential format and
            # returns a flat "issues" list instead. Without this fallback,
            # all previous issues would be silently dropped, breaking the
            # issue lifecycle chain.
            #
            # Strategy: carry forward all previous issues as-is (PERSISTED).
            # This is conservative — some may have actually been fixed — but
            # losing track of issues is far worse than keeping stale ones.
            logger.warning(
                "%s judge did NOT return previous_issue_verdicts "
                "(had %d previous issues). Carrying all forward as PERSISTED.",
                self.rubric_family, len(previous_issues),
            )
            for prev_iss in previous_issues:
                if prev_iss.status == IssueStatus.OPEN:
                    prev_iss.planned_fix = (
                        f"[PERSISTED] (judge did not return verdicts at turn {turn_index})"
                    )
                result_issues.append(prev_iss)

        # --- Parse new issues ---
        # Support both "issues" (turn 0 format) and "new_issues" (differential format)
        issues_data = data.get("new_issues", data.get("issues", []))

        for i, item in enumerate(issues_data):
            raw_issue_type = item.get("issue_type", "unknown")
            normalized_type = self._normalize_issue_type(raw_issue_type, self.rubric_family)
            if normalized_type != raw_issue_type:
                logger.debug(
                    "Normalized issue_type: %r -> %r (family=%s)",
                    raw_issue_type, normalized_type, self.rubric_family,
                )

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
                rubric_id=item.get("rubric_id", ""),
                issue_type=normalized_type,
                sub_type=item.get("sub_type", ""),
                severity=Severity(item.get("severity", "minor")),
                confidence=Confidence(item.get("confidence", "medium")),
                affected_slides=item.get("affected_slides", scope_slides),
                evidence=issue_evidence,
                suspected_module=item.get("suspected_root_cause", "unknown"),
                verdict=Verdict.FAIL,
                why_this_fails=item.get("why_this_fails", ""),
                fixability=item.get("fixability", "unknown"),
                planned_fix=item.get("planned_fix", ""),
                fix_detail=self._parse_fix_detail(item.get("fix_detail")),
                recommended_action=RepairAction(item.get("recommended_action", "PATCH")),
                action_rationale=item.get("action_rationale", ""),
                source_probe_id=f"{self.module_name}_{item.get('rubric_id', self.rubric_family)}",
            )
            issue.issue_id = stable_issue_id(
                issue, item.get("rubric_id", self.rubric_family),
            )

            # Dedup: skip if this new issue matches a carried-forward previous
            # issue by (issue_type, affected_slides). This prevents the same
            # problem from appearing twice when the judge re-reports it under
            # a new ID instead of returning a verdict for the old one.
            if previous_issues and any(
                previous.status != IssueStatus.RESOLVED
                and issues_share_target(issue, previous)
                for previous in result_issues
            ):
                logger.info(
                    "Dedup: new issue %s [%s] on slides %s matches a "
                    "carried-forward previous issue — skipping duplicate",
                    issue.issue_id, issue.issue_type, issue.affected_slides,
                )
                continue

            # Severity calibration: wording deviations (fix = add_qualifier)
            # are minor, not major — the core claim is correct, just imprecise.
            if (
                issue.severity == Severity.MAJOR
                and issue.issue_type in ("unfaithful_compression", "incorrect_claim")
                and issue.fix_detail
                and getattr(issue.fix_detail, "action_type", None) == "add_qualifier"
            ):
                issue.severity = Severity.MINOR
                logger.info(
                    "Severity calibration: %s [%s] downgraded to minor "
                    "(fix is add_qualifier, not factual replacement)",
                    issue.issue_id, issue.issue_type,
                )

            result_issues.append(issue)

        return result_issues

    @staticmethod
    def _parse_fix_detail(raw: Any) -> FixDetail:
        """Parse fix_detail from judge response, if present."""
        if not raw or not isinstance(raw, dict):
            return FixDetail()
        return FixDetail(
            correct_content=raw.get("correct_content", ""),
            source_ref=raw.get("source_ref", ""),
            target_location=raw.get("target_location", ""),
            action_type=raw.get("action_type", ""),
        )

    @staticmethod
    def _normalize_issue_type(raw_type: str, rubric_family: str) -> str:
        """Normalize a free-form issue_type string to a predefined value.

        Steps:
        1. Convert to snake_case lowercase.
        2. If it exactly matches a valid type for the rubric family, return it.
        3. Otherwise, use fuzzy matching (difflib) to find the closest valid type.
        4. If no match with cutoff >= 0.4, return "other".
        """
        # Normalize to snake_case
        normalized = re.sub(r'[^a-z0-9_]', '_', raw_type.lower().strip())
        normalized = re.sub(r'_+', '_', normalized).strip('_')

        if not normalized:
            return "other"

        # Find the valid set for this rubric family
        valid = VALID_ISSUE_TYPES.get(rubric_family, set())
        if not valid:
            valid = _ALL_VALID_ISSUE_TYPES

        # Exact match
        if normalized in valid:
            return normalized

        # Fuzzy match
        matches = get_close_matches(normalized, sorted(valid), n=1, cutoff=SpatialThresholds.FUZZY_MATCH_CUTOFF)
        if matches:
            return matches[0]

        return "other"
