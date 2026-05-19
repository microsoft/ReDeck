"""TurnSummary schema - summary of a single turn."""

from pydantic import BaseModel, Field

from .common import Status


class TurnSummary(BaseModel):
    """Summary of a single turn's results."""

    turn_index: int
    status: Status = Status.OK
    total_issues_found: int = 0
    issues_open: int = 0
    issues_resolved: int = 0
    issues_new: int = 0
    issues_wont_fix: int = 0
    issues_deferred: int = 0
    repair_units_applied: int = 0
    verify_pass_count: int = 0
    verify_fail_count: int = 0
    should_continue: bool = False
    reason: str = ""
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    timing_sec: float = 0.0
