#!/usr/bin/env python3.11
"""Run the multi-turn PDF→PPT pipeline with codegen.

Usage:
    # Single paper
    python3.11 scripts/run_pdf_pipeline.py --configs html_codegen --html-codegen --case db_002 --max-turns 4

    # All papers in papers/ directory, in parallel
    python3.11 scripts/run_pdf_pipeline.py --configs html_codegen --html-codegen --papers-dir papers --max-turns 4 --parallel 4

API authentication:
    AzureCliCredential is used by default with the Azure OpenAI endpoint. Run
    `az login` first. Override with AZURE_OPENAI_ENDPOINT when needed.
    Set REDECK_AZURE_AUTH=api_key to use API key auth explicitly.
    Alternatively, set OPENAI_BASE_URL + OPENAI_API_KEY for OpenAI-compatible APIs.
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Load .env file (same as test_repair_only.py)
env_path = project_root / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

from app.schemas.experiment_config import ExperimentConfig
from app.orchestrator.run_manager import RunManager
from app.modules.case_creator import CaseCreator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_pdf_pipeline")

# --------------------------------------------------------------------------
# Configuration templates
# --------------------------------------------------------------------------

MODEL = "gpt-5.4"

CONFIGS = {
    "default": {
        "ablation_tags": ["plan_full", "eval_family_slide", "layout_explicit", "repair_typed"],
        "eval_mode": {"enabled": True, "split_level": "family_plus_slide"},
        "max_turns": 5,
        "layout_strategy": "template",
    },
    "codegen": {
        "ablation_tags": ["codegen", "eval_family_slide", "layout_explicit"],
        "eval_mode": {"enabled": True, "split_level": "family_plus_slide"},
        "max_turns": 1,  # T0 only, no repair
        "layout_strategy": "template",
    },
    "codegen_repair": {
        "ablation_tags": ["codegen", "eval_family_slide", "layout_freeform", "repair_enabled"],
        "eval_mode": {"enabled": True, "split_level": "family_plus_slide"},
        "max_turns": 5,
        "layout_strategy": "template",
    },
    "codegen_no_layout": {
        "ablation_tags": ["codegen", "eval_family_slide", "layout_heuristic"],
        "eval_mode": {"enabled": True, "split_level": "family_plus_slide"},
        "max_turns": 1,
        "layout_strategy": "none",
    },
    "html_codegen": {
        "ablation_tags": ["html_codegen", "eval_family_slide", "layout_explicit"],
        "eval_mode": {"enabled": True, "split_level": "family_plus_slide"},
        "max_turns": 5,
        "use_html_codegen": True,
        "layout_strategy": "template",
    },
    "html_codegen_no_layout": {
        "ablation_tags": ["html_codegen", "eval_family_slide", "layout_heuristic"],
        "eval_mode": {"enabled": True, "split_level": "family_plus_slide"},
        "max_turns": 1,
        "use_html_codegen": True,
        "layout_strategy": "none",
    },
}


def build_config(
    config_name: str, case_id: str, max_turns: int,
    repair_strategy: str | None = None, run_suffix: str = "",
    codegen_prompt: str | None = None, theme_id: str | None = None,
    model: str | None = None, codegen_model: str | None = None,
    repair_model: str | None = None, prebuilt_blueprint_path: str | None = None,
    prebuilt_turn0_dir: str | None = None,
    style_pattern: str | None = None,
) -> ExperimentConfig:
    """Build an ExperimentConfig from a named template."""
    template = CONFIGS[config_name]
    suffix = f"_{run_suffix}" if run_suffix else ""
    run_id = f"{case_id}_{config_name}_{max_turns}turns{suffix}"
    models = {"default": model or MODEL}
    if codegen_model:
        models["slide_codegen"] = codegen_model
    if repair_model:
        models["slide_repair"] = repair_model
    config_dict = {
        "run_id": run_id,
        "ablation_tags": template["ablation_tags"],
        "models": models,
        "eval_mode": template["eval_mode"],
        "render_mode": {
            "fast_backend": "linux_lo_pdf",
            "reference_backend": "graph_pdf",
        },
        "max_turns": max_turns,
        "use_html_codegen": template.get("use_html_codegen", False),
        "repair_strategy": repair_strategy or template.get("repair_strategy", "redeck"),
        "layout_strategy": template.get("layout_strategy", "template"),
    }
    if codegen_prompt:
        config_dict["codegen_prompt"] = codegen_prompt
    if theme_id:
        config_dict["theme_id"] = theme_id
    if prebuilt_blueprint_path:
        config_dict["prebuilt_blueprint_path"] = prebuilt_blueprint_path
    if prebuilt_turn0_dir:
        config_dict["prebuilt_turn0_dir"] = prebuilt_turn0_dir
    if style_pattern:
        config_dict["style_pattern"] = style_pattern
    return ExperimentConfig.model_validate(config_dict)


def ensure_case_from_pdf(
    pdf_path: str,
    cases_dir: str = "cases",
    *,
    deck_type: str = "conference_talk",
    audience: str = "researchers",
    source_kind: str = "paper",
    page_budget: list[int] | None = None,
) -> str:
    """Create a case directory from a PDF file if it doesn't already exist."""
    pdf_path = Path(pdf_path)
    creator = CaseCreator()
    case_id = creator._generate_case_id(pdf_path)
    case_dir = Path(cases_dir) / case_id

    if case_dir.exists() and (case_dir / "task_brief.md").exists():
        logger.info("Case '%s' already exists, skipping creation", case_id)
        return case_id

    return creator.create_from_pdf(
        pdf_path, cases_dir=cases_dir,
        deck_type=deck_type, audience=audience,
        source_kind=source_kind,
        page_budget=page_budget or [8, 12],
    )


def run_single_case(
    case_id: str,
    config_name: str,
    max_turns: int,
    cases_dir: str = "cases",
    repair_strategy: str | None = None,
    run_suffix: str = "",
    codegen_prompt: str | None = None,
    theme_id: str | None = None,
    runs_dir: str | None = None,
    model: str | None = None,
    codegen_model: str | None = None,
    repair_model: str | None = None,
    prebuilt_blueprint_path: str | None = None,
    prebuilt_turn0_dir: str | None = None,
    style_pattern: str | None = None,
) -> dict:
    """Run the pipeline for a single case. Designed for subprocess execution."""
    # Re-setup logging for subprocess
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{case_id}] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    sub_logger = logging.getLogger(f"run.{case_id}")

    config = build_config(config_name, case_id, max_turns,
                          repair_strategy=repair_strategy, run_suffix=run_suffix,
                          codegen_prompt=codegen_prompt, theme_id=theme_id,
                          model=model,
                          codegen_model=codegen_model,
                          repair_model=repair_model,
                          prebuilt_blueprint_path=prebuilt_blueprint_path,
                          prebuilt_turn0_dir=prebuilt_turn0_dir,
                          style_pattern=style_pattern)

    # Skip if already completed
    actual_runs_dir = runs_dir or "runs"
    run_result_path = Path(actual_runs_dir) / config.run_id / "run_result.json"
    if run_result_path.exists():
        try:
            existing = json.load(open(run_result_path))
            if existing.get("status") == "completed":
                sub_logger.info("SKIPPED: already completed (%d turns)", existing.get("total_turns", 0))
                return existing
        except Exception:
            pass  # corrupted file, re-run

    sub_logger.info("Starting: config=%s, max_turns=%d",
                    config_name, max_turns)

    start = time.time()

    try:
        runner = RunManager(
            config=config,
            cases_dir=cases_dir,
            base_dir=".",
            runs_dir=runs_dir,
        )

        summaries = runner.run(case_id)
        elapsed = time.time() - start

        result = {
            "case_id": case_id,
            "config_name": config_name,
            "run_id": config.run_id,
            "status": "completed",
            "total_turns": len(summaries),
            "elapsed_sec": round(elapsed, 1),
            "run_dir": str(runner.paths.base),
            "turns": [],
        }

        for s in summaries:
            turn_info = {
                "turn": s.turn_index,
                "status": s.status.value,
                "issues_found": s.total_issues_found,
                "issues_open": s.issues_open,
                "issues_resolved": s.issues_resolved,
                "issues_new": s.issues_new,
                "repairs_applied": s.repair_units_applied,
                "should_continue": s.should_continue,
                "reason": s.reason,
            }
            result["turns"].append(turn_info)

        sub_logger.info("Completed: %d turns in %.1fs", len(summaries), elapsed)

    except Exception as e:
        elapsed = time.time() - start
        result = {
            "case_id": case_id,
            "config_name": config_name,
            "run_id": config.run_id,
            "status": "error",
            "error": str(e),
            "elapsed_sec": round(elapsed, 1),
        }
        sub_logger.error("FAILED after %.1fs: %s", elapsed, e)

    # Save individual result
    result_path = Path(actual_runs_dir) / result['run_id'] / "run_result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return result


def main():
    """Run the pipeline for one or more cases."""
    import argparse

    parser = argparse.ArgumentParser(description="PDF→PPT pipeline runner")
    parser.add_argument("--configs", default="codegen",
                        help="Config name (default: codegen)")
    parser.add_argument("--case", default=None,
                        help="Comma-separated case IDs (e.g. pdf_2408.03326v3,pdf_2106.09685)")
    parser.add_argument("--papers-dir", default=None,
                        help="Directory of PDF papers; auto-creates cases from each")
    parser.add_argument("--max-turns", type=int, default=10,
                        help="Total turns per case, including T0 generation (default: 10)")
    parser.add_argument("--repair-turns", type=int, default=None,
                        help="Repair turns after T0; overrides --max-turns")
    parser.add_argument("--parallel", type=int, default=1,
                        help="Number of parallel workers (default: 1)")
    parser.add_argument("--cases-dir", default="cases",
                        help="Base directory for cases (default: cases)")
    parser.add_argument("--skip-layout-design", action="store_true",
                        help="Ablation: skip LLM layout designer, use heuristic codegen only")
    parser.add_argument("--html-codegen", action="store_true",
                        help="Use HTML/CSS code generation (Playwright rendering) instead of python-pptx")
    parser.add_argument("--repair-strategy", choices=["redeck", "baseline"], default=None,
                        help="Repair strategy: 'redeck' (agentic, default) or 'baseline' (single-pass naive)")
    parser.add_argument("--run-suffix", default="",
                        help="Suffix appended to run directory names (e.g. 'baseline')")
    parser.add_argument("--codegen-prompt", default=None,
                        help="Custom codegen prompt name (e.g. 'slide_html_codegen_imgseed')")
    parser.add_argument("--theme-id", default=None,
                        help="Theme ID or family (e.g. 'ocean_breeze', 'navy_sand', 'demo_curated_all')")
    parser.add_argument("--style-pattern", default=None,
                        help="Design pattern for deck-level styling ('auto' or pattern name/id)")
    parser.add_argument("--runs-dir", default=None,
                        help="Custom output directory for runs (default: ./runs/)")
    parser.add_argument("--model", default=MODEL,
                        help=f"Model deployment for all modules (default: {MODEL})")
    parser.add_argument("--codegen-model", default=None,
                        help="Optional T0 HTML generation model override")
    parser.add_argument("--repair-model", default=None,
                        help="Optional HTML repair model override; defaults to codegen model")
    parser.add_argument("--prebuilt-blueprint", default=None,
                        help="Optional deck_blueprint.json reused for controlled T0 generation")
    parser.add_argument("--prebuilt-turn0-dir", default=None,
                        help="Optional prebuilt T0 artifacts reused for repair-only runs")
    parser.add_argument("--page-budget", nargs=2, type=int, metavar=("MIN", "MAX"),
                        default=[8, 12], help="Target slide-count range for new PDF cases")
    parser.add_argument("--deck-type", default="conference_talk",
                        help="Presentation intent for new PDF cases")
    parser.add_argument("--audience", default="researchers",
                        help="Target audience for new PDF cases")
    parser.add_argument("--source-kind", choices=["paper", "document"], default="paper",
                        help="Use document for reports, filings, and existing presentations")
    args = parser.parse_args()

    if args.repair_turns is not None:
        if args.repair_turns < 0:
            parser.error("--repair-turns must be non-negative")
        args.max_turns = args.repair_turns + 1
    if args.page_budget[0] > args.page_budget[1]:
        parser.error("--page-budget MIN must not exceed MAX")

    config_name = args.configs.split(",")[0]

    # If --html-codegen is set, override to use html_codegen config
    if args.html_codegen:
        if args.skip_layout_design:
            config_name = "html_codegen_no_layout"
        else:
            config_name = "html_codegen"
        logger.info("HTML codegen mode: using config '%s'", config_name)
    # If --skip-layout-design is set, override to use codegen_no_layout config
    elif args.skip_layout_design and config_name == "codegen":
        config_name = "codegen_no_layout"
        logger.info("Ablation mode: --skip-layout-design -> using config '%s'", config_name)

    # Collect case IDs to run
    case_ids = []

    if args.papers_dir:
        papers_dir = Path(args.papers_dir)
        pdf_files = sorted(papers_dir.glob("*.pdf"))
        if not pdf_files:
            logger.error("No PDF files found in %s", papers_dir)
            sys.exit(1)

        logger.info("Found %d PDFs in %s, creating cases...", len(pdf_files), papers_dir)
        for pdf_path in pdf_files:
            try:
                case_id = ensure_case_from_pdf(
                    str(pdf_path), args.cases_dir,
                    deck_type=args.deck_type,
                    audience=args.audience,
                    source_kind=args.source_kind,
                    page_budget=args.page_budget,
                )
                case_ids.append(case_id)
                logger.info("  Case ready: %s <- %s", case_id, pdf_path.name)
            except Exception as e:
                logger.error("  Failed to create case from %s: %s", pdf_path.name, e)

    if args.case:
        case_ids.extend(args.case.split(","))

    if not case_ids:
        logger.error("No cases specified. Use --case or --papers-dir")
        sys.exit(1)

    # Deduplicate
    case_ids = list(dict.fromkeys(case_ids))

    logger.info("=" * 70)
    logger.info("Running %d cases: %s", len(case_ids), case_ids)
    logger.info("Config: %s, Max turns: %d, Parallel: %d",
                config_name, args.max_turns, args.parallel)
    logger.info("=" * 70)

    all_results = []
    start_all = time.time()

    if args.parallel > 1 and len(case_ids) > 1:
        # Parallel execution
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = {
                pool.submit(
                    run_single_case,
                    case_id, config_name, args.max_turns,
                    args.cases_dir, args.repair_strategy, args.run_suffix,
                    args.codegen_prompt, args.theme_id, args.runs_dir, args.model,
                    args.codegen_model, args.repair_model,
                    args.prebuilt_blueprint, args.prebuilt_turn0_dir,
                    args.style_pattern,
                ): case_id
                for case_id in case_ids
            }

            for future in as_completed(futures):
                case_id = futures[future]
                try:
                    result = future.result()
                    all_results.append(result)
                    status = result.get("status", "?")
                    turns = result.get("total_turns", "?")
                    elapsed = result.get("elapsed_sec", "?")
                    logger.info(
                        "DONE: %s -> %s (%s turns, %ss)",
                        case_id, status, turns, elapsed,
                    )
                except Exception as e:
                    logger.error("FAILED: %s -> %s", case_id, e)
                    all_results.append({
                        "case_id": case_id, "status": "error",
                        "error": str(e),
                    })
    else:
        # Sequential execution
        for case_id in case_ids:
            result = run_single_case(
                case_id, config_name, args.max_turns,
                args.cases_dir, args.repair_strategy, args.run_suffix,
                args.codegen_prompt, args.theme_id, args.runs_dir, args.model,
                args.codegen_model, args.repair_model,
                args.prebuilt_blueprint, args.prebuilt_turn0_dir,
                args.style_pattern,
            )
            all_results.append(result)

    total_elapsed = time.time() - start_all

    # Print final summary
    print("\n" + "=" * 80)
    print(f"ALL RUNS COMPLETE ({len(all_results)} cases, {total_elapsed:.0f}s total)")
    print("=" * 80)

    for r in sorted(all_results, key=lambda x: x.get("case_id", "")):
        case = r.get("case_id", "?")
        status = r.get("status", "?")
        turns = r.get("total_turns", "-")
        elapsed = r.get("elapsed_sec", "-")
        run_dir = r.get("run_dir", "")

        if status == "completed":
            # Get final issue count
            final_turn = r.get("turns", [{}])[-1] if r.get("turns") else {}
            final_issues = final_turn.get("issues_found", "?")
            final_open = final_turn.get("issues_open", "?")
            print(f"  {case:40s} {status:10s} {turns:>3} turns  {elapsed:>6}s  "
                  f"final: {final_issues} issues ({final_open} open)")
        else:
            error = r.get("error", "")[:80]
            print(f"  {case:40s} {status:10s} {elapsed:>6}s  {error}")

    # Save aggregate results
    agg_dir = Path(args.runs_dir) if args.runs_dir else Path("runs")
    agg_path = agg_dir / "batch_results.json"
    agg_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"\nAggregate results saved to: {agg_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
