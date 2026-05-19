"""NarrativeJudge - evaluates A-series rubric items (Presentation Fundamentals)."""

import json
import logging

from ...schemas.extraction import SlideExtraction
from ...schemas.issue import Issue
from .base_judge import BaseJudge

logger = logging.getLogger(__name__)


class NarrativeJudge(BaseJudge):
    """Evaluates narrative quality: A1-A6."""

    rubric_family = "A"
    module_name = "narrative_judge"
    prompt_filename = "narrative_judge.system.md"

    def evaluate(
        self,
        extractions: list[SlideExtraction],
        task_brief: str,
        previous_issues: list[Issue] | None = None,
        turn_index: int = 0,
    ) -> list[Issue]:
        """Evaluate narrative quality across the deck."""
        # Build deck outline for the judge
        outline = self._build_outline(extractions)

        user_content = json.dumps({
            "deck_outline": outline,
            "task_brief": task_brief,
            "total_slides": len(extractions),
        }, indent=2, ensure_ascii=False)

        model = self.config.models.get_model(self.module_name)
        all_slides = [ext.slide_id for ext in extractions]

        # STEP 1: Triage previous issues (dedicated verdict-only call)
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
            prompt_version="narrative_judge.system.v1",
            max_tokens=4096,
        )

        new_issues = self._parse_issues(raw, all_slides, previous_issues=None, turn_index=turn_index)

        # STEP 3: Dedup new issues against triaged previous issues
        if triaged_issues:
            new_issues = self._dedup_new_against_triaged(new_issues, triaged_issues)

        return triaged_issues + new_issues

    def _build_outline(self, extractions: list[SlideExtraction]) -> list[dict]:
        """Build a text-only deck outline for narrative evaluation."""
        outline = []
        for ext in extractions:
            texts = []
            for obj in ext.objects:
                if obj.text_content.strip():
                    texts.append(obj.text_content.strip())
            outline.append({
                "slide_id": ext.slide_id,
                "title": ext.title,
                "text_content": "\n".join(texts)[:1000],
                "object_count": ext.total_objects,
            })
        return outline
