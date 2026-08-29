"""Issue schema - evaluation findings."""

from pydantic import BaseModel, Field

from .common import Confidence, IssueStatus, RepairAction, Severity, Verdict


class FixDetail(BaseModel):
    """Concrete fix specification from judge (primarily for C/D issues)."""

    correct_content: str = Field(
        default="",
        description="Exact text/data from source that should appear on the slide"
    )
    source_ref: str = Field(
        default="",
        description="Source chunk ID or passage containing the correct information"
    )
    target_location: str = Field(
        default="",
        description="Where on the slide to apply the fix (e.g. 'bullet 3', 'subtitle', 'new row in table')"
    )
    action_type: str = Field(
        default="",
        description="Type of edit: replace_text, add_bullet, add_data_row, remove_text, rewrite_claim"
    )


class IssueEvidence(BaseModel):
    """Evidence supporting an issue finding."""

    render_ref: str = ""
    object_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    description: str = ""


class Issue(BaseModel):
    """A single evaluation issue."""

    issue_id: str
    rubric_id: str = Field(description="e.g. A1, B3, C2, D1, E2")
    issue_type: str = Field(description="e.g. overlap, missing_content, incorrect_claim, density")
    sub_type: str = Field(default="", description="e.g. sparse_content, cramped_content, element_undersized, column_height_mismatch")
    severity: Severity
    confidence: Confidence = Confidence.HIGH
    affected_slides: list[int] = Field(default_factory=list)
    evidence: IssueEvidence = Field(default_factory=IssueEvidence)
    suspected_module: str = Field(
        default="unknown",
        description="Which module likely caused this: planner, codegen_compiler, evaluator"
    )
    status: IssueStatus = IssueStatus.OPEN
    verdict: Verdict = Verdict.FAIL
    why_this_fails: str = ""
    fixability: str = Field(default="unknown", description="easy_local_patch, medium, hard, requires_redesign")
    planned_fix: str = ""
    fix_detail: FixDetail = Field(
        default_factory=FixDetail,
        description="Concrete fix specification with exact content from source (primarily for C/D issues)"
    )
    recommended_action: RepairAction = Field(
        default=RepairAction.PATCH,
        description="Judge-recommended repair action: KEEP (skip), PATCH (text-only edit), REGEN (structural code change)"
    )
    action_rationale: str = Field(
        default="",
        description="Why the judge chose this action type"
    )
    resolved_at_turn: int | None = Field(
        default=None,
        description="Turn index at which this issue was resolved by the judge (None = still open)"
    )
    source_probe_id: str = Field(
        default="",
        description="ID of the probe that originally detected this issue (e.g. 'pw_overflow', "
                    "'geom_overlap', 'visual_judge_B9'). Used by regression verifier to know "
                    "which probe to re-run when checking resolved issues."
    )
    persisted_turns: int = Field(
        default=0,
        description="Number of consecutive turns this issue has been carried forward as "
                    "PERSISTED after a repair attempt. This is diagnostic history only; "
                    "repair escalation must use actual repair-attempt outcomes."
    )
    last_triaged_turn: int | None = Field(
        default=None,
        description="Most recent repair turn in which a current-render probe triaged "
                    "this issue. Prevents duplicate same-turn probe calls from mutating "
                    "lifecycle counters more than once."
    )
