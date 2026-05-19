"""RepairUnit schema - a unit of repair work."""

from pydantic import BaseModel, Field


class RepairUnit(BaseModel):
    """Defines a unit of repair work tied to an issue cluster."""

    repair_unit_id: str
    issue_cluster: list[str] = Field(description="List of issue_ids to address together")
    repair_type: str = Field(
        description="content_repair, form_repair, layout_repair, style_repair"
    )
    affected_slides: list[int] = Field(default_factory=list)
    frozen_objects: list[str] = Field(
        default_factory=list,
        description="Object IDs that must not be modified"
    )
    editable_objects: list[str] = Field(
        default_factory=list,
        description="Object IDs that can be modified"
    )
    allowed_ops: list[str] = Field(
        default_factory=list,
        description="Permitted repair operations"
    )
    verify_targets: list[str] = Field(
        default_factory=list,
        description="Rubric IDs to re-check after repair"
    )
    repair_output: dict = Field(
        default_factory=dict,
        description="Structured repair instructions from LLM"
    )
    status: str = Field(default="pending", description="pending, applied, verified, failed")
