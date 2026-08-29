"""Tests for IssueNormalizer module."""

import pytest

from app.modules.issue_normalizer import IssueNormalizer
from app.schemas.common import Confidence, IssueStatus, Severity
from app.schemas.issue import FixDetail, Issue, IssueEvidence


def _make_issue(
    issue_id: str,
    rubric_id: str = "B3",
    issue_type: str = "overlap",
    severity: Severity = Severity.MAJOR,
    confidence: Confidence = Confidence.HIGH,
    affected_slides: list[int] | None = None,
    description: str = "",
    object_refs: list[str] | None = None,
    planned_fix: str = "",
    fix_detail: FixDetail | None = None,
) -> Issue:
    return Issue(
        issue_id=issue_id,
        rubric_id=rubric_id,
        issue_type=issue_type,
        severity=severity,
        confidence=confidence,
        affected_slides=affected_slides or [1],
        evidence=IssueEvidence(
            description=description or f"Issue {issue_id}",
            object_refs=object_refs or [],
        ),
        planned_fix=planned_fix,
        fix_detail=fix_detail or FixDetail(),
    )


class TestIssueNormalizer:
    """Test issue dedup and ordering (merge removed in cleanup)."""

    def test_deduplication_by_id(self):
        normalizer = IssueNormalizer()
        issues = [
            _make_issue("issue_a", rubric_id="B3", issue_type="overlap",
                        affected_slides=[1]),
            _make_issue("issue_a", rubric_id="B3", issue_type="overlap",
                        affected_slides=[1]),  # exact duplicate
            _make_issue("issue_b", rubric_id="A1", issue_type="weak_narrative",
                        affected_slides=[2]),  # different rubric/type/slide
        ]
        result = normalizer.normalize(issues)
        ids = [i.issue_id for i in result]
        assert ids.count("issue_a") == 1
        assert "issue_b" in ids

    def test_severity_ordering(self):
        """Critical issues should appear before major, before minor."""
        normalizer = IssueNormalizer()
        issues = [
            _make_issue("minor_1", severity=Severity.MINOR, rubric_id="A1",
                        issue_type="weak"),
            _make_issue("critical_1", severity=Severity.CRITICAL, rubric_id="A2",
                        issue_type="missing"),
            _make_issue("major_1", severity=Severity.MAJOR, rubric_id="A3",
                        issue_type="poor"),
        ]
        result = normalizer.normalize(issues)
        severities = [i.severity for i in result]
        assert severities[0] == Severity.CRITICAL
        assert severities[-1] == Severity.MINOR

    def test_empty_issue_list(self):
        normalizer = IssueNormalizer()
        result = normalizer.normalize([])
        assert result == []

    def test_preserves_unique_issues(self):
        normalizer = IssueNormalizer()
        issues = [
            _make_issue("a", rubric_id="A1", issue_type="x", affected_slides=[1]),
            _make_issue("b", rubric_id="B3", issue_type="y", affected_slides=[2]),
            _make_issue("c", rubric_id="C1", issue_type="z", affected_slides=[3]),
        ]
        result = normalizer.normalize(issues)
        assert len(result) == 3

    def test_keeps_distinct_same_type_targets_on_same_slide(self):
        normalizer = IssueNormalizer()
        issues = [
            _make_issue("overlap_1", rubric_id="B3", issue_type="overlap",
                        affected_slides=[2], object_refs=["obj_a", "obj_b"],
                        description="Overlap between A and B"),
            _make_issue("overlap_2", rubric_id="B3", issue_type="overlap",
                        affected_slides=[2], object_refs=["obj_c", "obj_d"],
                        description="Overlap between C and D"),
        ]
        result = normalizer.normalize(issues)
        assert {issue.issue_id for issue in result} == {
            "overlap_1",
            "overlap_2",
        }

    def test_merges_duplicate_reports_for_same_target(self):
        normalizer = IssueNormalizer()
        issues = [
            _make_issue(
                "overlap_llm",
                rubric_id="B3",
                issue_type="overlap",
                affected_slides=[2],
                object_refs=["chart", "caption"],
                confidence=Confidence.MEDIUM,
            ),
            _make_issue(
                "overlap_geom",
                rubric_id="B3",
                issue_type="overlap",
                affected_slides=[2],
                object_refs=["caption", "chart"],
                confidence=Confidence.HIGH,
            ),
        ]

        result = normalizer.normalize(issues)

        assert [issue.issue_id for issue in result] == ["overlap_geom"]

    def test_keeps_distinct_low_contrast_regions_on_same_slide(self):
        normalizer = IssueNormalizer()
        issues = [
            _make_issue(
                "caption_contrast",
                rubric_id="B05",
                issue_type="low_contrast",
                affected_slides=[9],
                description="Figure 4 caption GPT-4o and GPT-5 coral text",
            ),
            _make_issue(
                "title_contrast",
                rubric_id="B05",
                issue_type="low_contrast",
                affected_slides=[9],
                description="Top teal header title phrase GPT refiners orange text",
            ),
        ]

        result = normalizer.normalize(issues)

        assert {issue.issue_id for issue in result} == {
            "caption_contrast",
            "title_contrast",
        }

    def test_high_confidence_stays_open(self):
        """High-confidence issues should remain OPEN."""
        normalizer = IssueNormalizer()
        issues = [
            _make_issue("high_conf", confidence=Confidence.HIGH, rubric_id="B3",
                        issue_type="overlap"),
        ]
        result = normalizer.normalize(issues)
        assert result[0].status == IssueStatus.OPEN

    def test_filters_gpt_4o_gpt_40_entity_alias_noise(self):
        normalizer = IssueNormalizer()
        issue = _make_issue(
            "D3_slide5_gpt_alias",
            rubric_id="D3",
            issue_type="entity_error",
            affected_slides=[5],
            description=(
                'Deck claim says "GPT-4o" but source evidence says '
                '"GPT-40" for the same model name.'
            ),
            planned_fix='Replace the model name "GPT-4o" with "GPT-40".',
            fix_detail=FixDetail(
                correct_content=(
                    "For each node, we employ GPT-40 to describe its "
                    "relevant characteristics of the EEG signal."
                ),
            ),
        )

        assert normalizer.normalize([issue]) == []

    def test_keeps_non_alias_entity_error(self):
        normalizer = IssueNormalizer()
        issue = _make_issue(
            "D3_slide2_wrong_dataset",
            rubric_id="D3",
            issue_type="entity_error",
            affected_slides=[2],
            description='Deck says "Dataset A" but source says "Dataset B".',
            planned_fix='Replace "Dataset A" with "Dataset B".',
        )

        result = normalizer.normalize([issue])

        assert [item.issue_id for item in result] == ["D3_slide2_wrong_dataset"]
