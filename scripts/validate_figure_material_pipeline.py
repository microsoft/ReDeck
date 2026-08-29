#!/usr/bin/env python3
"""Run a focused real-model validation of PDF figure use in HTML slides."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.backends.python_pptx.html_codegen_compiler import HtmlCodeGenCompiler
from app.llm_client import LLMClient
from app.modules.deck_planner import DeckPlanner
from app.modules.source_indexer import SourceIndexer
from app.modules.source_store import build_source_store
from app.modules.source_store.bundle_builder import SlideSourceBundleBuilder
from app.schemas.blueprint import DeckBlueprint


def _load_planner_blueprint(log_path: Path) -> DeckBlueprint:
    calls = [json.loads(line) for line in log_path.read_text().splitlines()]
    planner_calls = [
        call for call in calls
        if call.get("module") == "deck_planner"
        and call.get("status") == "ok"
        and call.get("response_text")
    ]
    if not planner_calls:
        raise RuntimeError(f"No successful deck_planner response in {log_path}")
    return DeckBlueprint.model_validate_json(planner_calls[-1]["response_text"])


def _build_bundles(blueprint: DeckBlueprint, source_store) -> None:
    deck_plan = []
    for slide in blueprint.slides:
        deck_plan.append({
            "slide_id": slide.slide_id,
            "slide_title": slide.primary_proposition,
            "source_doc_block_ids": slide.source_doc_block_ids or [
                ref for ref in slide.linked_evidence_ids if ref.startswith("DB")
            ],
            "asset_ids": slide.asset_ids or [
                ref for ref in slide.linked_evidence_ids if ref.startswith("A")
            ],
            "table_ids": slide.table_ids or [
                ref for ref in slide.linked_evidence_ids if ref.startswith("T")
            ],
        })
    bundles = SlideSourceBundleBuilder().build(
        deck_plan,
        source_store.doc_block_plan,
        source_store.atomic_blocks,
        source_store.assets,
        source_store.table_data,
    )
    source_store.bundles = {bundle.slide_id: bundle for bundle in bundles}


def _path_from_browser_url(url: str) -> Path | None:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).resolve()
    if not parsed.scheme:
        return Path(unquote(parsed.path)).resolve()
    return None


def _image_spread(path: Path) -> float:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        return round(sum(ImageStat.Stat(rgb).stddev) / 3, 3)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_outputs(
    blueprint: DeckBlueprint,
    source_store,
    output_dir: Path,
    pptx_path: Path,
) -> dict:
    pptx_media_hashes = set()
    with zipfile.ZipFile(pptx_path) as archive:
        for name in archive.namelist():
            if name.startswith("ppt/media/"):
                pptx_media_hashes.add(hashlib.sha256(archive.read(name)).hexdigest())

    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for slide in blueprint.slides:
            asset = source_store.get_asset(slide.assigned_figure_id)
            expected = Path(asset.image_path).resolve() if asset else None
            html_path = output_dir / "slide_code" / f"slide_{slide.slide_id:02d}.html"
            render_path = output_dir / "html_renders" / f"slide_{slide.slide_id:02d}.png"
            crop_path = output_dir / "figure_crops" / f"slide_{slide.slide_id:02d}.png"
            crop_path.parent.mkdir(parents=True, exist_ok=True)

            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.wait_for_timeout(300)
            image_data = page.locator("img").evaluate_all(
                """imgs => imgs.map((img, index) => {
                    const box = img.getBoundingClientRect();
                    const style = getComputedStyle(img);
                    return {
                        index,
                        currentSrc: img.currentSrc,
                        naturalWidth: img.naturalWidth,
                        naturalHeight: img.naturalHeight,
                        box: {x: box.x, y: box.y, width: box.width, height: box.height},
                        display: style.display,
                        visibility: style.visibility,
                        opacity: Number(style.opacity),
                    };
                })"""
            )
            matched = None
            for image in image_data:
                current_path = _path_from_browser_url(image["currentSrc"])
                if expected and current_path == expected:
                    matched = image
                    page.locator("img").nth(image["index"]).screenshot(path=str(crop_path))
                    break

            box = (matched or {}).get("box", {})
            visible = bool(
                matched
                and matched["naturalWidth"] > 0
                and matched["naturalHeight"] > 0
                and box.get("width", 0) >= 100
                and box.get("height", 0) >= 80
                and box.get("x", 1280) < 1280
                and box.get("y", 720) < 720
                and box.get("x", 0) + box.get("width", 0) > 0
                and box.get("y", 0) + box.get("height", 0) > 0
                and matched["display"] != "none"
                and matched["visibility"] != "hidden"
                and matched["opacity"] > 0
            )
            render_hash = _sha256(render_path) if render_path.exists() else ""
            render_in_pptx = render_hash in pptx_media_hashes
            passed = bool(
                expected
                and expected.is_file()
                and html_path.is_file()
                and render_path.is_file()
                and visible
                and _image_spread(render_path) > 5
                and render_in_pptx
            )
            results.append({
                "slide_id": slide.slide_id,
                "assigned_figure_id": slide.assigned_figure_id,
                "expected_source_image": str(expected) if expected else "",
                "html_path": str(html_path),
                "render_path": str(render_path),
                "figure_crop_path": str(crop_path) if crop_path.exists() else "",
                "img_elements": image_data,
                "matched_source_img": matched,
                "source_visible_in_browser": visible,
                "render_pixel_spread": _image_spread(render_path),
                "render_embedded_in_pptx": render_in_pptx,
                "passed": passed,
            })
            page.close()
        browser.close()

    return {
        "passed": all(result["passed"] for result in results),
        "slides": results,
        "pptx_path": str(pptx_path),
        "pptx_media_count": len(pptx_media_hashes),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True, type=Path)
    parser.add_argument("--planner-log", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--slides", required=True, help="Comma-separated slide IDs")
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()

    selected_ids = {int(value) for value in args.slides.split(",")}
    args.output_dir.mkdir(parents=True, exist_ok=True)

    blueprint = _load_planner_blueprint(args.planner_log)
    evidence = SourceIndexer().index(args.case_dir)
    source_store = build_source_store(args.case_dir, llm=None)
    DeckPlanner._assign_figures(blueprint, evidence, source_store)
    _build_bundles(blueprint, source_store)

    selected_slides = [
        slide for slide in blueprint.slides if slide.slide_id in selected_ids
    ]
    if {slide.slide_id for slide in selected_slides} != selected_ids:
        raise RuntimeError("One or more requested slides were absent from blueprint")
    for slide in selected_slides:
        if not slide.assigned_figure_id:
            raise RuntimeError(f"Slide {slide.slide_id} has no usable assigned figure")
    blueprint.slides = selected_slides
    blueprint.total_slides = len(selected_slides)
    (args.output_dir / "normalized_blueprint.json").write_text(
        blueprint.model_dump_json(indent=2)
    )

    llm = LLMClient(
        default_model=args.model,
        log_path=args.output_dir / "llm_calls.jsonl",
    )
    compiler = HtmlCodeGenCompiler(llm, model=args.model)
    pptx_path = args.output_dir / "deck.pptx"
    manifest = compiler.compile_deck(
        blueprint=blueprint,
        evidence=evidence,
        case_dir=args.case_dir,
        output_path=pptx_path,
        code_dir=args.output_dir / "slide_code",
        source_store=source_store,
        task_brief=(args.case_dir / "task_brief.md").read_text(),
    )
    (args.output_dir / "compile_manifest.json").write_text(
        json.dumps(manifest, indent=2)
    )

    validation = _validate_outputs(
        blueprint, source_store, args.output_dir, pptx_path,
    )
    (args.output_dir / "validation.json").write_text(
        json.dumps(validation, indent=2)
    )
    print(json.dumps(validation, indent=2))
    return 0 if validation["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
