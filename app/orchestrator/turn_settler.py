"""TurnSettler - summarizes a turn and decides whether to continue."""

import logging

from ..schemas.common import IssueStatus, RepairAction, Severity, Status
from ..schemas.issue import Issue
from ..schemas.repair_unit import RepairUnit
from ..schemas.turn_summary import TurnSummary
from ..schemas.verify_report import VerifyReport
from ..utils.diff_utils import diff_issue_lists

logger = logging.getLogger(__name__)


class TurnSettler:
    """Computes turn summary and decides whether another turn is needed."""

    def __init__(
        self,
        early_stop_turn: int = 6,
        plateau_window: int = 4,
        good_enough_threshold: int = 10,
    ):
        self.early_stop_turn = early_stop_turn
        self.plateau_window = plateau_window
        self.good_enough_threshold = good_enough_threshold

    def settle(
        self,
        turn_index: int,
        issues: list[Issue],
        previous_issues: list[Issue],
        repair_units: list[RepairUnit],
        verify_report: VerifyReport | None,
        artifact_paths: dict[str, str],
        timing_sec: float = 0.0,
        previous_issue_counts: list[int] | None = None,
    ) -> TurnSummary:
        """Compute turn summary.

        Args:
            previous_issue_counts: list of total issue counts from all prior turns
                (used for stagnation detection).
        """
        # Diff issues
        old_dicts = [i.model_dump() for i in previous_issues]
        new_dicts = [i.model_dump() for i in issues]
        diff = diff_issue_lists(old_dicts, new_dicts)

        issues_open = sum(1 for i in issues if i.status == IssueStatus.OPEN)
        issues_resolved = len(diff["resolved"])
        issues_new = len(diff["new"])

        # All issue types are now actionable for churn detection and repair.
        actionable_new = len(diff["new"])
        actionable_resolved = len(diff["resolved"])

        # Decide whether to continue
        should_continue = self._should_continue(
            issues, repair_units, verify_report, turn_index,
            previous_issues=previous_issues,
            previous_issue_counts=previous_issue_counts,
            current_issue_count=len(issues),
            issues_new=actionable_new,
            issues_resolved=actionable_resolved,
        )

        reason = self._make_reason(
            issues_open, issues_resolved, issues_new,
            verify_report, should_continue,
        )

        summary = TurnSummary(
            turn_index=turn_index,
            status=Status.OK,
            total_issues_found=len(issues),
            issues_open=issues_open,
            issues_resolved=issues_resolved,
            issues_new=issues_new,
            issues_wont_fix=sum(1 for i in issues if i.status == IssueStatus.WONT_FIX),
            issues_deferred=sum(1 for i in issues if i.status == IssueStatus.DEFERRED),
            repair_units_applied=sum(1 for u in repair_units if u.status == "applied"),
            verify_pass_count=verify_report.passed if verify_report else 0,
            verify_fail_count=verify_report.failed if verify_report else 0,
            should_continue=should_continue,
            reason=reason,
            artifact_paths=artifact_paths,
            timing_sec=timing_sec,
        )

        logger.info(
            "Turn %d settled: %d issues (%d open, %d resolved, %d new), continue=%s",
            turn_index, len(issues), issues_open, issues_resolved, issues_new,
            should_continue,
        )
        return summary

    def _should_continue(
        self,
        issues: list[Issue],
        repair_units: list[RepairUnit],
        verify_report: VerifyReport | None,
        turn_index: int,
        previous_issues: list[Issue] | None = None,
        previous_issue_counts: list[int] | None = None,
        current_issue_count: int = 0,
        issues_new: int = 0,
        issues_resolved: int = 0,
    ) -> bool:
        """Decide whether another turn is needed."""
        # Stop if no open issues at all (including minor)
        # Exclude KEEP issues — judge says they don't need repair
        open_issues = [
            i for i in issues
            if i.status == IssueStatus.OPEN
            and i.recommended_action != RepairAction.KEEP
        ]
        if not open_issues:
            return False

        # Stop if no repairs were successfully applied
        applied = sum(1 for u in repair_units if u.status == "applied")
        if applied == 0 and turn_index > 0:
            return False

        # Open current-render findings are not terminal success. Risk is
        # bounded by the no-applied-repair check, rebound detection, plateau
        # window, and RunManager.max_turns rather than by hiding a small issue
        # count behind a "good enough" label.
        _CONTENT_ACCURACY_TYPES = {
            "fabricated", "missing_evidence", "incorrect_claim",
            "numeric_error", "entity_error", "missing_point",
            "missing_entity", "missing_data_visualization",
            "missing_conclusion", "unfaithful_compression",
        }
        major_content_open = [
            i for i in open_issues
            if i.severity in (Severity.MAJOR, Severity.CRITICAL)
            and i.issue_type in _CONTENT_ACCURACY_TYPES
        ]
        # Rebound detection: based on issue-ID tracking, not raw count.
        # A true rebound = previously-resolved issues re-opened, or
        # previously-open issues got worse. Newly-discovered issues
        # (first-time IDs from expanded eval coverage) are NOT rebound.
        if previous_issues and turn_index >= 1:
            prev_open_ids = {
                i.issue_id for i in previous_issues
                if i.status == IssueStatus.OPEN
            }
            cur_open_ids = {i.issue_id for i in open_issues}

            # Issues that were open before and are still open (persisted)
            persisted_ids = prev_open_ids & cur_open_ids
            # Issues that were resolved/closed but re-appeared as open
            prev_resolved_ids = {
                i.issue_id for i in previous_issues
                if i.status in (IssueStatus.RESOLVED, IssueStatus.WONT_FIX)
            }
            reopened_ids = prev_resolved_ids & cur_open_ids
            # Truly new issues (IDs never seen in previous turn)
            prev_all_ids = {i.issue_id for i in previous_issues}
            newly_discovered = cur_open_ids - prev_all_ids
            # Issues resolved this turn
            resolved_ids = prev_open_ids - cur_open_ids

            # True regression = reopened issues (were resolved, now open again)
            # Net progress = resolved minus reopened
            net_progress = len(resolved_ids) - len(reopened_ids)

            logger.info(
                "T%d issue-ID tracking: %d resolved, %d persisted, "
                "%d newly discovered, %d reopened, net_progress=%+d",
                turn_index, len(resolved_ids), len(persisted_ids),
                len(newly_discovered), len(reopened_ids), net_progress,
            )

            if net_progress < 0:
                # True regression: more issues reopened than resolved
                if major_content_open and abs(net_progress) <= 2:
                    logger.info(
                        "T%d true rebound %+d but %d MAJOR content-accuracy "
                        "issues still open — continuing.",
                        turn_index, net_progress, len(major_content_open),
                    )
                else:
                    logger.info(
                        "Rebound detected at T%d: net_progress=%+d "
                        "(%d resolved, %d reopened). "
                        "Stopping to preserve previous turn's state.",
                        turn_index, net_progress,
                        len(resolved_ids), len(reopened_ids),
                    )
                    return False

        # Early stop: after turn 6, check if we're in a plateau.
        if (
            turn_index >= self.early_stop_turn
            and previous_issue_counts
            and len(previous_issue_counts) >= self.plateau_window
        ):
            count_n_ago = previous_issue_counts[-self.plateau_window]
            net_improvement = count_n_ago - len(open_issues)
            if net_improvement <= 0:
                logger.info(
                    "Early stop at T%d: net improvement over last 4 turns "
                    "is %d (<= 0 threshold). %d open issues remain.",
                    turn_index, net_improvement, len(open_issues),
                )
                return False

        return True

    def _make_reason(
        self,
        issues_open: int,
        issues_resolved: int,
        issues_new: int,
        verify_report: VerifyReport | None,
        should_continue: bool,
    ) -> str:
        """Generate human-readable reason for continue/stop decision."""
        parts = []
        if not should_continue:
            if issues_open == 0:
                parts.append("All issues resolved")
            else:
                parts.append(f"{issues_open} open issues remain but no further repair progress possible")
        else:
            parts.append(f"{issues_open} open issues remain, continuing")
            if issues_resolved > 0:
                parts.append(f"{issues_resolved} resolved this turn")
            if issues_new > 0:
                parts.append(f"{issues_new} new issues found")
        return "; ".join(parts)
