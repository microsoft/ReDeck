"""RenderBackend protocol and base types."""

from typing import Protocol, runtime_checkable

from ..schemas.render_result import RenderResult


@runtime_checkable
class RenderBackend(Protocol):
    """Protocol for render backends."""

    name: str

    def render_pptx_to_pdf(self, pptx_path: str, out_pdf_path: str) -> RenderResult:
        """Convert PPTX to PDF."""
        ...

    def rasterize_pdf_to_pngs(self, pdf_path: str, out_dir: str, dpi: int = 180) -> RenderResult:
        """Rasterize PDF to PNG images."""
        ...

    def render_pptx_to_pngs(self, pptx_path: str, out_dir: str) -> RenderResult:
        """Convert PPTX to PNG images (via PDF intermediate)."""
        ...
