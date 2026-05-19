#!/usr/bin/env python3
"""
ReDeck Spatial — the spatial oracle CLI.

This is the standalone CLI for ReDeck's Playwright-based spatial detection engine.
The same engine (`extract_html_slide_state`) powers:
  - Judge Layer 1 (DeterministicGeomChecks in redeck_judge.py)
  - verify_layout tool inside the repair agent (redeck_repair.py)

Use this script for fast, deterministic spatial checks without LLM involvement.

Detects: overlap, overflow, out-of-bounds, clipped content, occlusion, low contrast.

Usage:
    python scripts/redeck_spatial.py slide_01.html slide_02.html
    python scripts/redeck_spatial.py --dir ./slides/
    python scripts/redeck_spatial.py slide.html --json
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.redeck.html_spatial_state import (
    extract_html_slide_state,
    format_html_compact_state,
)


def count_issues(state):
    """Count hard spatial defects."""
    return (
        len(state.overlap_pairs)
        + len(state.overflow_blocks)
        + len(state.oob_blocks)
        + len(state.clipped_blocks)
        + len(state.occlusion_pairs)
    )


def state_to_dict(state):
    """Convert spatial state to JSON-serializable dict."""
    issues = []
    for a_id, b_id, area in state.overlap_pairs:
        a = next((b for b in state.blocks if b.block_id == a_id), None)
        b = next((b for b in state.blocks if b.block_id == b_id), None)
        issues.append({
            "type": "overlap",
            "elements": [a_id, b_id],
            "area_sq_in": round(area, 3),
            "a_bbox_px": list(a.bbox_px) if a else None,
            "b_bbox_px": list(b.bbox_px) if b else None,
        })
    for bid in state.overflow_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        issues.append({
            "type": "overflow",
            "element": bid,
            "overflow_bottom_px": blk.overflow_bottom_px if blk else 0,
            "overflow_right_px": blk.overflow_right_px if blk else 0,
        })
    for bid in state.oob_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        issues.append({
            "type": "out_of_bounds",
            "element": bid,
            "bbox_px": list(blk.bbox_px) if blk else None,
        })
    for bid in state.clipped_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        issues.append({
            "type": "clipped",
            "element": bid,
            "clipped_bottom_px": blk.clipped_bottom_px if blk else 0,
        })
    for front, back in state.occlusion_pairs:
        issues.append({
            "type": "occlusion",
            "front": front,
            "back": back,
        })
    for bid in state.low_contrast_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        issues.append({
            "type": "low_contrast",
            "element": bid,
            "contrast_ratio": round(blk.contrast_ratio, 2) if blk else 0,
            "fg": blk.fg_color if blk else "",
            "bg": blk.bg_color if blk else "",
        })
    return {
        "slide_id": state.slide_id,
        "n_elements": len(state.blocks),
        "n_issues": len(issues),
        "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ReDeck Spatial — deterministic spatial oracle for HTML slides"
    )
    parser.add_argument("files", nargs="*", help="HTML slide files to check")
    parser.add_argument("--dir", help="Directory of slide_*.html files")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    paths = []
    if args.dir:
        paths.extend(sorted(Path(args.dir).glob("slide_*.html")))
    for f in (args.files or []):
        p = Path(f)
        if p.is_file():
            paths.append(p)
        else:
            print(f"Warning: {f} not found", file=sys.stderr)

    if not paths:
        parser.error("No HTML files specified. Use positional args or --dir")

    all_results = []
    total_issues = 0

    for hp in paths:
        # Extract slide_id from filename if possible
        try:
            sid = int(hp.stem.split("_")[1])
        except (IndexError, ValueError):
            sid = 1

        html = hp.read_text()
        state = extract_html_slide_state(sid, html)
        n = count_issues(state)
        total_issues += n

        if args.json:
            all_results.append(state_to_dict(state))
        else:
            if n == 0:
                print(f"✅ {hp.name}: no issues")
            else:
                print(f"❌ {hp.name}: {n} issues")
                print(format_html_compact_state(state))
                print()

    if args.json:
        print(json.dumps(all_results, indent=2))

    sys.exit(1 if total_issues > 0 else 0)


if __name__ == "__main__":
    main()
