"""VerifyReport schema - verification results after repair."""

from pydantic import BaseModel, Field

from .common import Verdict


class VerifyItem(BaseModel):
    """Verification result for a single issue/rubric."""

    issue_id: str
    rubric_id: str
    repair_unit_id: str
    verdict: Verdict
    evidence: str = ""
    regression_detected: bool = False
    regression_details: str = ""


class VerifyReport(BaseModel):
    """Complete verification report after repairs."""

    turn_index: int
    items: list[VerifyItem] = Field(default_factory=list)
    total_checked: int = 0
    passed: int = 0
    failed: int = 0
    regressions: int = 0
