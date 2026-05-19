"""RenderManager - dispatches rendering to configured backends."""

import logging
from pathlib import Path

from ..schemas.common import RenderBackendType, Status
from ..schemas.experiment_config import ExperimentConfig
from ..schemas.render_result import RenderResult
from ..render_backends.libreoffice_backend import LibreOfficePdfRenderBackend
from ..utils.io_utils import write_json

logger = logging.getLogger(__name__)


class RenderManager:
    """Manages render backends and dispatches rendering tasks."""

    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.backends: dict[str, object] = {}
        self._init_backends()

    def _init_backends(self) -> None:
        """Initialize configured render backends."""
        # Always initialize LibreOffice if configured
        fast = self.config.render_mode.fast_backend
        ref = self.config.render_mode.reference_backend

        for backend_type in {fast, ref}:
            if backend_type == RenderBackendType.LINUX_LO_PDF:
                self.backends["linux_lo_pdf"] = LibreOfficePdfRenderBackend()

    def render_fast(
        self,
        pptx_path: str,
        output_dir: str,
    ) -> RenderResult:
        """Render using the fast/approximate backend."""
        backend_name = self.config.render_mode.fast_backend.value
        return self._render(backend_name, pptx_path, output_dir)

    def render_reference(
        self,
        pptx_path: str,
        output_dir: str,
    ) -> RenderResult:
        """Render using the reference backend."""
        backend_name = self.config.render_mode.reference_backend.value
        return self._render(backend_name, pptx_path, output_dir)

    def _render(
        self,
        backend_name: str,
        pptx_path: str,
        output_dir: str,
    ) -> RenderResult:
        """Render using a specific backend."""
        backend = self.backends.get(backend_name)
        if not backend:
            return RenderResult(
                backend_name=backend_name,
                status=Status.ERROR,
                error_message=f"Backend '{backend_name}' not initialized",
            )

        logger.info("Rendering %s with backend %s", pptx_path, backend_name)

        pdf_dir = str(Path(output_dir) / "pdf")
        png_dir = str(Path(output_dir) / "slide_png")
        pdf_path = str(Path(pdf_dir) / "deck.pdf")

        # Render PPTX -> PDF -> PNGs
        result = backend.render_pptx_to_pngs(pptx_path, png_dir)

        # Copy PDF to pdf subdir if it was created elsewhere
        if result.pdf_path and result.status == Status.OK:
            import shutil
            Path(pdf_dir).mkdir(parents=True, exist_ok=True)
            if str(result.pdf_path) != pdf_path:
                try:
                    shutil.copy2(result.pdf_path, pdf_path)
                    result.pdf_path = pdf_path
                except Exception:
                    pass

        # Save render meta
        if result.render_meta:
            meta_path = str(Path(output_dir) / "render_meta.json")
            write_json(result.render_meta, meta_path)

        return result
