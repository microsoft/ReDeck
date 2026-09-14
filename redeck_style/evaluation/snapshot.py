"""Render once and share exact pixels, visible text and spatial diagnostics."""

import hashlib
import json
import re
from pathlib import Path

from .reading import capture_reading

SNAPSHOT_SCHEMA = "1.12"


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def capture_page(source, png_path):
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
    from scripts.evaluate_scene_similarity import _layout_validity, _surface_validity

    source, png_path = Path(source).resolve(), Path(png_path).resolve()
    png_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720}, java_script_enabled=False)
            page.route(re.compile(r"^https?://"), lambda route: route.abort())
            page.goto(source.as_uri(), wait_until="load")
            page.evaluate("document.fonts.ready")
            page.wait_for_function("Array.from(document.images).every(image => image.complete)")
            page.wait_for_timeout(120)
            validity = _layout_validity(page)
            validity.update(_surface_validity(page))
            objects = page.evaluate("""() => Array.from(document.body.querySelectorAll('*')).flatMap((element, index) => {
                const style = getComputedStyle(element);
                const bounds = element.getBoundingClientRect();
                if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0 || !bounds.width || !bounds.height) return [];
                if (element.checkVisibility && !element.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return [];
                const text = Array.from(element.childNodes).filter(node => node.nodeType === Node.TEXT_NODE).map(node => node.textContent.trim()).filter(Boolean).join(' ');
                const image = element.tagName === 'IMG';
                if (!text && !image) return [];
                return [{object_id: element.id || 'dom-' + index, shape_name: element.tagName,
                    object_type: image ? 'picture' : 'text_box', text_content: text,
                    bbox_emu: [bounds.x, bounds.y, bounds.width, bounds.height].map(value => Math.round(value * 9525)),
                    font_sizes_pt: [parseFloat(style.fontSize) * .75], has_image: image,
                    image_path: image ? element.getAttribute('src') || '' : '', z_order: index}];
            })""")
            title = page.evaluate("document.querySelector('h1')?.textContent || document.title || ''")
            reading_view = capture_reading(page)
            for screenshot_attempt in range(1, 4):
                try:
                    page.screenshot(path=str(png_path))
                    break
                except PlaywrightError as error:
                    if "Unable to capture screenshot" not in str(error) or screenshot_attempt == 3:
                        raise
                    page.wait_for_timeout(120)
        finally:
            browser.close()
    snapshot = {"schema_version": SNAPSHOT_SCHEMA, "html_sha256": file_hash(source),
                "png_sha256": file_hash(png_path), "source": str(source), "png": str(png_path),
                "title": title, "objects": objects, "reading_view": reading_view, "validity": validity,
                "screenshot_attempts": screenshot_attempt}
    png_path.with_suffix(".state.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    return snapshot


def load_snapshot(source, png_path, fallback_png=None):
    state_path = Path(png_path).with_suffix(".state.json")
    if state_path.exists() and Path(png_path).exists():
        snapshot = json.loads(state_path.read_text())
        if (snapshot.get("schema_version") == SNAPSHOT_SCHEMA and snapshot["html_sha256"] == file_hash(source)
                and snapshot["png_sha256"] == file_hash(png_path)):
            return snapshot
    return capture_page(source, fallback_png or png_path)
