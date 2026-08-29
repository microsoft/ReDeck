"""Playwright Render Backend — renders HTML slides to PNG/PDF.

Replaces the LibreOffice-based pipeline for HTML-generated slides.
Each slide is a self-contained HTML page rendered via Chromium headless.
"""

import logging
import re
import os
import tempfile
from pathlib import Path

from ..schemas.common import RenderClass, Status
from ..schemas.render_result import RenderMeta, RenderResult
from ..utils.io_utils import ensure_dir

logger = logging.getLogger(__name__)

VIEWPORT_W = 1280
VIEWPORT_H = 720
DEVICE_SCALE_FACTOR = 2  # 2x for crisp 2560×1440 PNGs


class PlaywrightRenderBackend:
    """Renders HTML slides to PNG and assembles into PDF."""

    name = "playwright"

    def __init__(self, dpi: int = 180):
        self.dpi = dpi
        self._browser = None
        self._playwright = None

    def _ensure_browser(self):
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        logger.info("Playwright browser launched for rendering")

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def __del__(self):
        self.close()

    # ------------------------------------------------------------------
    # Core: HTML → PNG
    # ------------------------------------------------------------------

    def render_html_to_png(self, html_content: str, output_path: str | Path) -> bool:
        """Render a single HTML page to PNG.

        Handles local image paths by converting to file:// URLs.
        """
        self._ensure_browser()
        output_path = Path(output_path)

        # Convert bare absolute paths in <img src> to file:// URLs
        html_content = re.sub(
            r'(<img\s[^>]*src=["\'])(/[^"\']+)(["\'])',
            r'\1file://\2\3',
            html_content,
        )

        # Convert relative paths — try cwd first, then project root candidates
        cwd = os.getcwd()
        # Build search roots: cwd, plus common project roots that may contain
        # "cases/" directories with figure assets.
        _search_roots = [cwd]
        # Walk up from cwd looking for a directory that contains "cases/" or "app/"
        _probe = Path(cwd)
        for _ in range(6):
            if (_probe / "cases").is_dir() or (_probe / "app").is_dir():
                if str(_probe) != cwd:
                    _search_roots.append(str(_probe))
                break
            _probe = _probe.parent

        def _resolve(m):
            prefix, path, suffix = m.group(1), m.group(2), m.group(3)
            if path.startswith(('file://', 'http://', 'https://', 'data:', '/')):
                return m.group(0)
            path_parts = Path(path).parts
            if 'generated_assets' in path_parts:
                asset_name = Path(path).name
                asset_candidates = [
                    output_path.parent / path,
                    output_path.parent.parent / 'generated_assets' / asset_name,
                    output_path.parent.parent.parent / 'generated_assets' / asset_name,
                ]
                for candidate in sorted(Path(cwd).glob(f'runs/**/generated_assets/{asset_name}')):
                    asset_candidates.append(candidate)
                for abs_path in asset_candidates:
                    if abs_path.exists():
                        return f'{prefix}file://{abs_path.resolve()}{suffix}'
            for root in _search_roots:
                abs_path = os.path.join(root, path)
                if os.path.exists(abs_path):
                    return f'{prefix}file://{Path(abs_path).resolve()}{suffix}'
            return m.group(0)

        html_content = re.sub(
            r'(<img\s[^>]*src=["\'])([^"\']+)(["\'])',
            _resolve,
            html_content,
        )

        page = None
        try:
            page = self._browser.new_page(
                viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
                device_scale_factor=DEVICE_SCALE_FACTOR,
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(html_content)
                tmp_path = tmp.name
            try:
                page.goto(f"file://{tmp_path}", wait_until="networkidle")
                page.wait_for_timeout(300)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output_path), full_page=False)
            finally:
                os.unlink(tmp_path)
            page.close()
            return True
        except Exception as e:
            logger.error("Playwright render failed: %s", e)
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            return False

    def render_html_file_to_png(self, html_path: str | Path, output_path: str | Path) -> bool:
        """Render an HTML file to PNG."""
        html_content = Path(html_path).read_text(encoding="utf-8")
        return self.render_html_to_png(html_content, output_path)

    # ------------------------------------------------------------------
    # Batch: directory of HTML files → PNGs + PDF
    # ------------------------------------------------------------------

    def render_html_dir_to_pngs(
        self, html_dir: str | Path, out_dir: str | Path
    ) -> RenderResult:
        """Render all slide_XX.html files in a directory to PNGs."""
        html_dir = Path(html_dir)
        out_dir = Path(out_dir)
        ensure_dir(str(out_dir))

        html_files = sorted(html_dir.glob("slide_*.html"))
        if not html_files:
            return RenderResult(
                backend_name=self.name,
                status=Status.ERROR,
                error_message=f"No slide_*.html files in {html_dir}",
            )

        png_paths = []
        warnings = []
        for html_file in html_files:
            png_name = html_file.stem + ".png"
            png_path = out_dir / png_name
            ok = self.render_html_file_to_png(html_file, png_path)
            if ok:
                png_paths.append(str(png_path))
            else:
                warnings.append(f"Failed to render {html_file.name}")

        return RenderResult(
            backend_name=self.name,
            status=Status.OK if png_paths else Status.ERROR,
            png_paths=png_paths,
            warnings=warnings,
            render_meta=RenderMeta(
                backend_name=self.name,
                render_class=RenderClass.APPROX_RENDER,
                office_family="playwright",
            ),
        )

    def assemble_pngs_to_pdf(
        self, png_paths: list[str], output_pdf: str | Path
    ) -> bool:
        """Assemble PNG images into a PDF using Pillow."""
        try:
            from PIL import Image

            output_pdf = Path(output_pdf)
            output_pdf.parent.mkdir(parents=True, exist_ok=True)

            images = []
            for p in png_paths:
                img = Image.open(p).convert("RGB")
                images.append(img)

            if not images:
                return False

            images[0].save(
                str(output_pdf),
                save_all=True,
                append_images=images[1:],
                resolution=self.dpi,
            )
            logger.info("Assembled %d slides into %s", len(images), output_pdf)
            return True
        except Exception as e:
            logger.error("PDF assembly failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # RenderBackend protocol (for RenderManager compatibility)
    # ------------------------------------------------------------------

    def render_pptx_to_pngs(self, pptx_path: str, out_dir: str) -> RenderResult:
        """Not applicable for HTML backend — raises informative error."""
        return RenderResult(
            backend_name=self.name,
            status=Status.ERROR,
            error_message="PlaywrightBackend does not render PPTX files. Use render_html_dir_to_pngs().",
        )

    # ------------------------------------------------------------------
    # DOM extraction (for spatial state / geom checks)
    # ------------------------------------------------------------------

    def extract_dom_elements(self, html_content: str) -> list[dict]:
        """Extract visible DOM elements with bounding boxes from rendered HTML.

        Returns list of dicts with keys:
          - tag, text, bbox (x, y, width, height in px), classes, id
        """
        self._ensure_browser()

        html_content = re.sub(
            r'(<img\s[^>]*src=["\'])(/[^"\']+)(["\'])',
            r'\1file://\2\3',
            html_content,
        )

        page = None
        try:
            page = self._browser.new_page(
                viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
                device_scale_factor=DEVICE_SCALE_FACTOR,
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(html_content)
                tmp_path = tmp.name
            try:
                page.goto(f"file://{tmp_path}", wait_until="networkidle")
                page.wait_for_timeout(200)

                # Query all visible elements with text or images
                elements = page.evaluate("""() => {
                    const results = [];
                    const walker = document.createTreeWalker(
                        document.body,
                        NodeFilter.SHOW_ELEMENT,
                        null
                    );
                    let node;
                    while (node = walker.nextNode()) {
                        const rect = node.getBoundingClientRect();
                        if (rect.width < 5 || rect.height < 5) continue;
                        const tag = node.tagName.toLowerCase();
                        // Skip structural containers
                        if (['html', 'body', 'head', 'style', 'script', 'meta', 'link'].includes(tag)) continue;

                        const text = node.innerText ? node.innerText.substring(0, 500) : '';
                        const isImg = tag === 'img';
                        const hasDirectText = Array.from(node.childNodes)
                            .some(n => n.nodeType === 3 && n.textContent.trim().length > 0);

                        if (!text && !isImg && !hasDirectText) continue;

                        results.push({
                            tag: tag,
                            text: text,
                            bbox: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
                            classes: node.className || '',
                            id: node.id || '',
                            isImg: isImg,
                            src: isImg ? node.src : '',
                            fontSize: window.getComputedStyle(node).fontSize,
                        });
                    }
                    return results;
                }""")
            finally:
                os.unlink(tmp_path)
            page.close()
            return elements
        except Exception as e:
            logger.error("DOM extraction failed: %s", e)
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            return []
