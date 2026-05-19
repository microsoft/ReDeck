"""Slide Agent Harness - CLI entry point."""

import argparse
import json
import logging
import sys
from pathlib import Path

from .schemas.experiment_config import ExperimentConfig
from .orchestrator.run_manager import RunManager
from .utils.io_utils import read_json


def setup_logging(level: str = "INFO") -> None:
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    """Main entry point for the slide agent harness."""
    parser = argparse.ArgumentParser(
        description="Slide Agent Harness - generate and evaluate slide decks"
    )
    parser.add_argument(
        "--case",
        help="Case ID (directory name under cases/)"
    )
    parser.add_argument(
        "--config", required=True,
        help="Path to experiment config JSON"
    )
    parser.add_argument(
        "--cases-dir", default="cases",
        help="Base directory for cases (default: cases)"
    )
    parser.add_argument(
        "--base-dir", default=".",
        help="Base directory for runs output (default: .)"
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )
    # PDF-specific arguments
    parser.add_argument(
        "--pdf",
        help="Path to PDF paper (auto-creates case directory from PDF)"
    )
    parser.add_argument(
        "--pdf-deck-type", default="conference_talk",
        help="Deck type for PDF mode (default: conference_talk)"
    )
    parser.add_argument(
        "--pdf-audience", default="researchers",
        help="Target audience for PDF mode (default: researchers)"
    )
    parser.add_argument(
        "--pdf-pages", default="8,12",
        help="Page budget min,max for PDF mode (default: 8,12)"
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    logger = logging.getLogger("slide_agent")

    # Handle PDF mode: auto-create case from PDF
    if args.pdf:
        from .modules.case_creator import CaseCreator

        page_budget = [int(x) for x in args.pdf_pages.split(",")]
        creator = CaseCreator()
        case_id = creator.create_from_pdf(
            args.pdf,
            cases_dir=args.cases_dir,
            deck_type=args.pdf_deck_type,
            audience=args.pdf_audience,
            page_budget=page_budget,
        )
        args.case = case_id
        logger.info("Created case from PDF: %s", case_id)

    if not args.case:
        parser.error("Either --case or --pdf is required")

    # Load run config
    config_data = read_json(args.config)
    config = ExperimentConfig.model_validate(config_data)

    logger.info("Loaded config: run_id=%s", config.run_id)

    # Create and run
    runner = RunManager(
        config=config,
        cases_dir=args.cases_dir,
        base_dir=args.base_dir,
    )

    summaries = runner.run(args.case)

    # Print final summary
    print("\n" + "=" * 60)
    print("RUN COMPLETE")
    print("=" * 60)
    for s in summaries:
        status_icon = "ok" if s.status.value == "ok" else "ERR"
        print(
            f"  Turn {s.turn_index}: [{status_icon}] "
            f"{s.total_issues_found} issues "
            f"({s.issues_open} open, {s.issues_resolved} resolved, {s.issues_new} new) "
            f"| {s.repair_units_applied} repairs applied "
            f"| {'CONTINUE' if s.should_continue else 'STOP'}"
        )
    print(f"\nRun directory: {runner.paths.base}")
    print("=" * 60)


if __name__ == "__main__":
    main()
