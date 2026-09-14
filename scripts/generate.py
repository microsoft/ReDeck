#!/usr/bin/env python3
"""Prepare a PDF or source pack, plan once, and run the current generation pipeline."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redeck_style.paths import resolve_cases_root
from redeck_style.evaluation.coordinator import add_judge_arguments
from redeck_style.evaluation.probes import add_probe_arguments, probe_config
from scripts import codegen, repair
from scripts.repair_session import add_repair_arguments


class PlanningClient:
    """Adapt the existing deck planner to the shared model transport."""

    def __init__(self, api, directory):
        self.client = codegen.get_client(api)
        self.directory = directory

    def call_json(self, *, system_prompt, user_content, response_model, model, max_tokens, **metadata):
        from app.utils.json_utils import strip_code_fences

        response = codegen.call_llm(
            self.client, model, system_prompt, user_content, max_output_tokens=max_tokens,
            log_prefix=self.directory / "request",
        )[0]
        return response_model.model_validate_json(strip_code_fences(response))


def prepare_blueprint(case_id, cases_root, directory, model, api, page_budget):
    from app.modules.case_loader import CaseLoader
    from app.modules.deck_planner import DeckPlanner
    from app.schemas.experiment_config import ExperimentConfig, ModelConfig

    state = CaseLoader(cases_root).load(case_id)
    if page_budget:
        state.intent.page_budget = page_budget
    document = cases_root / case_id / "source_pack/paper_full.md"
    if not document.is_file() or not document.read_text().strip():
        raise ValueError("A nonempty source_pack/paper_full.md is required for planning")
    directory.mkdir(parents=True, exist_ok=False)
    planner = DeckPlanner(PlanningClient(api, directory), ExperimentConfig(
        run_id=case_id, models=ModelConfig(default=model),
    ))
    blueprint = planner.plan(state.intent, state.evidence, state.task_brief,
                             paper_full_md=document.read_text(), allow_fallback=False)
    if not blueprint.slides:
        raise ValueError("Planning returned an empty deck")
    destination = directory / "deck_blueprint.json"
    destination.write_text(blueprint.model_dump_json(indent=2) + "\n")
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog="Additional design options are forwarded to codegen; see redeck codegen --help.")
    add_judge_arguments(parser)
    add_probe_arguments(parser)
    add_repair_arguments(parser)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--case")
    parser.add_argument("--cases-root", type=Path)
    parser.add_argument("--blueprint", type=Path)
    parser.add_argument("--out", "--output-dir", "-o", dest="out", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--api", choices=("local", "trapi", "anthropic"), default="local")
    parser.add_argument("--pages", help="Slide count, or inclusive min,max budget, for new planning")
    parser.add_argument("--repair", action="store_true", help="Run the same unified repair controller after generation")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--dry-run", action="store_true", help="Requires a supplied blueprint; render prompts without model calls")
    args, design_arguments = parser.parse_known_args(argv)
    codegen.build_parser().parse_args(["--case", args.case or "prepared_document", *design_arguments])
    if not args.pdf and not args.case:
        parser.error("Supply --pdf or --case")
    if args.case and (Path(args.case).name != args.case or args.case in {".", ".."}):
        parser.error("--case must be a simple case ID")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Output must be a fresh directory")
    if args.dry_run and (args.pdf or not args.blueprint or args.repair):
        parser.error("--dry-run requires --case and --blueprint, without --pdf or --repair")
    if not 1 <= args.attempts <= 6:
        parser.error("--attempts must be between 1 and 6")
    try:
        routes = probe_config({"routes": args.probe_routes, "mode": args.judge_mode,
                               "execution": args.probe_execution})["routes"]
    except ValueError as error:
        parser.error(str(error))
    page_budget = None
    if args.pages:
        try:
            page_budget = [int(value) for value in args.pages.split(",")]
            if len(page_budget) == 1:
                page_budget *= 2
            if len(page_budget) != 2 or not 1 <= page_budget[0] <= page_budget[1]:
                raise ValueError
        except ValueError:
            parser.error("--pages must be a positive count or min,max")
    cases_root = resolve_cases_root(args.cases_root)
    if args.pdf:
        from app.modules.case_creator import CaseCreator

        creator = CaseCreator()
        args.case = args.case or creator._generate_case_id(args.pdf)
        if (cases_root / args.case).exists():
            parser.error("PDF extraction requires a new case ID")
        args.case = creator.create_from_pdf(args.pdf, case_id=args.case, cases_dir=cases_root, page_budget=page_budget)
    document = cases_root / args.case / "source_pack/paper_full.md"
    if not document.is_file() or not document.read_text().strip():
        parser.error("A nonempty source_pack/paper_full.md is required; prepare source text before generation")
    blueprint = args.blueprint or prepare_blueprint(
        args.case, cases_root, args.out / "planning", args.model, args.api, page_budget,
    )
    common = ["--model", args.model, "--api", args.api]
    evaluation = []
    for field in ("judge_model", "judge_python", "probe_root", "content_workers", "request_limit", "probe_cache"):
        value = getattr(args, field)
        if value is not None:
            evaluation.extend(["--" + field.replace("_", "-"), str(value)])
    evaluation.extend(["--judge-mode", args.judge_mode if "content" in routes else "off"])
    generation = ["--case", args.case, "--cases-root", str(cases_root), "--blueprint", str(blueprint),
                  "--out", str(args.out), *common, *evaluation, *design_arguments]
    if args.dry_run:
        generation.append("--dry-run")
    codegen.main(generation)
    if args.repair:
        repair.main(["--dir", str(args.out / "slide_code"), "--output-dir", str(args.out / "repair"),
                     "--source-run", str(args.out), "--attempts", str(args.attempts), *common, *evaluation,
                     "--probe-execution", args.probe_execution, "--content-repair", args.content_repair,
                     "--probe-routes", *routes])
    print(json.dumps({"generation": str(args.out), "repair": str(args.out / "repair") if args.repair else None}))


if __name__ == "__main__":
    main()
