#!/usr/bin/env python3
"""Review existing v2 pages using the original source-grounded C/D/E probes."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redeck_style.evaluation.coordinator import add_judge_arguments, judge_options, review_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api", choices=("local", "trapi", "anthropic"), default="local")
    parser.add_argument("--probes", help="Comma-separated focused checks; partial coverage is never a full pass")
    parser.add_argument("--slides", help="Comma-separated original slide IDs")
    add_judge_arguments(parser)
    args = parser.parse_args(argv)
    options = judge_options(args)
    if args.probes:
        options["probes"] = [value.strip() for value in args.probes.split(",")]
    if args.slides:
        options["slides"] = [int(value) for value in args.slides.split(",")]
    report = review_run(args.run, args.output, options)
    print(json.dumps({key: report.get(key) for key in ("status", "coverage_complete", "model_calls", "report_path")}, indent=2))
    if any(record["status"] == "error" for record in report["probes"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
