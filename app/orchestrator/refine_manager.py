"""RefineManager — multi-turn PPTX spatial refinement loop.

Uses agentic repair: SpatialJudge detects issues per slide,
PptxRepairAgent fixes them via tool-calling loop with verify_layout.
"""
from __future__ import annotations

import shutil
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..backends.python_pptx.refiner.font_metrics import FontMetrics
from ..backends.python_pptx.refiner.spatial_analyzer import PptxSpatialAnalyzer, SpatialReport
from ..backends.python_pptx.refiner.spatial_judge import SpatialJudge
from ..backends.python_pptx.refiner.repair_agent import PptxRepairAgent
from ..llm_client import LLMClient
from ..orchestrator.render_manager import RenderManager
from ..schemas.common import Status
from ..schemas.experiment_config import ExperimentConfig, EvalMode
from ..schemas.issue import Issue

import logging
logger = logging.getLogger(__name__)


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class RefineTurnResult:
    turn: int
    issue_count: int
    overflow_count: int
    overlap_count: int
    ops_applied: int
    timing_sec: float


@dataclass
class RefineSummary:
    input_path: Path
    output_path: Path
    total_turns: int
    initial_issues: int
    final_issues: int
    turns: list[RefineTurnResult] = field(default_factory=list)
    converged: bool = False


# ── Manager ───────────────────────────────────────────────────────────────────

class RefineManager:
    """Orchestrates multi-turn spatial refinement of a PPTX file.

    Uses agentic repair (tool-calling loop) instead of plan-then-execute.
    """

    def __init__(
        self,
        pptx_path: str | Path,
        output_dir: str | Path,
        max_turns: int = 5,
        model: Optional[str] = None,
        font_dirs: Optional[list[str]] = None,
    ):
        self.pptx_path = Path(pptx_path)
        self.output_dir = Path(output_dir)
        self.max_turns = max_turns
        self.model = model

        # Minimal ExperimentConfig for RenderManager
        eval_mode = EvalMode(enabled=True, use_judge_agent=False, use_probe_planner=False)
        self._config = ExperimentConfig(
            run_id="refine_manager", eval_mode=eval_mode,
            use_html_codegen=False, max_turns=max_turns,
        )

        # Components
        log_path = self.output_dir / "llm_calls.jsonl"
        self._llm = LLMClient(
            default_model=model or self._config.models.default,
            log_path=str(log_path),
        )
        self._font_metrics = FontMetrics(extra_font_dirs=font_dirs)
        self._spatial_analyzer = PptxSpatialAnalyzer(self._font_metrics)
        self._render_mgr = RenderManager(self._config)
        self._spatial_judge = SpatialJudge(self._llm, model=model)

        # Repair agent — needs a render function
        self._repair_agent = PptxRepairAgent(
            llm=self._llm,
            font_metrics=self._font_metrics,
            render_fn=self._render_single_slide,
            model=model,
        )

    def _render_single_slide(self, pptx_path: str, slide_index: int) -> str:
        """Render a single slide to PNG for verify_layout."""
        render_dir = self.output_dir / "verify_renders"
        render_dir.mkdir(parents=True, exist_ok=True)
        result = self._render_mgr.render_fast(pptx_path, str(render_dir))
        if result.status == Status.OK and slide_index < len(result.png_paths):
            return result.png_paths[slide_index]
        raise RuntimeError(f"Failed to render slide {slide_index}")

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> RefineSummary:
        """Execute the multi-turn refinement loop with agentic repair."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Working copy
        working_pptx = self.output_dir / self.pptx_path.name
        shutil.copy2(self.pptx_path, working_pptx)

        turn_results: list[RefineTurnResult] = []
        initial_issues = 0
        prev_issue_count: Optional[int] = None
        converged = False

        for turn in range(self.max_turns):
            t0 = time.time()
            turn_dir = self.output_dir / f"turn_{turn:02d}"
            turn_dir.mkdir(parents=True, exist_ok=True)

            # a) Analyze (deterministic)
            report: SpatialReport = self._spatial_analyzer.analyze(working_pptx)

            # b) Render all slides
            render_result = self._render_mgr.render_fast(
                pptx_path=str(working_pptx),
                output_dir=str(turn_dir / "renders"),
            )
            png_paths: list[str] = []
            if render_result.status == Status.OK:
                png_paths = render_result.png_paths or []

            # c) VLM evaluate per slide
            vlm_issues = self._spatial_judge.evaluate(
                extractions=report.extractions,
                png_paths=png_paths,
            )

            # Combine all issues
            all_vlm = vlm_issues
            issue_count = len(all_vlm) + len(report.overflows) + len(report.small_fonts)

            if turn == 0:
                initial_issues = issue_count

            # d) Convergence check
            no_improvement = (prev_issue_count is not None and issue_count >= prev_issue_count)
            converged = issue_count == 0

            if converged or no_improvement:
                turn_results.append(RefineTurnResult(
                    turn=turn, issue_count=issue_count,
                    overflow_count=len(report.overflows),
                    overlap_count=len(report.overlaps),
                    ops_applied=0, timing_sec=time.time() - t0,
                ))
                break

            # e) Group VLM issues by slide_index, dispatch repair agent per slide
            # Build slide_id → slide_index mapping
            sid_to_idx = {ext.slide_id: ext.slide_index for ext in report.extractions}
            issues_by_slide: dict[int, list[Issue]] = defaultdict(list)
            for iss in all_vlm:
                for sid in iss.affected_slides:
                    slide_idx = sid_to_idx.get(sid, -1)
                    if slide_idx >= 0:
                        issues_by_slide[slide_idx].append(iss)

            total_ops = 0
            for slide_idx in sorted(issues_by_slide.keys()):
                slide_issues = issues_by_slide[slide_idx]
                if not slide_issues:
                    continue
                if slide_idx >= len(png_paths):
                    continue

                # Build shape data for this slide
                if slide_idx < len(report.extractions):
                    ext = report.extractions[slide_idx]
                    shape_lines = []
                    for obj in ext.objects:
                        if not obj.bbox_emu or len(obj.bbox_emu) < 4:
                            continue
                        l, t, w, h = obj.bbox_emu
                        shape_lines.append(
                            f"  '{obj.shape_name}': pos=({l/914400:.2f}, {t/914400:.2f})in "
                            f"size=({w/914400:.2f}x{h/914400:.2f})in "
                            f"text=\"{obj.text_content[:40]}\""
                        )
                    shape_data = "\n".join(shape_lines)
                else:
                    shape_data = "(no shape data)"

                logger.info(
                    "Turn %d: repairing slide %d (%d issues)",
                    turn, slide_idx + 1, len(slide_issues),
                )
                ops = self._repair_agent.repair_slide(
                    pptx_path=working_pptx,
                    slide_index=slide_idx,
                    issues=slide_issues,
                    png_path=png_paths[slide_idx],
                    shape_data=shape_data,
                )
                total_ops += ops

            prev_issue_count = issue_count
            timing = time.time() - t0
            turn_results.append(RefineTurnResult(
                turn=turn, issue_count=issue_count,
                overflow_count=len(report.overflows),
                overlap_count=len(report.overlaps),
                ops_applied=total_ops, timing_sec=timing,
            ))
            logger.info("Turn %d: %d issues, %d tool calls, %.1fs", turn, issue_count, total_ops, timing)

        # Save final PPTX
        final_path = self.output_dir / f"refined_{self.pptx_path.name}"
        shutil.copy2(working_pptx, final_path)

        return RefineSummary(
            input_path=self.pptx_path,
            output_path=final_path,
            total_turns=len(turn_results),
            initial_issues=initial_issues,
            final_issues=turn_results[-1].issue_count if turn_results else 0,
            turns=turn_results,
            converged=converged,
        )
