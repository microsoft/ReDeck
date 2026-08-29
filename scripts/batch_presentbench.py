#!/usr/bin/env python3.11
"""Batch runner for PresentBench evaluation.

This script:
1. Takes PresentBench case directories as input
2. Creates pipeline case directories (source_pack, task_brief, constraints)
3. Runs the slide generation pipeline with repair enabled
4. Converts PPTX to PDF via LibreOffice
5. Copies slides.pdf to PresentBench results directory structure

Usage:
    # Run all 20 selected cases
    python3.11 scripts/batch_presentbench.py --max-turns 4 --parallel 4

    # Run specific cases
    python3.11 scripts/batch_presentbench.py --cases "ICLR_2025/Attention_as_a_Hypernetwork,CVPR_2025/AIpparel_*" --max-turns 4

    # Dry run (just create case dirs, don't run pipeline)
    python3.11 scripts/batch_presentbench.py --dry-run

Environment variables:
    AZURE_API_KEY   - Azure OpenAI API key
    AZURE_ENDPOINT  - Azure OpenAI endpoint URL
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Load .env file
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("batch_presentbench")

# ============================================================
# PresentBench paths
# ============================================================
PRESENTBENCH_ROOT = Path(os.getenv(
    "PRESENTBENCH_ROOT",
    os.path.expanduser("~/PresentBench"),
))
PRESENTBENCH_DATA = PRESENTBENCH_ROOT / "data" / "academia"

# ============================================================
# 20 Selected Cases (diverse conferences)
# ============================================================
SELECTED_CASES = [
    # ICLR 2025 (5)
    "ICLR_2025/Attention_as_a_Hypernetwork",
    "ICLR_2025/Brain_Bandit-A_Biologically_Grounded_Neural_Network_for_Efficient_Control_of_Exploration",
    "ICLR_2025/Booster-Tackling_Harmful_Fine-tuning_for_Large_Language_Models_via_Attenuating_Harmful_Perturbation",
    "ICLR_2025/AI_as_Humanity_s_Salieri-Quantifying_Linguistic_Creativity_of_Language_Models_via_Systematic_Attribution_of_Machine_Text_against_Web_Text",
    "ICLR_2025/Accelerated_training_through_iterative_gradient_propagation_along_the_residual_path",
    # ICML 2025 (5)
    "ICML_2025/ICML_2025_Accelerating_LLM_Inference_with_Lossless_Speculative_Decoding_Algorithms_for_Heterogeneous_Vocabularies_Oral_6bfb95",
    "ICML_2025/ICML_2025_An_analytic_theory_of_creativity_in_convolutional_diffusion_models_Oral_2b3ae4",
    "ICML_2025/ICML_2025_Beyond_Self-Repellent_Kernels__History-Driven_Target_Towards_Efficient_Nonlinear_MCMC_on_General_Graphs_Oral_207f19",
    "ICML_2025/ICML_2025_Can_MLLMs_Reason_in_Multimodality__EMMA__An_Enhanced_MultiModal_ReAsoning_Benchmark_Oral_72c07c",
    "ICML_2025/ICML_2025_Emergence_in_non-neural_models__grokking_modular_arithmetic_via_average_gradient_outer_product_Oral_50041e",
    # CVPR 2025 (5)
    "CVPR_2025/AIpparel_A_Multimodal_Foundation_Model_for_Digital_Garments",
    "CVPR_2025/DepthCrafter_Generating_Consistent_Long_Depth_Sequences_for_Open-world_Videos",
    "CVPR_2025/EffiDec3D_An_Optimized_Decoder_for_High-Performance_and_Efficient_3D_Medical_Image_Segmentation",
    "CVPR_2025/Flowing_from_Words_to_Pixels_A_Noise-Free_Framework_for_Cross-Modality_Evolution",
    "CVPR_2025/Free-viewpoint_Human_Animation_with_Pose-correlated_Reference_Selection",
    # CVPR 2024 (3)
    "CVPR_2024/Discovering_and_Mitigating_Visual_Biases_through_Keyword_Explanation",
    "CVPR_2024/Frequency-Adaptive_Dilated_Convolution_for_Semantic_Segmentation",
    "CVPR_2024/RAVE_Randomized_Noise_Shuffling_for_Fast_and_Consistent_Video_Editing_with_Diffusion_Models",
    # ICLR 2024 (2)
    "ICLR_2024/ICLR_2024_Cameras_as_Rays__Pose_Estimation_via_Ray_Diffusion_Oral_20d4d7",
    "ICLR_2024/ICLR_2024_ClimODE__Climate_and_Weather_Forecasting_with_Physics-informed_Neural_ODEs_Oral_b88221",
]

MODEL = "gpt-5.4"


# ============================================================
# Pipeline config
# ============================================================
def build_config(case_id: str, max_turns: int) -> ExperimentConfig:
    """Build ExperimentConfig for PresentBench run."""
    config_dict = {
        "run_id": f"pb_{case_id}_{max_turns}t",
        "ablation_tags": ["presentbench", "codegen", "redeck"],
        "models": {"default": MODEL},
        "eval_mode": {
            "enabled": True,
            "split_level": "family_plus_slide",
            "use_judge_agent": True,
        },
        "render_mode": {
            "fast_backend": "linux_lo_pdf",
            "reference_backend": "graph_pdf",
        },
        "max_turns": max_turns,
        "use_html_codegen": True,
        "repair_strategy": "redeck",
        "layout_strategy": "template",
    }
    return ExperimentConfig.model_validate(config_dict)


# ============================================================
# Case creation from PresentBench
# ============================================================
def create_case_from_presentbench(
    pb_case_rel: str,
    our_cases_dir: str = "cases",
) -> str:
    """Create a pipeline case directory from a PresentBench case.

    Args:
        pb_case_rel: Relative path like "ICLR_2025/Attention_as_a_Hypernetwork"
        our_cases_dir: Our cases directory

    Returns:
        case_id string
    """
    pb_case_dir = PRESENTBENCH_DATA / pb_case_rel
    if not pb_case_dir.exists():
        raise FileNotFoundError(f"PresentBench case not found: {pb_case_dir}")

    # Find the material PDF
    material_pdf = pb_case_dir / "material.pdf"
    if not material_pdf.exists():
        raise FileNotFoundError(f"material.pdf not found in {pb_case_dir}")

    # Read the PresentBench instructions for the task brief
    instructions_path = pb_case_dir / "generation_task" / "instructions.md"
    pb_instructions = ""
    if instructions_path.exists():
        pb_instructions = instructions_path.read_text(encoding="utf-8")

    # Generate case_id from the relative path
    case_name = pb_case_rel.replace("/", "_")
    case_id = f"pb_{case_name}"

    case_dir = Path(our_cases_dir) / case_id
    source_dir = case_dir / "source_pack"

    # Check if case already exists and has all required files
    if (case_dir / "task_brief.md").exists() and (source_dir / "paper_full.md").exists():
        logger.info("Case '%s' already exists, skipping creation", case_id)
        return case_id

    # Use CaseCreator to handle PDF processing (marker extraction, figure extraction, etc.)
    from app.modules.case_creator import CaseCreator
    creator = CaseCreator()

    # Create case from the PDF
    actual_case_id = creator.create_from_pdf(
        pdf_path=material_pdf,
        case_id=case_id,
        cases_dir=our_cases_dir,
        deck_type="conference_talk",
        audience="researchers and graduate students",
        page_budget=[16, 20],
    )

    # Override the task_brief.md with PresentBench's instructions if available
    if pb_instructions:
        # The PresentBench instructions are very detailed and case-specific
        # They include exact required sections, content constraints, etc.
        # We wrap them in our task_brief format
        task_brief = _build_task_brief_from_presentbench(pb_instructions, case_id)
        (case_dir / "task_brief.md").write_text(task_brief, encoding="utf-8")
        logger.info("Overwrote task_brief.md with PresentBench instructions")

    # Update constraints to enforce 16-20 page budget
    constraints_path = case_dir / "constraints.json"
    if constraints_path.exists():
        constraints = json.loads(constraints_path.read_text())
    else:
        constraints = {}
    constraints["page_budget"] = [16, 20]
    constraints["case_id"] = case_id
    constraints_path.write_text(
        json.dumps(constraints, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info("Created case '%s' from PresentBench: %s", case_id, pb_case_rel)
    return actual_case_id


def _build_task_brief_from_presentbench(pb_instructions: str, case_id: str) -> str:
    """Build our task_brief.md from PresentBench instructions.

    PresentBench instructions are already very detailed — we use them
    directly but add our standard headers for compatibility.
    """
    return f"""# Task Brief: {case_id}

## Source
This task brief is derived from PresentBench evaluation instructions.
The slides will be evaluated against a detailed checklist covering:
- Content completeness (all required sections present)
- Content correctness (all facts accurate)
- Per-slide factual fidelity
- Visual design quality
- Presentation fundamentals

## PresentBench Instructions

{pb_instructions}

## Pipeline-Specific Notes
- Output format: PPTX (will be converted to PDF for evaluation)
- Page budget: 16-20 slides (STRICT — benchmark penalizes violations)
- All content must be traceable to the source paper
- Include source attribution on every chart/table (e.g., "Figure 1 in paper")
- Every data point must exactly match the source paper
"""


# ============================================================
# Convert PPTX to PDF
# ============================================================
def convert_pptx_to_pdf(pptx_path: str, output_dir: str = None) -> str:
    """Convert PPTX to PDF using LibreOffice.

    Returns path to the generated PDF.
    """
    pptx_path = Path(pptx_path)
    if not pptx_path.exists():
        raise FileNotFoundError(f"PPTX not found: {pptx_path}")

    if output_dir is None:
        output_dir = str(pptx_path.parent)

    # Use LibreOffice to convert
    cmd = [
        "libreoffice", "--headless", "--convert-to", "pdf",
        "--outdir", output_dir,
        str(pptx_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error("LibreOffice conversion failed: %s", result.stderr)
            return None

        # Find the generated PDF
        pdf_name = pptx_path.stem + ".pdf"
        pdf_path = Path(output_dir) / pdf_name
        if pdf_path.exists():
            return str(pdf_path)
        else:
            logger.error("PDF not found after conversion: %s", pdf_path)
            return None

    except subprocess.TimeoutExpired:
        logger.error("LibreOffice conversion timed out")
        return None
    except FileNotFoundError:
        logger.error("LibreOffice not found. Install with: apt install libreoffice")
        return None


# ============================================================
# Copy results to PresentBench directory
# ============================================================
def copy_to_presentbench_results(
    pdf_path: str,
    pb_case_rel: str,
    agent_name: str = "OurSystem",
) -> str:
    """Copy slides.pdf to PresentBench results directory.

    Expected structure:
    PresentBench/results/{agent_name}/academia/{conf}/{case}/generation_task/results/slides.pdf
    """
    results_dir = (
        PRESENTBENCH_ROOT / "results" / agent_name / "academia"
        / pb_case_rel / "generation_task" / "results"
    )
    results_dir.mkdir(parents=True, exist_ok=True)

    dest = results_dir / "slides.pdf"
    shutil.copy2(pdf_path, dest)
    logger.info("Copied slides.pdf to %s", dest)
    return str(dest)


# ============================================================
# Run single case
# ============================================================
def run_single_case(
    pb_case_rel: str,
    max_turns: int,
    cases_dir: str = "cases",
    agent_name: str = "OurSystem",
) -> dict:
    """Run the full pipeline for a single PresentBench case.

    1. Create case directory
    2. Run pipeline with repair
    3. Convert PPTX to PDF
    4. Copy to PresentBench results
    """
    # Re-setup logging for subprocess
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{pb_case_rel.split('/')[-1][:30]}] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )

    start = time.time()
    result = {
        "pb_case": pb_case_rel,
        "status": "pending",
        "elapsed_sec": 0,
    }

    try:
        # Step 1: Create case
        case_id = create_case_from_presentbench(pb_case_rel, cases_dir)
        result["case_id"] = case_id

        # Step 2: Build config and run pipeline
        config = build_config(case_id, max_turns)
        result["run_id"] = config.run_id

        # Skip if already completed
        run_result_path = Path("runs") / config.run_id / "run_result.json"
        if run_result_path.exists():
            try:
                existing = json.loads(run_result_path.read_text())
                if existing.get("status") == "completed":
                    logger.info("SKIPPED: %s already completed", case_id)
                    result.update(existing)
                    result["status"] = "skipped"

                    # Still need to ensure PDF is copied
                    _ensure_pdf_copied(config, pb_case_rel, agent_name)
                    result["elapsed_sec"] = round(time.time() - start, 1)
                    return result
            except Exception:
                pass

        runner = RunManager(
            config=config,
            cases_dir=cases_dir,
            base_dir=".",
        )
        summaries = runner.run(case_id)
        elapsed = time.time() - start

        # Extract turn info
        turns_info = []
        for s in summaries:
            turns_info.append({
                "turn": s.turn_index,
                "issues_found": s.total_issues_found,
                "issues_open": s.issues_open,
                "issues_resolved": s.issues_resolved,
                "issues_new": s.issues_new,
                "repairs_applied": s.repair_units_applied,
                "should_continue": s.should_continue,
            })

        result.update({
            "status": "completed",
            "total_turns": len(summaries),
            "elapsed_sec": round(elapsed, 1),
            "run_dir": str(runner.paths.base),
            "turns": turns_info,
        })

        # Step 3: Find the final PPTX and convert to PDF
        final_turn = len(summaries) - 1
        pptx_path = str(runner.paths.deck_pptx_path(final_turn))
        if not Path(pptx_path).exists():
            # Try turn 0
            pptx_path = str(runner.paths.deck_pptx_path(0))

        if Path(pptx_path).exists():
            pdf_path = convert_pptx_to_pdf(pptx_path)
            if pdf_path:
                # Step 4: Copy to PresentBench results
                dest = copy_to_presentbench_results(
                    pdf_path, pb_case_rel, agent_name,
                )
                result["pdf_path"] = dest
                result["slides_ready"] = True
            else:
                result["slides_ready"] = False
                result["error"] = "PPTX to PDF conversion failed"
        else:
            result["slides_ready"] = False
            result["error"] = f"PPTX not found at {pptx_path}"

    except Exception as e:
        elapsed = time.time() - start
        result.update({
            "status": "error",
            "error": str(e),
            "elapsed_sec": round(elapsed, 1),
        })
        logger.error("FAILED %s: %s", pb_case_rel, e, exc_info=True)

    # Save individual result
    run_id = result.get("run_id", f"pb_{pb_case_rel.replace('/', '_')}")
    result_path = Path(f"runs/{run_id}/run_result.json")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    return result


def _ensure_pdf_copied(config, pb_case_rel, agent_name):
    """Ensure the PDF is in PresentBench results dir (for skipped runs)."""
    from app.utils.paths import RunPaths
    paths = RunPaths(".", config.run_id)

    # Try to find the final PPTX
    for turn in range(config.max_turns - 1, -1, -1):
        pptx_path = paths.deck_pptx_path(turn)
        if pptx_path.exists():
            pdf_path = convert_pptx_to_pdf(str(pptx_path))
            if pdf_path:
                copy_to_presentbench_results(pdf_path, pb_case_rel, agent_name)
            return


# ============================================================
# Main
# ============================================================
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="PresentBench batch runner: generate slides & evaluate"
    )
    parser.add_argument(
        "--cases", default=None,
        help="Comma-separated PresentBench case paths (e.g., ICLR_2025/Attention_*). "
             "Default: run all 20 selected cases.",
    )
    parser.add_argument(
        "--max-turns", type=int, default=4,
        help="Maximum repair turns (default: 4)",
    )
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="Number of parallel workers (default: 1)",
    )
    parser.add_argument(
        "--cases-dir", default="cases",
        help="Our pipeline's cases directory (default: cases)",
    )
    parser.add_argument(
        "--agent-name", default="OurSystem",
        help="Agent name for PresentBench results (default: OurSystem)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only create case directories, don't run pipeline",
    )
    parser.add_argument(
        "--evaluate", action="store_true",
        help="After generation, run PresentBench evaluation (requires Gemini API)",
    )
    args = parser.parse_args()

    # Determine which cases to run
    if args.cases:
        case_list = [c.strip() for c in args.cases.split(",")]
    else:
        case_list = SELECTED_CASES

    # Validate cases exist
    valid_cases = []
    for case_rel in case_list:
        case_dir = PRESENTBENCH_DATA / case_rel
        if case_dir.exists():
            valid_cases.append(case_rel)
        else:
            logger.warning("Case not found: %s (skipping)", case_dir)

    if not valid_cases:
        logger.error("No valid cases found!")
        sys.exit(1)

    logger.info("=" * 70)
    logger.info("PresentBench Batch Runner")
    logger.info("Cases: %d, Max turns: %d, Parallel: %d",
                len(valid_cases), args.max_turns, args.parallel)
    logger.info("=" * 70)

    if args.dry_run:
        logger.info("DRY RUN: creating case directories only")
        for case_rel in valid_cases:
            try:
                case_id = create_case_from_presentbench(case_rel, args.cases_dir)
                logger.info("  Created: %s -> %s", case_rel, case_id)
            except Exception as e:
                logger.error("  Failed: %s -> %s", case_rel, e)
        return

    # Run pipeline for each case
    all_results = []
    start_all = time.time()

    if args.parallel > 1 and len(valid_cases) > 1:
        with ProcessPoolExecutor(max_workers=args.parallel) as pool:
            futures = {
                pool.submit(
                    run_single_case,
                    case_rel, args.max_turns, args.cases_dir, args.agent_name,
                ): case_rel
                for case_rel in valid_cases
            }
            for future in as_completed(futures):
                case_rel = futures[future]
                try:
                    result = future.result()
                    all_results.append(result)
                    logger.info(
                        "DONE: %s -> %s (%s turns, %ss)",
                        case_rel, result.get("status"),
                        result.get("total_turns", "?"),
                        result.get("elapsed_sec", "?"),
                    )
                except Exception as e:
                    logger.error("FAILED: %s -> %s", case_rel, e)
                    all_results.append({
                        "pb_case": case_rel, "status": "error", "error": str(e),
                    })
    else:
        for case_rel in valid_cases:
            result = run_single_case(
                case_rel, args.max_turns, args.cases_dir, args.agent_name,
            )
            all_results.append(result)
            logger.info(
                "DONE: %s -> %s (%s turns, %ss)",
                case_rel, result.get("status"),
                result.get("total_turns", "?"),
                result.get("elapsed_sec", "?"),
            )

    total_elapsed = time.time() - start_all

    # Print summary
    print("\n" + "=" * 80)
    print(f"BATCH COMPLETE ({len(all_results)} cases, {total_elapsed:.0f}s total)")
    print("=" * 80)

    completed = 0
    failed = 0
    slides_ready = 0

    for r in sorted(all_results, key=lambda x: x.get("pb_case", "")):
        case = r.get("pb_case", "?").split("/")[-1][:40]
        status = r.get("status", "?")
        turns = r.get("total_turns", "-")
        elapsed = r.get("elapsed_sec", "-")
        ready = r.get("slides_ready", False)

        if status == "completed":
            completed += 1
            if ready:
                slides_ready += 1
            final_turn = (r.get("turns") or [{}])[-1]
            t0_turn = (r.get("turns") or [{}])[0]
            t0_issues = t0_turn.get("issues_found", "?")
            final_issues = final_turn.get("issues_found", "?")
            final_open = final_turn.get("issues_open", "?")
            print(
                f"  {case:42s} {status:10s} {turns:>2} turns  "
                f"{elapsed:>6}s  T0:{t0_issues}→T{turns-1 if isinstance(turns,int) else '?'}:{final_issues} "
                f"({final_open} open)  {'PDF✓' if ready else 'PDF✗'}"
            )
        elif status == "skipped":
            completed += 1
            slides_ready += 1
            print(f"  {case:42s} {'SKIPPED':10s}")
        else:
            failed += 1
            error = r.get("error", "")[:60]
            print(f"  {case:42s} {'FAILED':10s} {error}")

    print(f"\nCompleted: {completed}/{len(all_results)}, "
          f"Slides ready: {slides_ready}, Failed: {failed}")

    # Compute repair effectiveness
    _print_repair_stats(all_results)

    # Save aggregate results
    agg_path = Path("runs/presentbench_batch_results.json")
    agg_path.parent.mkdir(parents=True, exist_ok=True)
    agg_path.write_text(json.dumps(all_results, indent=2, ensure_ascii=False))
    print(f"\nResults saved to: {agg_path}")

    # Run PresentBench evaluation if requested
    if args.evaluate:
        print("\n" + "=" * 80)
        print("Running PresentBench evaluation...")
        print("=" * 80)
        _run_presentbench_eval(args.agent_name)

    print("=" * 80)


def _print_repair_stats(results: list[dict]):
    """Print repair effectiveness statistics."""
    total_t0_issues = 0
    total_final_issues = 0
    total_resolved = 0
    total_new = 0
    cases_with_repair = 0

    for r in results:
        turns = r.get("turns", [])
        if len(turns) < 2:
            continue

        cases_with_repair += 1
        t0 = turns[0]
        total_t0_issues += t0.get("issues_found", 0)

        final = turns[-1]
        total_final_issues += final.get("issues_found", 0)

        for t in turns[1:]:
            total_resolved += t.get("issues_resolved", 0)
            total_new += t.get("issues_new", 0)

    if cases_with_repair > 0:
        print(f"\n--- Repair Effectiveness ---")
        print(f"  Cases with repair: {cases_with_repair}")
        print(f"  T0 total issues: {total_t0_issues}")
        print(f"  Final total issues: {total_final_issues}")
        net_reduction = total_t0_issues - total_final_issues
        pct = (net_reduction / total_t0_issues * 100) if total_t0_issues else 0
        print(f"  Net reduction: {net_reduction} ({pct:.1f}%)")
        print(f"  Total resolved across turns: {total_resolved}")
        print(f"  Total new across turns: {total_new}")
        if total_resolved > 0:
            regression_rate = total_new / total_resolved * 100
            print(f"  Regression rate: {regression_rate:.1f}% (new/resolved)")


def _run_presentbench_eval(agent_name: str):
    """Run PresentBench evaluation."""
    judge_script = PRESENTBENCH_ROOT / "judge_all.py"
    if not judge_script.exists():
        logger.error("PresentBench judge_all.py not found at %s", judge_script)
        return

    cmd = [
        sys.executable, str(judge_script),
        "--agent_name", agent_name,
        "--result_root", str(PRESENTBENCH_ROOT / "results" / agent_name),
        "--data_root", str(PRESENTBENCH_ROOT / "data"),
    ]

    logger.info("Running: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=str(PRESENTBENCH_ROOT), check=True, timeout=3600)
    except subprocess.CalledProcessError as e:
        logger.error("PresentBench evaluation failed: %s", e)
    except subprocess.TimeoutExpired:
        logger.error("PresentBench evaluation timed out (1 hour)")


if __name__ == "__main__":
    main()
