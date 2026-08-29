#!/usr/bin/env python3
"""
ReDeck Judge — Full multi-dimensional evaluation for HTML slides.

Runs all 6 evaluation layers:
1. DeterministicGeomChecks (spatial: overlap, OOB, empty_slide)
2. VisualJudge (visual quality: density, alignment, contrast — uses screenshots)
3. NarrativeJudge (A family: logical flow, title quality)
4. CompletenessJudge (C family: missing points, missing data)
5. CorrectnessJudge (D family: factual errors, wrong numbers)
6. FidelityJudge (E family: fabrication, unfaithful compression)

Usage:
    # Spatial checks only (no LLM, fast)
    python scripts/redeck_judge.py --dir ./slides/ --spatial-only

    # Full evaluation (requires LLM + source paper)
    python scripts/redeck_judge.py --dir ./slides/ --paper paper.md

    # Full evaluation with JSON output
    python scripts/redeck_judge.py --dir ./slides/ --paper paper.md --json
"""
import sys
import json
import argparse
import logging
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm_client import LLMClient
from app.modules.redeck.html_spatial_state import (
    extract_html_slide_state,
    format_html_compact_state,
)
from app.modules.evaluators.geom_checks import DeterministicGeomChecks
from app.schemas.issue import Issue
from app.schemas.extraction import SlideExtraction, ExtractedObject
from app.schemas.issue_types import SlideDimensions

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _extract_from_html(slide_codes: dict[int, str]) -> list[SlideExtraction]:
    """Extract slide structure from HTML codes for geom checks.

    Mirrors RunManager._extract_from_html() — builds SlideExtraction objects
    from Playwright DOM bounding boxes.
    """
    import re
    from app.utils.html_text import extract_title_and_body

    pw_states = {}
    for sid, html in sorted(slide_codes.items()):
        try:
            state = extract_html_slide_state(sid, html)
            pw_states[sid] = state
        except Exception as e:
            logger.debug("Playwright extraction failed for slide %d: %s", sid, e)

    extractions = []
    for sid, html in sorted(slide_codes.items()):
        title, body = extract_title_and_body(html)
        text_only = f"{title} {body}".strip()
        img_count = len(re.findall(r'<img\b', html, re.IGNORECASE))

        objects = []
        pw_state = pw_states.get(sid)

        if pw_state and hasattr(pw_state, 'blocks') and pw_state.blocks:
            emu = SlideDimensions.PX_TO_EMU
            for blk in pw_state.blocks:
                obj_type = "text_box"
                has_img = False
                if blk.shape_type in ("picture", "image"):
                    obj_type = "picture"
                    has_img = True
                elif blk.shape_type in ("chart", "table"):
                    obj_type = blk.shape_type

                objects.append(ExtractedObject(
                    object_id=blk.block_id,
                    shape_name=blk.var_name or blk.block_id,
                    object_type=obj_type,
                    bbox_emu=[
                        int(blk.x * emu), int(blk.y * emu),
                        int(blk.w * emu), int(blk.h * emu),
                    ],
                    text_content=" ".join(blk.text_lines) if blk.text_lines else '',
                    font_sizes_pt=[18.0],
                    has_image=has_img,
                ))

        extractions.append(SlideExtraction(
            slide_number=sid,
            title=title,
            body_text=body,
            objects=objects,
            total_text_length=len(text_only),
            total_shapes=len(objects),
            image_count=img_count,
        ))

    return extractions


def _render_slides(slide_codes: dict[int, str]) -> tuple[list[str], dict[int, str]]:
    """Render HTML slides to PNGs and base64 for vision judges."""
    from playwright.sync_api import sync_playwright
    import tempfile, os

    png_dir = Path(tempfile.mkdtemp(prefix="redeck_judge_"))
    png_paths = []
    b64_map = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        for sid, html in sorted(slide_codes.items()):
            # Write temp HTML
            tmp_html = png_dir / f"slide_{sid:02d}.html"
            tmp_html.write_text(html)
            page.goto(f"file://{tmp_html.resolve()}")
            page.wait_for_timeout(500)
            png_path = str(png_dir / f"slide_{sid:02d}.png")
            page.screenshot(path=png_path)
            png_paths.append(png_path)
            with open(png_path, "rb") as f:
                b64_map[sid] = base64.b64encode(f.read()).decode()
        browser.close()

    return png_paths, b64_map


def run_spatial_only(slide_codes: dict[int, str]) -> list[dict]:
    """Run spatial checks only (no LLM). Returns issue dicts."""
    all_issues = []
    for sid, html in sorted(slide_codes.items()):
        state = extract_html_slide_state(sid, html)
        n = (len(state.overlap_pairs) + len(state.overflow_blocks)
             + len(state.oob_blocks) + len(state.clipped_blocks)
             + len(state.occlusion_pairs))
        if n > 0:
            report = format_html_compact_state(state)
            all_issues.append({
                "slide_id": sid,
                "n_issues": n,
                "report": report,
                "overlaps": len(state.overlap_pairs),
                "overflows": len(state.overflow_blocks),
                "oob": len(state.oob_blocks),
                "clipped": len(state.clipped_blocks),
                "occlusions": len(state.occlusion_pairs),
            })
    return all_issues


def run_full_evaluation(
    slide_codes: dict[int, str],
    paper_text: str = "",
    model: str = "gpt-5.4",
) -> list[Issue]:
    """Run full evaluation pipeline (spatial + all LLM judges)."""
    from app.orchestrator.eval_router import EvalRouter
    from app.schemas.experiment_config import ExperimentConfig, EvalMode
    from app.schemas.evidence import EvidenceState

    llm = LLMClient()

    config = ExperimentConfig(
        run_id="redeck_judge_standalone",
        use_html_codegen=True,
        eval_mode=EvalMode(
            enabled=True,
            use_judge_agent=False,  # Simpler for standalone
            use_probe_planner=False,
        ),
    )

    router = EvalRouter(llm, config)

    # Extract slide structure
    extractions = _extract_from_html(slide_codes)

    # Render screenshots for visual judge
    png_paths, _ = _render_slides(slide_codes)

    # Build task brief from paper
    task_brief = "Generate a professional academic presentation from the paper."
    source_summary = paper_text[:8000] if paper_text else ""

    issues = router.evaluate(
        extractions=extractions,
        png_paths=png_paths,
        task_brief=task_brief,
        source_summary=source_summary,
        slide_codes=slide_codes,
    )

    return issues


def main():
    parser = argparse.ArgumentParser(
        description="ReDeck Judge — multi-dimensional evaluation for HTML slides"
    )
    parser.add_argument("files", nargs="*", help="HTML slide files")
    parser.add_argument("--dir", help="Directory of slide_*.html files")
    parser.add_argument("--paper", help="Source paper markdown file (for content judges)")
    parser.add_argument("--spatial-only", action="store_true",
                        help="Run spatial checks only (no LLM, fast)")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--output", "-o", help="Output file for issues")
    args = parser.parse_args()

    # Collect input files
    paths = []
    if args.dir:
        paths.extend(sorted(Path(args.dir).glob("slide_*.html")))
    for f in (args.files or []):
        p = Path(f)
        if p.is_file():
            paths.append(p)

    if not paths:
        parser.error("No HTML files. Use positional args or --dir")

    # Build slide_codes dict
    slide_codes = {}
    for hp in paths:
        try:
            sid = int(hp.stem.split("_")[1])
        except (IndexError, ValueError):
            sid = len(slide_codes) + 1
        slide_codes[sid] = hp.read_text()

    if args.spatial_only:
        results = run_spatial_only(slide_codes)
        total = sum(r["n_issues"] for r in results)

        if args.json:
            print(json.dumps(results, indent=2))
        else:
            for r in results:
                print(f"❌ slide_{r['slide_id']:02d}: {r['n_issues']} spatial issues")
                print(r["report"])
                print()
            clean = len(slide_codes) - len(results)
            if clean > 0:
                print(f"✅ {clean} slide(s) clean")
            print(f"\nTotal: {total} spatial issues across {len(slide_codes)} slides")

        if args.output:
            Path(args.output).write_text(json.dumps(results, indent=2))
        sys.exit(1 if total > 0 else 0)

    else:
        # Full evaluation
        paper_text = ""
        if args.paper:
            paper_text = Path(args.paper).read_text()

        issues = run_full_evaluation(slide_codes, paper_text, args.model)

        if args.json:
            output = [i.model_dump(mode="json") for i in issues]
            print(json.dumps(output, indent=2))
        else:
            # Group by slide
            by_slide: dict[int, list[Issue]] = {}
            for iss in issues:
                for sid in iss.affected_slides:
                    by_slide.setdefault(sid, []).append(iss)

            for sid in sorted(by_slide):
                iss_list = by_slide[sid]
                print(f"\n{'='*60}")
                print(f"Slide {sid}: {len(iss_list)} issues")
                print(f"{'='*60}")
                for iss in iss_list:
                    severity = iss.severity.value if hasattr(iss.severity, 'value') else str(iss.severity)
                    desc = iss.evidence.description[:120] if iss.evidence else ""
                    print(f"  [{severity}] {iss.rubric_id} {iss.issue_type}")
                    if desc:
                        print(f"    {desc}")
                    if iss.planned_fix:
                        print(f"    Fix: {iss.planned_fix[:100]}")

            clean_slides = set(slide_codes.keys()) - set(by_slide.keys())
            if clean_slides:
                print(f"\n✅ {len(clean_slides)} slide(s) clean: {sorted(clean_slides)}")
            print(f"\nTotal: {len(issues)} issues across {len(by_slide)} slides")

        if args.output:
            output = [i.model_dump(mode="json") for i in issues]
            Path(args.output).write_text(json.dumps(output, indent=2))

        sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
