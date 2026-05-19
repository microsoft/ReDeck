"""Tests for TurnSettler module."""

import pytest

from app.orchestrator.turn_settler import TurnSettler
from app.schemas.common import IssueStatus, Severity, Verdict
from app.schemas.issue import Issue, IssueEvidence
from app.schemas.repair_unit import RepairUnit
from app.schemas.turn_summary import TurnSummary
from app.schemas.verify_report import VerifyItem, VerifyReport


def _make_issue(
    issue_id: str,
    severity: Severity = Severity.MAJOR,
    status: IssueStatus = IssueStatus.OPEN,
) -> Issue:
    return Issue(
        issue_id=issue_id,
        rubric_id="B3",
        issue_type="test",
        severity=severity,
        status=status,
        affected_slides=[1],
        evidence=IssueEvidence(description="test"),
    )


class TestTurnSettler:
    """Test turn summarization and continue/stop decisions."""

    def test_settle_returns_turn_summary(self):
        settler = TurnSettler()
        summary = settler.settle(
            turn_index=0,
            issues=[],
            previous_issues=[],
            repair_units=[],
            verify_report=None,
            artifact_paths={},
        )
        assert isinstance(summary, TurnSummary)
        assert summary.turn_index == 0

    def test_should_continue_false_when_no_issues(self):
        settler = TurnSettler()
        summary = settler.settle(
            turn_index=0,
            issues=[],
            previous_issues=[],
            repair_units=[],
            verify_report=None,
            artifact_paths={},
        )
        assert summary.should_continue is False
        assert "resolved" in summary.reason.lower() or "no" in summary.reason.lower()

    def test_should_continue_true_when_serious_issues(self):
        settler = TurnSettler()
        issues = [
            _make_issue("i1", severity=Severity.CRITICAL),
        ]
        repair_units = [
            RepairUnit(
                repair_unit_id="r1",
                issue_cluster=["i1"],
                repair_type="layout_repair",
                status="applied",
            )
        ]
        summary = settler.settle(
            turn_index=0,
            issues=issues,
            previous_issues=[],
            repair_units=repair_units,
            verify_report=None,
            artifact_paths={},
        )
        assert summary.should_continue is True

    def test_should_stop_on_regression(self):
        settler = TurnSettler()
        issues = [_make_issue("i1", severity=Severity.MAJOR)]
        verify_report = VerifyReport(
            turn_index=1,
            items=[
                VerifyItem(
                    issue_id="i1",
                    rubric_id="B3",
                    repair_unit_id="r1",
                    verdict=Verdict.FAIL,
                    regression_detected=True,
                )
            ],
            total_checked=1,
            passed=0,
            failed=1,
            regressions=1,
        )
        repair_units = [
            RepairUnit(
                repair_unit_id="r1",
                issue_cluster=["i1"],
                repair_type="layout_repair",
                status="applied",
            )
        ]
        summary = settler.settle(
            turn_index=1,
            issues=issues,
            previous_issues=[_make_issue("i1")],
            repair_units=repair_units,
            verify_report=verify_report,
            artifact_paths={},
        )
        assert summary.should_continue is True

    def test_should_stop_when_no_repairs_applied(self):
        settler = TurnSettler()
        issues = [_make_issue("i1", severity=Severity.MAJOR)]
        repair_units = [
            RepairUnit(
                repair_unit_id="r1",
                issue_cluster=["i1"],
                repair_type="layout_repair",
                status="failed",  # not applied
            )
        ]
        summary = settler.settle(
            turn_index=1,  # turn_index > 0
            issues=issues,
            previous_issues=[_make_issue("i1")],
            repair_units=repair_units,
            verify_report=None,
            artifact_paths={},
        )
        assert summary.should_continue is False

    def test_should_continue_true_with_minor_issues(self):
        """Minor issues should also trigger repair (minor repair enabled)."""
        settler = TurnSettler()
        issues = [
            _make_issue("i1", severity=Severity.MINOR),
            _make_issue("i2", severity=Severity.MINOR),
        ]
        summary = settler.settle(
            turn_index=0,
            issues=issues,
            previous_issues=[],
            repair_units=[],
            verify_report=None,
            artifact_paths={},
        )
        assert summary.should_continue is True

    def test_issue_counts(self):
        settler = TurnSettler()
        old_issues = [
            _make_issue("old_1"),
            _make_issue("old_2"),
        ]
        new_issues = [
            _make_issue("old_1"),  # persisting
            _make_issue("new_1", severity=Severity.CRITICAL),  # new
        ]
        repair_units = [
            RepairUnit(
                repair_unit_id="r1",
                issue_cluster=["old_2"],
                repair_type="layout_repair",
                status="applied",
            )
        ]
        summary = settler.settle(
            turn_index=1,
            issues=new_issues,
            previous_issues=old_issues,
            repair_units=repair_units,
            verify_report=None,
            artifact_paths={},
        )
        assert summary.total_issues_found == 2
        assert summary.issues_resolved == 1  # old_2 gone
        assert summary.issues_new == 1  # new_1

    def test_artifact_paths_preserved(self):
        settler = TurnSettler()
        paths = {"pptx": "/out/deck.pptx", "pdf": "/out/deck.pdf"}
        summary = settler.settle(
            turn_index=0,
            issues=[],
            previous_issues=[],
            repair_units=[],
            verify_report=None,
            artifact_paths=paths,
        )
        assert summary.artifact_paths == paths

    def test_repair_units_applied_count(self):
        settler = TurnSettler()
        repair_units = [
            RepairUnit(repair_unit_id="r1", issue_cluster=["i1"],
                       repair_type="layout_repair", status="applied"),
            RepairUnit(repair_unit_id="r2", issue_cluster=["i2"],
                       repair_type="content_repair", status="applied"),
            RepairUnit(repair_unit_id="r3", issue_cluster=["i3"],
                       repair_type="style_repair", status="failed"),
        ]
        summary = settler.settle(
            turn_index=0,
            issues=[],
            previous_issues=[],
            repair_units=repair_units,
            verify_report=None,
            artifact_paths={},
        )
        assert summary.repair_units_applied == 2

    def test_verify_counts(self):
        settler = TurnSettler()
        verify_report = VerifyReport(
            turn_index=1,
            items=[],
            total_checked=5,
            passed=3,
            failed=2,
            regressions=0,
        )
        summary = settler.settle(
            turn_index=1,
            issues=[],
            previous_issues=[],
            repair_units=[],
            verify_report=verify_report,
            artifact_paths={},
        )
        assert summary.verify_pass_count == 3
        assert summary.verify_fail_count == 2

    def test_wont_fix_counted(self):
        settler = TurnSettler()
        issues = [
            _make_issue("i1", status=IssueStatus.WONT_FIX),
            _make_issue("i2", status=IssueStatus.WONT_FIX),
            _make_issue("i3", status=IssueStatus.OPEN),
        ]
        summary = settler.settle(
            turn_index=0,
            issues=issues,
            previous_issues=[],
            repair_units=[],
            verify_report=None,
            artifact_paths={},
        )
        assert summary.issues_wont_fix == 2
