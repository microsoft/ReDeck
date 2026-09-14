#!/usr/bin/env python3
"""Run the current deterministic geometry/readability probes without a model call."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redeck_style.evaluation.snapshot import capture_page
from redeck_style.repair import issue_counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--dir", type=Path)
    parser.add_argument("--output-dir", "-o", type=Path, required=True)
    args = parser.parse_args(argv)
    files = sorted(args.dir.glob("*.html")) if args.dir else args.files
    if not files:
        parser.error("Supply HTML files or a nonempty --dir")
    if len({path.stem for path in files}) != len(files):
        parser.error("Input slide names must be unique")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    records = []
    for source in files:
        snapshot = capture_page(source, args.output_dir / f"{source.stem}.png")
        records.append({"source": str(source), "issue_counts": issue_counts(snapshot["validity"]),
                        "status": "needs_visual_and_content_review"})
    (args.output_dir / "spatial_report.json").write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
