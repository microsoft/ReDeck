"""EvidenceState schema - indexed source materials."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, PrivateAttr


class EvidenceChunk(BaseModel):
    """A chunk of source evidence."""

    chunk_id: str
    source_file: str
    content: str
    chunk_type: str = Field(description="text, table, figure_caption, numeric")
    page_ref: str | None = None
    metadata: dict = Field(default_factory=dict)


class FigureRef(BaseModel):
    """Reference to a figure/image in source materials."""

    figure_id: str
    source_file: str
    image_path: str | None = None
    caption: str = ""
    description: str = ""
    page_number: int | None = Field(default=None, description="Source page number (1-indexed)")
    bbox: list[float] = Field(
        default_factory=list,
        description="Bounding box [x0, y0, x1, y1] in PDF points"
    )
    width: int | None = Field(default=None, description="Image pixel width")
    height: int | None = Field(default=None, description="Image pixel height")
    figure_type: str = Field(
        default="embedded",
        description="raster | vector | composite | embedded | page_screenshot | region_crop"
    )


class TableRef(BaseModel):
    """Reference to a table in source materials."""

    table_id: str
    source_file: str
    content: str = ""
    caption: str = ""
    description: str = Field(
        default="",
        description="VLM-generated semantic description of the table"
    )
    headers: list[str] = Field(default_factory=list)
    row_count: int = 0
    image_path: str | None = Field(
        default=None,
        description="Path to high-DPI PNG screenshot of the table"
    )
    page_number: int | None = Field(
        default=None,
        description="Source page number (1-indexed)"
    )
    bbox: list[float] = Field(
        default_factory=list,
        description="Bounding box [x0, y0, x1, y1] in PDF points"
    )


class NumericFact(BaseModel):
    """An extracted numeric fact from sources."""

    fact_id: str
    value: str
    unit: str = ""
    context: str = ""
    source_ref: str = ""


class EntityEntry(BaseModel):
    """A named entity from source materials."""

    entity_id: str
    name: str
    entity_type: str = Field(description="person, method, dataset, metric, product, org")
    aliases: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class FormulaRef(BaseModel):
    """A LaTeX formula extracted from source materials."""

    formula_id: str
    latex: str = Field(description="Raw LaTeX source, e.g. 'E=mc^2'")
    display: bool = Field(
        default=False,
        description="True for display math ($$), False for inline ($)"
    )
    context: str = Field(
        default="",
        description="Surrounding text for context"
    )
    source_file: str = ""
    page_ref: str | None = None
    rendered_path: str | None = Field(
        default=None,
        description="Path to rendered PNG if pre-rendered"
    )


class EvidenceState(BaseModel):
    """Complete indexed evidence from source materials."""

    chunks: list[EvidenceChunk] = Field(default_factory=list)
    figures: list[FigureRef] = Field(default_factory=list)
    tables: list[TableRef] = Field(default_factory=list)
    numeric_facts: list[NumericFact] = Field(default_factory=list)
    entity_registry: list[EntityEntry] = Field(default_factory=list)
    formulas: list[FormulaRef] = Field(default_factory=list)

    # ── Lazy BM25 index (not serialized) ──
    _index: Any = PrivateAttr(default=None)

    def get_index(self) -> Any:
        """Return a BM25-backed EvidenceIndex, built lazily on first call."""
        if self._index is None:
            from ..modules.evaluators.eval_tools import EvidenceIndex
            self._index = EvidenceIndex(self)
        return self._index
