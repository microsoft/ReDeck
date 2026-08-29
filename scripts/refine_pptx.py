#!/usr/bin/env python3
"""CLI entry point for PPTX spatial refinement."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.backends.python_pptx.refiner.font_metrics import FontMetrics, EMU_PER_INCH
from app.backends.python_pptx.refiner.spatial_analyzer import PptxSpatialAnalyzer, SpatialReport


def _print_report(report: SpatialReport, pptx_path: Path) -> None:
    slide_w_in = report.slide_width_emu / EMU_PER_INCH
    slide_h_in = report.slide_height_emu / EMU_PER_INCH
    print(f"\n=== Spatial Analysis Report: {pptx_path.name} ===")
    print(f"Slide dimensions: {slide_w_in:.2f} x {slide_h_in:.2f} in")
    print(f"Slides analyzed:  {len(report.extractions)}")
    print(f"Overflows found:  {len(report.overflows)}")
    print(f"Overlaps found:   {len(report.overlaps)}")

    if report.overflows:
        print("\n--- Overflows ---")
        for ov in report.overflows:
            snippet = ov.text_snippet[:60].replace("\n", " ")
            print(
                f"  Slide {ov.slide_index + 1} | {ov.shape_name!r} | "
                f"overflow_w={ov.overflow.overflow_width_emu:.0f} "
                f"overflow_h={ov.overflow.overflow_height_emu:.0f} emu | "
                f"text: {snippet!r}"
            )

    if report.overlaps:
        print("\n--- Overlaps ---")
        for ol in report.overlaps:
            print(
                f"  Slide {ol.slide_index + 1} | {ol.shape_a_name!r} ∩ {ol.shape_b_name!r} | "
                f"area={ol.overlap_area_sq_in:.3f} sq-in"
            )

    if not report.overflows and not report.overlaps:
        print("\nNo spatial issues detected.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PPTX spatial refiner — analyze overflows/overlaps and optionally fix them."
    )
    parser.add_argument("input", help="Path to input PPTX file")
    parser.add_argument("-o", "--output", help="Output PPTX path (default: <input>_refined.pptx)")
    parser.add_argument("--max-turns", type=int, default=5, help="Max refinement turns (default: 5)")
    parser.add_argument("--model", help="LLM model to use for fix planning")
    parser.add_argument("--analyze-only", action="store_true", help="Only analyze; do not apply fixes (no LLM needed)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if args.analyze_only:
        fm = FontMetrics()
        analyzer = PptxSpatialAnalyzer(fm)
        report = analyzer.analyze(input_path)
        _print_report(report, input_path)
        return

    # Full refinement mode
    output_path = Path(args.output) if args.output else input_path.with_stem(input_path.stem + "_refined")
    output_dir = output_path.parent / f".refine_{input_path.stem}"

    from app.orchestrator.refine_manager import RefineManager
    manager = RefineManager(
        pptx_path=input_path,
        output_dir=output_dir,
        max_turns=args.max_turns,
        model=args.model,
    )
    summary = manager.run()

    # Copy final output
    working_pptx = output_dir / input_path.name
    if working_pptx.exists():
        shutil.copy2(working_pptx, output_path)

    print(f"\n=== Refinement Summary ===")
    print(f"Input:          {summary.input_path}")
    print(f"Output:         {output_path}")
    print(f"Turns run:      {summary.total_turns}")
    print(f"Initial issues: {summary.initial_issues}")
    print(f"Final issues:   {summary.final_issues}")
    print(f"Converged:      {summary.converged}")
    for tr in summary.turns:
        print(
            f"  Turn {tr.turn}: issues={tr.issue_count} "
            f"(overflows={tr.overflow_count}, overlaps={tr.overlap_count}) "
            f"ops={tr.ops_applied} time={tr.timing_sec:.1f}s"
        )
    print()


if __name__ == "__main__":
    main()
