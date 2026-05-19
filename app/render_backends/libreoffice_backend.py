"""LibreOffice PDF Render Backend - local fast/approximate rendering."""

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from ..schemas.common import RenderClass, Status
from ..schemas.render_result import RenderMeta, RenderResult
from ..utils.io_utils import ensure_dir

logger = logging.getLogger(__name__)


class LibreOfficePdfRenderBackend:
    """Renders PPTX to PDF using LibreOffice headless, then rasterizes to PNG."""

    name = "linux_lo_pdf"

    def __init__(
        self,
        soffice_binary: str = "soffice",
        pdf_filter: str = "impress_pdf_Export",
        rasterizer: str = "pdftocairo",
        dpi: int = 180,
        timeout_sec: int = 120,
    ):
        self.soffice_binary = soffice_binary
        self.pdf_filter = pdf_filter
        self.rasterizer = rasterizer
        self.dpi = dpi
        self.timeout_sec = timeout_sec

    def render_pptx_to_pdf(self, pptx_path: str, out_pdf_path: str) -> RenderResult:
        """Convert PPTX to PDF using LibreOffice headless.

        Uses a per-process unique user profile to avoid lock contention
        when multiple LibreOffice instances run in parallel.
        """
        start = time.time()
        warnings = []
        out_dir = str(Path(out_pdf_path).parent)
        ensure_dir(out_dir)

        # Create isolated user profile to avoid lock contention with parallel instances
        profile_dir = tempfile.mkdtemp(prefix=f"lo_profile_{os.getpid()}_")
        profile_uri = f"file://{profile_dir}"

        cmd = [
            self.soffice_binary,
            "--headless",
            f"-env:UserInstallation={profile_uri}",
            f"--convert-to", f"pdf:{self.pdf_filter}",
            "--outdir", out_dir,
            pptx_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )

            if result.returncode != 0:
                self._cleanup_profile(profile_dir)
                return RenderResult(
                    backend_name=self.name,
                    status=Status.ERROR,
                    error_message=f"soffice failed: {result.stderr}",
                    warnings=[result.stderr],
                    timing_sec=time.time() - start,
                )

            # LibreOffice outputs PDF with same name as input but .pdf extension
            lo_output = Path(out_dir) / (Path(pptx_path).stem + ".pdf")
            if lo_output.exists() and str(lo_output) != out_pdf_path:
                lo_output.rename(out_pdf_path)

            if result.stderr:
                warnings.append(result.stderr.strip())

            # Warn if PDF was not produced (silent failure)
            if not Path(out_pdf_path).exists():
                warnings.append("soffice returned 0 but no PDF was produced")
                logger.warning(
                    "LibreOffice rendered successfully (rc=0) but no PDF output at %s",
                    out_pdf_path,
                )

            # Get version info
            version = self._get_version()

            elapsed = time.time() - start
            self._cleanup_profile(profile_dir)
            return RenderResult(
                backend_name=self.name,
                status=Status.OK,
                pdf_path=out_pdf_path,
                timing_sec=elapsed,
                warnings=warnings,
                render_meta=RenderMeta(
                    backend_name=self.name,
                    render_class=RenderClass.APPROX_RENDER,
                    office_family="libreoffice",
                    version=version,
                    warnings=warnings,
                ),
            )

        except subprocess.TimeoutExpired:
            self._cleanup_profile(profile_dir)
            return RenderResult(
                backend_name=self.name,
                status=Status.ERROR,
                error_message=f"soffice timed out after {self.timeout_sec}s",
                timing_sec=time.time() - start,
            )
        except FileNotFoundError:
            self._cleanup_profile(profile_dir)
            return RenderResult(
                backend_name=self.name,
                status=Status.ERROR,
                error_message=f"soffice binary not found: {self.soffice_binary}",
                timing_sec=time.time() - start,
            )

    def rasterize_pdf_to_pngs(
        self, pdf_path: str, out_dir: str, dpi: int | None = None
    ) -> RenderResult:
        """Rasterize PDF to PNG images using pdftocairo or pdf2image."""
        start = time.time()
        ensure_dir(out_dir)
        dpi = dpi or self.dpi

        # Try pdftocairo first, fall back to pdf2image
        try:
            png_paths = self._rasterize_pdftocairo(pdf_path, out_dir, dpi)
        except (FileNotFoundError, subprocess.CalledProcessError):
            try:
                png_paths = self._rasterize_pdf2image(pdf_path, out_dir, dpi)
            except Exception as e:
                return RenderResult(
                    backend_name=self.name,
                    status=Status.ERROR,
                    error_message=f"PDF rasterization failed: {e}",
                    timing_sec=time.time() - start,
                )

        return RenderResult(
            backend_name=self.name,
            status=Status.OK,
            pdf_path=pdf_path,
            png_paths=png_paths,
            slide_count=len(png_paths),
            timing_sec=time.time() - start,
        )

    def render_pptx_to_pngs(self, pptx_path: str, out_dir: str) -> RenderResult:
        """Convert PPTX to PNGs via PDF intermediate."""
        ensure_dir(out_dir)
        pdf_path = str(Path(out_dir) / "deck.pdf")

        # Step 1: PPTX -> PDF
        pdf_result = self.render_pptx_to_pdf(pptx_path, pdf_path)
        if pdf_result.status != Status.OK:
            return pdf_result

        # Step 2: PDF -> PNGs
        png_result = self.rasterize_pdf_to_pngs(pdf_path, out_dir)

        # Merge results
        return RenderResult(
            backend_name=self.name,
            status=png_result.status,
            pdf_path=pdf_path,
            png_paths=png_result.png_paths,
            slide_count=png_result.slide_count,
            warnings=pdf_result.warnings + png_result.warnings,
            timing_sec=pdf_result.timing_sec + png_result.timing_sec,
            render_meta=pdf_result.render_meta,
        )

    def _rasterize_pdftocairo(self, pdf_path: str, out_dir: str, dpi: int) -> list[str]:
        """Rasterize using pdftocairo."""
        prefix = str(Path(out_dir) / "slide")
        cmd = [
            self.rasterizer,
            "-png",
            "-r", str(dpi),
            pdf_path,
            prefix,
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=self.timeout_sec)

        # Collect output PNGs
        png_dir = Path(out_dir)
        pngs = sorted(str(p) for p in png_dir.glob("slide-*.png"))
        return pngs

    def _rasterize_pdf2image(self, pdf_path: str, out_dir: str, dpi: int) -> list[str]:
        """Rasterize using pdf2image (Python library)."""
        from pdf2image import convert_from_path

        images = convert_from_path(pdf_path, dpi=dpi)
        png_paths = []
        for i, img in enumerate(images):
            png_path = str(Path(out_dir) / f"slide_{i + 1:03d}.png")
            img.save(png_path, "PNG")
            png_paths.append(png_path)
        return png_paths

    @staticmethod
    def _cleanup_profile(profile_dir: str) -> None:
        """Remove temporary LibreOffice user profile directory."""
        import shutil
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass  # Best effort cleanup

    def _get_version(self) -> str:
        """Get LibreOffice version."""
        try:
            result = subprocess.run(
                [self.soffice_binary, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"
