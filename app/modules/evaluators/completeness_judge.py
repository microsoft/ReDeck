"""CompletenessJudge - evaluates C-series rubric items."""

import json
import logging
import re

from ...schemas.extraction import SlideExtraction
from ...schemas.blueprint import DeckBlueprint
from ...schemas.evidence import EvidenceState
from ...schemas.issue import Issue
from .base_judge import BaseJudge

logger = logging.getLogger(__name__)


def _extract_text_from_html(html: str, max_chars: int = 1500) -> str:
    """Extract visible text from HTML slide code.

    Used as a fallback when SlideExtraction.text_content is empty
    (HTML→PNG mode where PPTX only contains an embedded image).
    """
    # Remove style/script blocks
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


class CompletenessJudge(BaseJudge):
    """Evaluates content completeness: C1-C5.

    Supports two modes:
    - Single-pass: direct LLM call (default, fast)
    - Agent mode: wrapped by EvaluatorAgent with search_source tool
      (slower but higher precision, see evaluator_agent.py)

    The mode is selected by EvalRouter based on config.
    """

    rubric_family = "C"
    module_name = "completeness_judge"
    prompt_filename = "completeness_judge.system.md"

    def evaluate(
        self,
        extractions: list[SlideExtraction],
        task_brief: str,
        source_summary: str,
        blueprint: DeckBlueprint | None = None,
        evidence: EvidenceState | None = None,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
    ) -> list[Issue]:
        """Evaluate content completeness against brief and source."""
        # Build deck content summary with per-slide evidence
        content_summary = []
        for ext in extractions:
            texts = [obj.text_content for obj in ext.objects if obj.text_content.strip()]

            # HTML fallback: in HTML→PNG mode, text_content is empty because
            # the PPTX only contains an embedded PNG image.  Fall back to
            # extracting visible text from the slide HTML source code.
            if not texts:
                slide_codes = getattr(self, '_slide_codes', None) or {}
                html = slide_codes.get(ext.slide_id, '')
                if html:
                    texts = [_extract_text_from_html(html)]

            entry = {
                "slide_id": ext.slide_id,
                "title": ext.title,
                "content": "\n".join(texts)[:1500],
            }
            # Inject per-slide evidence (same chunks codegen used)
            slide_text_combined = "\n".join(texts)
            slide_ev = self._build_slide_evidence(
                ext.slide_id, blueprint, evidence,
                source_store=getattr(self, '_source_store', None),
                slide_text=slide_text_combined,
            )
            if slide_ev:
                entry["source_evidence"] = slide_ev

            content_summary.append(entry)

        user_content = json.dumps({
            "deck_content": content_summary,
            "task_brief": task_brief,
            "source_summary": source_summary,  # full source, no truncation
            "total_slides": len(extractions),
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
            max_tokens=4096,
        )

        new_issues = self._parse_issues(raw, all_slides, previous_issues=None, turn_index=turn_index)

        if triaged_issues:
            new_issues = self._dedup_new_against_triaged(new_issues, triaged_issues)

        return triaged_issues + new_issues
