"""Tests for diff_utils module."""

import pytest

from app.utils.diff_utils import diff_issue_lists, count_by_severity


class TestDiffIssueLists:
    """Test diff computation between old and new issue lists."""

    def test_new_issues(self):
        old = []
        new = [
            {"issue_id": "a", "severity": "major"},
            {"issue_id": "b", "severity": "minor"},
        ]
        diff = diff_issue_lists(old, new)
        assert len(diff["new"]) == 2
        assert len(diff["resolved"]) == 0
        assert len(diff["persisting"]) == 0

    def test_resolved_issues(self):
        old = [
            {"issue_id": "a", "severity": "major"},
            {"issue_id": "b", "severity": "minor"},
        ]
        new = []
        diff = diff_issue_lists(old, new)
        assert len(diff["resolved"]) == 2
        assert len(diff["new"]) == 0
        assert len(diff["persisting"]) == 0

    def test_persisting_issues(self):
        old = [
            {"issue_id": "a", "severity": "major"},
            {"issue_id": "b", "severity": "minor"},
        ]
        new = [
            {"issue_id": "a", "severity": "major"},
            {"issue_id": "b", "severity": "minor"},
        ]
        diff = diff_issue_lists(old, new)
        assert len(diff["persisting"]) == 2
        assert len(diff["new"]) == 0
        assert len(diff["resolved"]) == 0

    def test_mixed_diff(self):
        old = [
            {"issue_id": "a", "severity": "major"},
            {"issue_id": "b", "severity": "minor"},
            {"issue_id": "c", "severity": "critical"},
        ]
        new = [
            {"issue_id": "b", "severity": "minor"},    # persisting
            {"issue_id": "d", "severity": "major"},     # new
        ]
        diff = diff_issue_lists(old, new)
        assert len(diff["resolved"]) == 2  # a and c
        assert len(diff["persisting"]) == 1  # b
        assert len(diff["new"]) == 1  # d

        resolved_ids = {i["issue_id"] for i in diff["resolved"]}
        assert resolved_ids == {"a", "c"}
        assert diff["new"][0]["issue_id"] == "d"
        assert diff["persisting"][0]["issue_id"] == "b"

    def test_both_empty(self):
        diff = diff_issue_lists([], [])
        assert diff["resolved"] == []
        assert diff["persisting"] == []
        assert diff["new"] == []


class TestCountBySeverity:
    """Test severity counting utility."""

    def test_counts(self):
        issues = [
            {"issue_id": "a", "severity": "critical"},
            {"issue_id": "b", "severity": "major"},
            {"issue_id": "c", "severity": "major"},
            {"issue_id": "d", "severity": "minor"},
        ]
        counts = count_by_severity(issues)
        assert counts["critical"] == 1
        assert counts["major"] == 2
        assert counts["minor"] == 1

    def test_empty_list(self):
        counts = count_by_severity([])
        assert counts["critical"] == 0
        assert counts["major"] == 0
        assert counts["minor"] == 0

    def test_missing_severity_defaults_to_minor(self):
        issues = [{"issue_id": "x"}]
        counts = count_by_severity(issues)
        assert counts["minor"] == 1
