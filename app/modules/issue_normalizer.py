"""IssueNormalizer - deduplicates, cross-source dedup, filters, and sorts issues."""

import logging
import re
from collections import defaultdict

from ..schemas.common import Confidence, IssueStatus, Severity
from ..schemas.issue import Issue

logger = logging.getLogger(__name__)

# Confidence ranking: higher value = more trustworthy
_CONFIDENCE_RANK = {
    Confidence.HIGH: 2,
    Confidence.MEDIUM: 1,
    Confidence.LOW: 0,
}


class IssueNormalizer:
    """Deduplicates, filters, and sorts issues from all evaluators.

    Pipeline:
      1. Deduplicate by issue_id (exact match)
      2. Cross-source dedup: when multiple issues target the same
         (slide, rubric_id) pair, keep only the highest-confidence one
      3. Filter out low-signal noise (confidence=LOW & severity=MINOR)
      4. Sort by severity then slide number
    """

    def normalize(self, issues: list[Issue], slide_evidence_map: dict[int, set[str]] | None = None) -> list[Issue]:
        """Normalize a list of issues."""
        n_input = len(issues)

        # Step 1: Deduplicate by issue_id
        deduped = self._deduplicate(issues)
        n_after_dedup = len(deduped)

        # Step 2: Cross-source dedup by (slide, rubric_id)
        deduped = self._cross_source_dedup(deduped)
        n_after_cross = len(deduped)

        # Step 2b: Cross-source dedup by (slide, issue_type) — catches same
        # issue_type from different rubric families (e.g. geom A5 + LLM A5)
        deduped = self._issue_type_dedup(deduped)
        n_after_cross = len(deduped)

        # Step 3: Filter low-signal noise
        deduped = self._filter_low_signal(deduped)
        n_after_filter = len(deduped)

        # Step 4: Sort by severity then slide
        deduped.sort(key=lambda i: (
            {"critical": 0, "major": 1, "minor": 2, "info": 3}.get(i.severity.value, 4),
            min(i.affected_slides) if i.affected_slides else 999,
        ))

        # Step 5: Defer D/E issues whose evidence refs are outside the
        # affected slides' linked chunks — repair cannot act on them.
        n_after_sort = len(deduped)
        n_deferred = 0

        logger.info(
            "Normalized %d issues -> %d open (dedup=%d, cross_source=%d, filter=%d, deferred=%d)",
            n_input, len(deduped) - n_deferred,
            n_input - n_after_dedup,
            n_after_dedup - n_after_cross,
            n_after_cross - n_after_filter,
            n_deferred,
        )
        return deduped

    def _deduplicate(self, issues: list[Issue]) -> list[Issue]:
        """Remove duplicate issues by issue_id."""
        seen: set[str] = set()
        result: list[Issue] = []
        for issue in issues:
            if issue.issue_id not in seen:
                seen.add(issue.issue_id)
                result.append(issue)
        return result

    def _cross_source_dedup(self, issues: list[Issue]) -> list[Issue]:
        """When multiple issues target the same (slide, rubric_id), keep
        the one with the highest confidence.

        This handles the case where a deterministic checker and an LLM
        judge both flag the same problem on the same slide.  The
        deterministic version (typically confidence=HIGH with precise
        coordinates) is preferred.

        Issues without affected_slides are never merged.
        """
        # Group by (slide, rubric_id).  An issue with multiple
        # affected_slides is indexed under each slide independently.
        groups: dict[tuple[int, str], list[Issue]] = defaultdict(list)
        no_slide_issues: list[Issue] = []

        for issue in issues:
            if not issue.affected_slides:
                no_slide_issues.append(issue)
                continue
            for slide in issue.affected_slides:
                groups[(slide, issue.rubric_id)].append(issue)

        # For each group keep the highest-confidence issue
        kept_ids: set[str] = set()
        for key, group in groups.items():
            best = max(
                group,
                key=lambda i: (
                    _CONFIDENCE_RANK.get(i.confidence, 0),
                    # tie-break: prefer more severe
                    -{"critical": 0, "major": 1, "minor": 2, "info": 3}.get(
                        i.severity.value, 4
                    ),
                ),
            )
            kept_ids.add(best.issue_id)

        # Also keep all no-slide issues
        for issue in no_slide_issues:
            kept_ids.add(issue.issue_id)

        # Preserve original order
        return [i for i in issues if i.issue_id in kept_ids]

    def _issue_type_dedup(self, issues: list[Issue]) -> list[Issue]:
        """Deduplicate by (slide, issue_type) — merges issues with the same
        type on the same slide even if they come from different rubric families.
        Keeps the highest-confidence one.
        """
        groups: dict[tuple[int, str], list[Issue]] = defaultdict(list)
        no_slide_issues: list[Issue] = []

        for issue in issues:
            if not issue.affected_slides:
                no_slide_issues.append(issue)
                continue
            for slide in issue.affected_slides:
                groups[(slide, issue.issue_type)].append(issue)

        kept_ids: set[str] = set()
        for key, group in groups.items():
            best = max(
                group,
                key=lambda i: (
                    _CONFIDENCE_RANK.get(i.confidence, 0),
                    -{"critical": 0, "major": 1, "minor": 2, "info": 3}.get(
                        i.severity.value, 4
                    ),
                ),
            )
            kept_ids.add(best.issue_id)

        for issue in no_slide_issues:
            kept_ids.add(issue.issue_id)

        return [i for i in issues if i.issue_id in kept_ids]

    def _filter_low_signal(self, issues: list[Issue]) -> list[Issue]:
        """Drop issues that are both low-confidence and low-severity.

        These are issues the judge itself is uncertain about and that
        have minimal impact.  Sending them to repair only adds churn.
        """
        result: list[Issue] = []
        for issue in issues:
            if (issue.confidence == Confidence.LOW
                    and issue.severity == Severity.MINOR):
                logger.debug(
                    "Filtered low-signal issue: %s (slide %s)",
                    issue.issue_id, issue.affected_slides,
                )
                continue
            result.append(issue)
        return result
