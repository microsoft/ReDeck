"""CorrectnessJudge - evaluates D-series rubric items."""

import json
import logging

from ...schemas.extraction import SlideExtraction
from ...schemas.blueprint import DeckBlueprint
from ...schemas.evidence import EvidenceState
from ...schemas.issue import Issue
from .base_judge import BaseJudge

logger = logging.getLogger(__name__)


class CorrectnessJudge(BaseJudge):
    """Evaluates content correctness: D1-D5.

    Supports two modes:
    - Single-pass: direct LLM call (default, fast)
    - Agent mode: wrapped by EvaluatorAgent with search_source tool
      (slower but higher precision, see evaluator_agent.py)

    The mode is selected by EvalRouter based on config.
    """

    rubric_family = "D"
    module_name = "correctness_judge"
    prompt_filename = "correctness_judge.system.md"

    def evaluate(
        self,
        extractions: list[SlideExtraction],
        source_summary: str,
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
    ) -> list[Issue]:
        """Evaluate content correctness against source materials (single-pass)."""
        # Build claim inventory with per-slide evidence
        claims = []
        for ext in extractions:
            slide_claims = []
            for obj in ext.objects:
                if obj.text_content.strip():
                    slide_claims.append(obj.text_content.strip())

            entry = {
                "slide_id": ext.slide_id,
                "title": ext.title,
                "claims": slide_claims,
            }
            # Inject per-slide evidence (same chunks codegen used)
            slide_text_combined = " ".join(slide_claims)
            slide_ev = self._build_slide_evidence(
                ext.slide_id, blueprint, evidence,
                source_store=getattr(self, '_source_store', None),
                slide_text=slide_text_combined,
            )
            if slide_ev:
                entry["source_evidence"] = slide_ev

            claims.append(entry)

        user_content = json.dumps({
            "deck_claims": claims,
            "source_materials": source_summary  # full source, no truncation,
        }, indent=2, ensure_ascii=False)

        # Triage previous issues in a dedicated verdict-only call
        model = self.config.models.get_model(self.module_name)
        all_slides = [ext.slide_id for ext in extractions]

        triaged_issues: list[Issue] = []
        if previous_issues:
            triaged_issues = self._triage_previous_issues(
                previous_issues, all_slides, user_content, model, turn_index,
            )

        # STEP 2: Fresh judge — with persistent issue awareness
        step2_content = user_content
        if triaged_issues:
            persistent_ctx = self._format_persistent_context(triaged_issues)
            if persistent_ctx:
                step2_content = user_content + persistent_ctx

        raw = self.llm.call_text(
            system_prompt=self.system_prompt,
            user_content=step2_content,
            model=model,
            module_name=self.module_name,
            prompt_version="correctness_judge.system.v1",
            max_tokens=4096,
        )

        new_issues = self._parse_issues(raw, all_slides, previous_issues=None, turn_index=turn_index)

        if triaged_issues:
            new_issues = self._dedup_new_against_triaged(new_issues, triaged_issues)

        return triaged_issues + new_issues
