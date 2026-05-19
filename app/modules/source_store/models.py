"""Pydantic schemas for the SourceStore module."""

from pydantic import BaseModel, Field, PrivateAttr


class AtomicBlock(BaseModel):
    """Smallest text/layout unit from PDF extraction."""
    block_id: str  # B001, B002, ...
    type: str  # heading / paragraph / list_item / caption / formula / footnote
    page: int | None = None
    text: str
    bbox: list[float] = Field(default_factory=list)


class Asset(BaseModel):
    """Figure, table screenshot, or page screenshot."""
    asset_id: str  # A001, A002, ...
    type: str  # figure / table_image / page_screenshot
    page: int | None = None
    image_path: str = ""
    caption: str = ""
    bbox: list[float] = Field(default_factory=list)
    summary: str = ""
    linked_block_ids: list[str] = Field(default_factory=list)


class TableData(BaseModel):
    """Table with both image and structured text."""
    table_id: str  # T001, T002, ...
    caption: str = ""
    page: int | None = None
    rows_or_markdown: str = ""
    image_asset_id: str | None = None
    summary: str = ""
    linked_block_ids: list[str] = Field(default_factory=list)


class DocumentBlock(BaseModel):
    """LLM-produced semantic sub-document block."""
    doc_block_id: str  # DB001, DB002, ...
    title: str
    section_path: str = ""
    role: str = "generic"  # overview / background / method / evidence / result / caveat / appendix / generic
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    included_atomic_block_ids: list[str] = Field(default_factory=list)
    linked_asset_ids: list[str] = Field(default_factory=list)
    linked_table_ids: list[str] = Field(default_factory=list)
    page_range: list[int] = Field(default_factory=list)
    importance: str = "medium"  # high / medium / low
    slide_usage_hint: str = ""  # title_slide / concept_slide / evidence_slide / visual_slide / backup
    split_reason: str = ""


class DocumentBlockPlan(BaseModel):
    """LLM output: complete document blocking plan."""
    document_profile: str = "generic"  # technical_report / paper / manual / spec / business_report / generic
    blocks: list[DocumentBlock] = Field(default_factory=list)


class SlideSourceBundle(BaseModel):
    """Per-slide evidence package for codegen/judge/repair."""
    slide_id: int
    slide_title: str = ""
    source_doc_block_ids: list[str] = Field(default_factory=list)
    source_atomic_block_ids: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    source_text: str = ""
    asset_summaries: list[str] = Field(default_factory=list)
    table_summaries: list[str] = Field(default_factory=list)
    generation_notes: str = ""


class SourceStore(BaseModel):
    """Complete document store — replaces EvidenceState.

    Central container holding all source material artifacts:
    - AtomicBlocks: smallest text units from PDF extraction
    - Assets: figures, table screenshots, page screenshots
    - TableData: structured table content
    - DocumentBlockPlan: LLM-produced semantic groupings
    - SlideSourceBundles: per-slide evidence packages
    - Summary index: structured resource index for planning
    """
    atomic_blocks: list[AtomicBlock] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    table_data: list[TableData] = Field(default_factory=list)
    doc_block_plan: DocumentBlockPlan = Field(default_factory=DocumentBlockPlan)
    summary_index: dict = Field(default_factory=dict)
    bundles: dict[int, SlideSourceBundle] = Field(default_factory=dict)
    anchored_doc: str = ""

    # Legacy compatibility
    _evidence_state: object = PrivateAttr(default=None)

    def get_bundle(self, slide_id: int) -> SlideSourceBundle | None:
        """Get the source bundle for a specific slide."""
        return self.bundles.get(slide_id)

    def get_block(self, block_id: str) -> AtomicBlock | None:
        """Look up an atomic block by ID."""
        for b in self.atomic_blocks:
            if b.block_id == block_id:
                return b
        return None

    def get_asset(self, asset_id: str) -> Asset | None:
        """Look up an asset by ID."""
        for a in self.assets:
            if a.asset_id == asset_id:
                return a
        return None

    def get_doc_block(self, doc_block_id: str) -> DocumentBlock | None:
        """Look up a document block by ID."""
        for db in self.doc_block_plan.blocks:
            if db.doc_block_id == doc_block_id:
                return db
        return None

    def to_evidence_state(self):
        """Backward compat: convert to legacy EvidenceState for un-migrated consumers.

        Lazily imports EvidenceState to avoid circular dependencies.
        """
        if self._evidence_state is not None:
            return self._evidence_state

        from ...schemas.evidence import (
            EvidenceChunk, EvidenceState, FigureRef, TableRef,
        )

        chunks = [
            EvidenceChunk(
                chunk_id=ab.block_id,
                source_file="paper_full.md",
                content=ab.text,
                chunk_type="text",
                page_ref=f"p{ab.page}" if ab.page else None,
            )
            for ab in self.atomic_blocks
        ]

        figures = [
            FigureRef(
                figure_id=a.asset_id,
                source_file="paper_full.md",
                image_path=a.image_path,
                caption=a.caption,
                description=a.summary,
                page_number=a.page,
            )
            for a in self.assets
            if a.type == "figure"
        ]

        tables = [
            TableRef(
                table_id=t.table_id,
                source_file="paper_full.md",
                content=t.rows_or_markdown,
                caption=t.caption,
                description=t.summary,
                page_number=t.page,
            )
            for t in self.table_data
        ]

        self._evidence_state = EvidenceState(
            chunks=chunks,
            figures=figures,
            tables=tables,
        )
        return self._evidence_state

    def format_summary_index(self) -> str:
        """Format summary index as text for LLM consumption.

        Returns a compact structured overview (~3-5K chars) suitable for
        planner and judge global context.
        """
        if not self.summary_index:
            return ""

        parts: list[str] = []

        block_index = self.summary_index.get("block_index", [])
        if block_index:
            parts.append("## Document Block Index")
            for entry in block_index:
                dbid = entry.get("doc_block_id", "?")
                title = entry.get("title", "")
                role = entry.get("role", "")
                imp = entry.get("importance", "")
                summary = entry.get("summary", "")
                assets = entry.get("linked_asset_ids", [])
                tables = entry.get("linked_table_ids", [])
                parts.append(f"[{dbid}] {title} | role={role} | importance={imp}")
                if summary:
                    parts.append(f"  Summary: {summary}")
                if assets or tables:
                    parts.append(f"  Assets: {assets} | Tables: {tables}")

        asset_index = self.summary_index.get("asset_index", [])
        if asset_index:
            parts.append("\n## Asset Index")
            for entry in asset_index:
                aid = entry.get("asset_id", "?")
                atype = entry.get("type", "")
                page = entry.get("page", "?")
                caption = (entry.get("caption", "") or "")[:120]
                parts.append(f"[{aid}] {atype} p{page} | caption: {caption}")

        table_index = self.summary_index.get("table_index", [])
        if table_index:
            parts.append("\n## Table Index")
            for entry in table_index:
                tid = entry.get("table_id", "?")
                caption = (entry.get("caption", "") or "")[:120]
                headers = entry.get("headers", [])
                rows = entry.get("row_count", 0)
                parts.append(f"[{tid}] {caption} | headers: {headers} | rows: {rows}")

        return "\n".join(parts)
