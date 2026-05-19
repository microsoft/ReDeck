"""RenderResult schema - output of render backends."""

from pydantic import BaseModel, Field

from .common import RenderClass, Status


class RenderMeta(BaseModel):
    """Metadata about a render operation."""

    backend_name: str
    render_class: RenderClass
    office_family: str = Field(description="libreoffice, microsoft_graph, powerpoint_mac")
    version: str = ""
    font_manifest_hash: str = ""
    warnings: list[str] = Field(default_factory=list)


class RenderResult(BaseModel):
    """Complete result of a render operation."""

    backend_name: str
    status: Status
    pdf_path: str = ""
    png_paths: list[str] = Field(default_factory=list)
    slide_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    font_info: dict = Field(default_factory=dict)
    timing_sec: float = 0.0
    render_meta: RenderMeta | None = None
    error_message: str = ""
