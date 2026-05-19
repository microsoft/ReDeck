"""CaseState schema - top-level case tracking."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from .evidence import EvidenceState
from .intent import IntentState

if TYPE_CHECKING:
    from ..modules.source_store import SourceStore


class CaseState(BaseModel):
    """Top-level state for a case being processed."""

    case_id: str
    case_dir: str
    intent: IntentState
    evidence: EvidenceState = Field(default_factory=EvidenceState)
    source_store: Any = None  # SourceStore | None — Any to avoid forward ref
    task_brief: str = ""
    constraints: dict = Field(default_factory=dict)
    revision_cards: list[dict] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}
