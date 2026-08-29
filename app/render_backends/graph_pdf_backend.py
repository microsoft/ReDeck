"""Microsoft Graph PDF Render Backend - cloud reference rendering."""

import logging
import time
from pathlib import Path

import httpx

from ..schemas.common import RenderClass, Status
from ..schemas.render_result import RenderMeta, RenderResult
from ..utils.graph_auth import GraphAuthClient
from ..utils.io_utils import ensure_dir

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphPdfRenderBackend:
    """Renders PPTX to PDF using Microsoft Graph API (cloud conversion)."""

    name = "graph_pdf"

    def __init__(
        self,
        tenant_id: str = "",
        client_id: str = "",
        client_secret_env: str = "MS_GRAPH_CLIENT_SECRET",
        drive_id: str = "",
        upload_folder: str = "/slide-agent-render-cache",
        cleanup_remote_after_render: bool = True,
        dpi: int = 180,
        timeout_sec: int = 180,
    ):
        self.drive_id = drive_id
        self.upload_folder = upload_folder
        self.cleanup_remote = cleanup_remote_after_render
        self.dpi = dpi
        self.timeout_sec = timeout_sec

        self.auth = GraphAuthClient(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret_env=client_secret_env,
        )

    def render_pptx_to_pdf(self, pptx_path: str, out_pdf_path: str) -> RenderResult:
        """Convert PPTX to PDF using Microsoft Graph."""
        start = time.time()
        ensure_dir(Path(out_pdf_path).parent)

        try:
            headers = self.auth.get_headers()
        except Exception as e:
            return RenderResult(
                backend_name=self.name,
                status=Status.ERROR,
                error_message=f"Graph auth failed: {e}",
                timing_sec=time.time() - start,
            )

        try:
            # Step 1: Upload PPTX
            item_id = self._upload_file(pptx_path, headers)

            # Step 2: Download as PDF
            self._download_as_pdf(item_id, out_pdf_path, headers)

            # Step 3: Cleanup
            if self.cleanup_remote:
                self._delete_remote(item_id, headers)

            elapsed = time.time() - start
            return RenderResult(
                backend_name=self.name,
                status=Status.OK,
                pdf_path=out_pdf_path,
                timing_sec=elapsed,
                render_meta=RenderMeta(
                    backend_name=self.name,
                    render_class=RenderClass.REFERENCE_RENDER,
                    office_family="microsoft_graph",
                    version="v1.0",
                ),
            )

        except httpx.HTTPStatusError as e:
            error_type = "graph_auth_error" if e.response.status_code in (401, 403) else "graph_api_error"
            return RenderResult(
                backend_name=self.name,
                status=Status.ERROR,
                error_message=f"Graph API error ({e.response.status_code}): {e.response.text[:500]}",
                timing_sec=time.time() - start,
            )
        except Exception as e:
            return RenderResult(
                backend_name=self.name,
                status=Status.ERROR,
                error_message=f"Graph render failed: {e}",
                timing_sec=time.time() - start,
            )

    def rasterize_pdf_to_pngs(
        self, pdf_path: str, out_dir: str, dpi: int | None = None
    ) -> RenderResult:
        """Rasterize PDF to PNGs using pdf2image."""
        start = time.time()
        ensure_dir(out_dir)
        dpi = dpi or self.dpi

        try:
            from pdf2image import convert_from_path

            images = convert_from_path(pdf_path, dpi=dpi)
            png_paths = []
            for i, img in enumerate(images):
                png_path = str(Path(out_dir) / f"slide_{i + 1:03d}.png")
                img.save(png_path, "PNG")
                png_paths.append(png_path)

            return RenderResult(
                backend_name=self.name,
                status=Status.OK,
                pdf_path=pdf_path,
                png_paths=png_paths,
                slide_count=len(png_paths),
                timing_sec=time.time() - start,
            )
        except Exception as e:
            return RenderResult(
                backend_name=self.name,
                status=Status.ERROR,
                error_message=f"PDF rasterization failed: {e}",
                timing_sec=time.time() - start,
            )

    def render_pptx_to_pngs(self, pptx_path: str, out_dir: str) -> RenderResult:
        """Convert PPTX to PNGs via Graph PDF conversion."""
        ensure_dir(out_dir)
        pdf_path = str(Path(out_dir) / "deck.pdf")

        pdf_result = self.render_pptx_to_pdf(pptx_path, pdf_path)
        if pdf_result.status != Status.OK:
            return pdf_result

        png_result = self.rasterize_pdf_to_pngs(pdf_path, out_dir)
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

    def _upload_file(self, local_path: str, headers: dict) -> str:
        """Upload a file to OneDrive and return the item ID."""
        filename = Path(local_path).name
        upload_url = (
            f"{GRAPH_BASE}/drives/{self.drive_id}"
            f"/root:{self.upload_folder}/{filename}:/content"
        )

        with open(local_path, "rb") as f:
            content = f.read()

        upload_headers = {
            "Authorization": headers["Authorization"],
            "Content-Type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }

        resp = httpx.put(
            upload_url,
            content=content,
            headers=upload_headers,
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        item_data = resp.json()
        item_id = item_data["id"]
        logger.info("Uploaded %s to Graph, item_id=%s", filename, item_id)
        return item_id

    def _download_as_pdf(self, item_id: str, out_path: str, headers: dict) -> None:
        """Download a drive item as PDF."""
        url = (
            f"{GRAPH_BASE}/drives/{self.drive_id}"
            f"/items/{item_id}/content?format=pdf"
        )

        resp = httpx.get(
            url,
            headers={"Authorization": headers["Authorization"]},
            timeout=self.timeout_sec,
            follow_redirects=True,
        )
        resp.raise_for_status()

        with open(out_path, "wb") as f:
            f.write(resp.content)
        logger.info("Downloaded PDF to %s (%d bytes)", out_path, len(resp.content))

    def _delete_remote(self, item_id: str, headers: dict) -> None:
        """Delete a remote drive item."""
        url = f"{GRAPH_BASE}/drives/{self.drive_id}/items/{item_id}"
        try:
            resp = httpx.delete(
                url,
                headers={"Authorization": headers["Authorization"]},
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("Cleaned up remote item %s", item_id)
        except Exception as e:
            logger.warning("Failed to cleanup remote item %s: %s", item_id, e)
