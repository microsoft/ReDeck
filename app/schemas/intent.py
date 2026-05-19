"""IntentState schema - captures the task intent and constraints."""

from pydantic import BaseModel, Field


class IntentState(BaseModel):
    """Captures what the user/task wants from the deck."""

    case_id: str
    deck_type: str = Field(description="e.g. conference_talk, executive_briefing, report_deck")
    audience: str = Field(description="Target audience description")
    page_budget: list[int] = Field(
        min_length=2, max_length=2,
        description="[min_pages, max_pages]"
    )
    must_cover: list[str] = Field(default_factory=list, description="Required topics/sections")
    must_avoid: list[str] = Field(default_factory=list, description="Topics/patterns to avoid")
    editable_required: bool = Field(default=True, description="Output must be editable PPTX")
    additional_constraints: dict = Field(default_factory=dict)
