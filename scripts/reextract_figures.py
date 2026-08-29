#!/usr/bin/env python3
"""Re-extract figures/tables for existing cases using YOLO11.

Clears old figures/tables/screenshots and re-runs FigureExtractor.
Does NOT touch task_brief.md, evidence.json, or other case files.

Usage:
    python3.11 scripts/reextract_figures.py --cases db_002 db_003 db_029 db_031 db_112
"""
import sys, os, shutil, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from app.modules.figure_extractor import FigureExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("reextract")

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"


def reextract(case_id: str):
    source_dir = CASES_DIR / case_id / "source_pack"
    pdf_path = source_dir / "paper.pdf"
    if not pdf_path.exists():
        logger.warning("No paper.pdf for %s, skipping", case_id)
        return

    # Clear old extraction outputs
    for subdir in ("figures", "tables", "screenshots"):
        d = source_dir / subdir
        if d.exists():
            n = len(list(d.iterdir()))
            shutil.rmtree(d)
            logger.info("Cleared %s/%s (%d files)", case_id, subdir, n)

    # Re-extract
    extractor = FigureExtractor(source_dir)
    figures, tables, screenshots = extractor.extract(pdf_path)
    logger.info(
        "%s: %d figures, %d tables, %d screenshots",
        case_id, len(figures), len(tables), len(screenshots),
    )


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", nargs="+", required=True)
    args = parser.parse_args()

    for case_id in args.cases:
        print(f"\n{'='*60}")
        print(f"Re-extracting: {case_id}")
        print(f"{'='*60}")
        reextract(case_id)

    print("\nDone. Now run the pipeline to regenerate slides.")


if __name__ == "__main__":
    main()
