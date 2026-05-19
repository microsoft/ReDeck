"""EvalUnit schema - a unit of evaluation work."""

from pydantic import BaseModel, Field


class EvalUnit(BaseModel):
    """Defines a unit of evaluation: (rubric_family, scope, packet_type)."""

    eval_unit_id: str
    rubric_family: str = Field(description="A, B_visual, B_geom, C, D_numeric, D_claim, E")
    rubric_ids: list[str] = Field(description="Specific rubric items, e.g. ['A1','A2','A3']")
    scope: str = Field(description="deck, slide_N, slide_N_M")
    scope_slides: list[int] = Field(default_factory=list)
    packet_type: str = Field(
        description="outline_packet, slide_png_layout, text_packet, claim_packet, claim_evidence_packet, geometry_packet"
    )
    input_artifacts: list[str] = Field(
        default_factory=list,
        description="Paths to input artifacts for this eval unit"
    )
