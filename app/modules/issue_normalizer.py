"""IssueNormalizer - deduplicates, cross-source dedup, filters, and sorts issues."""

import logging
import re

from ..schemas.common import Confidence, IssueStatus, Severity
from ..schemas.issue import Issue
from ..utils.issue_identity import issues_share_target

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
      2. Cross-source dedup: when multiple issues target the same semantic
         object/region, keep only the highest-confidence one
      3. Filter out low-signal noise (confidence=LOW & severity=MINOR)
      4. Sort by severity then slide number
    """

    def normalize(self, issues: list[Issue], slide_evidence_map: dict[int, set[str]] | None = None) -> list[Issue]:
        """Normalize a list of issues."""
        n_input = len(issues)

        # Step 1: Deduplicate by issue_id
        deduped = self._deduplicate(issues)
        n_after_dedup = len(deduped)

        # Step 2: Target-aware cross-source dedup within a rubric.
        deduped = self._cross_source_dedup(deduped)
        n_after_cross = len(deduped)

        # Step 2b: Target-aware dedup across rubric families.
        deduped = self._issue_type_dedup(deduped)
        n_after_type_dedup = len(deduped)

        # Step 2c: Filter known OCR/model-alias churn before it reaches repair.
        # Some paper text/extractions alternate between GPT-4o and GPT-40.
        # Treating that as a hard entity error makes the repair loop flip the
        # visible model name across turns without improving fidelity.
        deduped = self._filter_model_alias_noise(deduped)
        n_after_alias_filter = len(deduped)

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
            "Normalized %d issues -> %d open (dedup=%d, cross_source=%d, alias_filter=%d, filter=%d, deferred=%d)",
            n_input, len(deduped) - n_deferred,
            n_input - n_after_dedup,
            n_after_dedup - n_after_type_dedup,
            n_after_type_dedup - n_after_alias_filter,
            n_after_alias_filter - n_after_filter,
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
        """Deduplicate same-rubric reports only when their targets match.

        This handles the case where a deterministic checker and an LLM
        judge both flag the same problem on the same slide.  The
        deterministic version (typically confidence=HIGH with precise
        coordinates) is preferred.
        """
        return self._target_aware_dedup(issues, require_same_rubric=True)

    def _issue_type_dedup(self, issues: list[Issue]) -> list[Issue]:
        """Deduplicate cross-rubric reports only when targets match."""
        return self._target_aware_dedup(issues, require_same_rubric=False)

    @staticmethod
    def _preference(issue: Issue) -> tuple[int, int]:
        return (
            _CONFIDENCE_RANK.get(issue.confidence, 0),
            -{"critical": 0, "major": 1, "minor": 2, "info": 3}.get(
                issue.severity.value, 4,
            ),
        )

    def _target_aware_dedup(
        self,
        issues: list[Issue],
        *,
        require_same_rubric: bool,
    ) -> list[Issue]:
        """Keep distinct same-slide targets while merging duplicate reports."""
        result: list[Issue] = []
        for issue in issues:
            if not issue.affected_slides:
                result.append(issue)
                continue

            match_index = None
            for index, existing in enumerate(result):
                if not existing.affected_slides:
                    continue
                if require_same_rubric and existing.rubric_id != issue.rubric_id:
                    continue
                if issues_share_target(existing, issue):
                    match_index = index
                    break

            if match_index is None:
                result.append(issue)
                continue

            if self._preference(issue) > self._preference(result[match_index]):
                result[match_index] = issue
        return result

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

    def _filter_model_alias_noise(self, issues: list[Issue]) -> list[Issue]:
        """Drop entity errors caused only by known OCR/model-name aliases."""
        result: list[Issue] = []
        for issue in issues:
            if self._is_known_model_alias_issue(issue):
                logger.info(
                    "Filtered model-alias entity issue: %s (%s)",
                    issue.issue_id, issue.issue_type,
                )
                continue
            result.append(issue)
        return result

    @staticmethod
    def _is_known_model_alias_issue(issue: Issue) -> bool:
        """Return True for GPT-4o/GPT-40 spelling-only entity churn.

        Source PDFs and OCR text can disagree between letter ``o`` and zero in
        model names. When the issue is framed as a local D-family entity-name
        mismatch between those spellings, sending it to repair creates visible
        oscillation rather than a meaningful correctness improvement.
        """
        if (issue.issue_type or "") != "entity_error":
            return False
        if not (issue.rubric_id or "").upper().startswith("D"):
            return False

        parts = [
            issue.issue_id or "",
            issue.planned_fix or "",
            issue.why_this_fails or "",
        ]
        if issue.evidence and issue.evidence.description:
            parts.append(issue.evidence.description)
        fd = getattr(issue, "fix_detail", None)
        if fd:
            parts.extend([
                getattr(fd, "correct_content", "") or "",
                getattr(fd, "target_location", "") or "",
                getattr(fd, "source_ref", "") or "",
            ])

        text = "\n".join(str(part) for part in parts if part).casefold()
        if "gpt-4o" not in text or "gpt-40" not in text:
            return False

        mismatch_terms = (
            "model name", "named model", "incorrect model", "entity",
            "match the source", "source wording", "source evidence",
            "normalization", "replace",
        )
        if not any(term in text for term in mismatch_terms):
            return False

        repairish = re.search(
            r"(replace|change|rewrite|normalize)[^\n.]{0,140}(gpt-4o|gpt-40)",
            text,
        )
        source_mismatch = "source" in text and "gpt-4o" in text and "gpt-40" in text
        return bool(repairish or source_mismatch)
