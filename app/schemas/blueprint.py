"""DeckBlueprint schema - deck-level narrative plan."""

from pydantic import BaseModel, Field


class BlueprintSlide(BaseModel):
    """Plan for a single slide within the deck blueprint."""

    slide_id: int
    role: str = Field(description="e.g. title, context, method, results, comparison, conclusion")
    primary_proposition: str = Field(description="One-sentence main message for this slide")
    narrative_position: str = Field(description="e.g. opening, body, transition, closing")
    linked_evidence_ids: list[str] = Field(default_factory=list)
    source_doc_block_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    must_cover_subset: list[str] = Field(default_factory=list)
    assigned_figure_id: str = Field(
        default="",
        description=(
            "Figure ID assigned to this slide (e.g. 'fig_p1_fig1'). "
            "Empty if no figure should be used. Each figure should be "
            "assigned to at most one slide across the deck."
        ),
    )
    layout_hint: str = Field(
        default="",
        description=(
            "Layout hint for codegen: 'two-column' | 'image-hero' | "
            "'table-focus' | 'metric-cards' | 'quote-insight' | "
            "'three-column' | ''. Empty means codegen decides freely."
        ),
    )
    notes: str = ""


class DeckBlueprint(BaseModel):
    """Deck-level narrative plan output by DeckPlanner."""

    case_id: str
    total_slides: int
    narrative_arc: str = Field(description="High-level narrative strategy")
    slides: list[BlueprintSlide] = Field(default_factory=list)
    reasoning: str = Field(default="", description="Planner reasoning for deck structure")
