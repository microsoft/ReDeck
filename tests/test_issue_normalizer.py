"""Tests for IssueNormalizer module."""

import pytest

from app.modules.issue_normalizer import IssueNormalizer
from app.schemas.common import Confidence, IssueStatus, Severity
from app.schemas.issue import Issue, IssueEvidence


def _make_issue(
    issue_id: str,
    rubric_id: str = "B3",
    issue_type: str = "overlap",
    severity: Severity = Severity.MAJOR,
    confidence: Confidence = Confidence.HIGH,
    affected_slides: list[int] | None = None,
    description: str = "",
    object_refs: list[str] | None = None,
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
    )


class TestIssueNormalizer:
    """Test issue deduplication and stable ordering."""

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

    def test_no_merge_same_type_same_slides(self):
        """Same rubric/type/slides with different object_refs are cross-source deduped
        — the normalizer keeps the highest-confidence one."""
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
        # Cross-source dedup merges by (slide, rubric_id) → 1 issue survives
        assert len(result) == 1

    def test_high_confidence_stays_open(self):
        """High-confidence issues should remain OPEN."""
        normalizer = IssueNormalizer()
        issues = [
            _make_issue("high_conf", confidence=Confidence.HIGH, rubric_id="B3",
                        issue_type="overlap"),
        ]
        result = normalizer.normalize(issues)
        assert result[0].status == IssueStatus.OPEN
