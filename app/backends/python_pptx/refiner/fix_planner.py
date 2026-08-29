"""LLM-powered fix planner: turns spatial issues into a FixPlan."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .spatial_analyzer import ShapeOverflow, OverlapPair, SpatialReport
from ....llm_client import LLMClient
from ....schemas.issue import Issue
from ....utils.io_utils import read_text
from ....utils.image_ops import image_to_base64

_PROMPT_PATH = Path(__file__).parent.parent.parent.parent / "app" / "prompts" / "refiner" / "fix_planner.system.md"
# Resolve relative to repo root more robustly
_PROMPT_PATH_ALT = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "refiner" / "fix_planner.system.md"

_EMU_PER_PT = 12700


class FixOp(BaseModel):
    slide_index: int
    shape_name: str
    op_type: str
    params: dict
    reason: str = ""


class FixPlan(BaseModel):
    ops: list[FixOp] = Field(default_factory=list)
    rationale: str = ""


class FixPlanner:
    def __init__(self, llm: LLMClient, model: str | None = None):
        self._llm = llm
        self._model = model

    def _load_prompt(self) -> str:
        path = _PROMPT_PATH_ALT if _PROMPT_PATH_ALT.exists() else _PROMPT_PATH
        return read_text(path)

    def plan(
        self,
        report: SpatialReport,
        issues: list[Issue],
        png_paths: list[str],
    ) -> FixPlan:
        system_prompt = self._load_prompt()
        user_content = self._build_context(report, issues)

        if png_paths:
            image_urls = [image_to_base64(p) for p in png_paths]
            return self._llm.call_vision_json(
                system_prompt=system_prompt,
                text_content=user_content,
                image_urls=image_urls,
                response_model=FixPlan,
                model=self._model,
                module_name="fix_planner",
                max_tokens=16384,
            )
        else:
            return self._llm.call_json(
                system_prompt=system_prompt,
                user_content=user_content,
                response_model=FixPlan,
                model=self._model,
                module_name="fix_planner",
                max_tokens=16384,
            )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _build_context(self, report: SpatialReport, issues: list[Issue]) -> str:
        parts: list[str] = []

        parts.append(
            f"Slide dimensions: width={report.slide_width_emu} EMU, "
            f"height={report.slide_height_emu} EMU"
        )

        if report.overflows:
            parts.append("\n## Text Overflows")
            for ov in report.overflows:
                size_pt = round(ov.font_size_emu / _EMU_PER_PT, 1)
                parts.append(
                    f"- slide {ov.slide_index}, shape '{ov.shape_name}': "
                    f"overflow h={ov.overflow.overflow_height_emu} EMU "
                    f"w={ov.overflow.overflow_width_emu} EMU, "
                    f"font {size_pt}pt, "
                    f"box {ov.box_width_emu}x{ov.box_height_emu} EMU, "
                    f"text: \"{ov.text_snippet[:60]}\""
                )

        if report.overlaps:
            parts.append("\n## Shape Overlaps")
            for op in report.overlaps:
                parts.append(
                    f"- slide {op.slide_index}: '{op.shape_a_name}' overlaps "
                    f"'{op.shape_b_name}' by {op.overlap_area_sq_in:.2f} sq in"
                )

        if report.small_fonts:
            parts.append(f"\n## Small Fonts ({len(report.small_fonts)} instances below {report.small_fonts[0].min_readable_pt}pt)")
            parts.append("These text runs are too small to read comfortably. Use `enlarge_font` to fix.")
            # Group by slide
            from collections import defaultdict
            by_slide = defaultdict(list)
            for sf in report.small_fonts:
                by_slide[sf.slide_index].append(sf)
            for si in sorted(by_slide):
                for sf in by_slide[si]:
                    parts.append(
                        f"- slide {sf.slide_index}, '{sf.shape_name}': "
                        f"{sf.font_size_pt}pt (min {sf.min_readable_pt}pt) "
                        f"text: \"{sf.text_snippet}\""
                    )

        if issues:
            parts.append("\n## VLM Layout Issues (with suggested fixes)")
            for iss in issues:
                slides = iss.affected_slides if iss.affected_slides else ["?"]
                parts.append(f"- slides {slides}: [{iss.issue_type}] {iss.why_this_fails}")
                if iss.planned_fix:
                    parts.append(f"  SUGGESTED FIX: {iss.planned_fix}")

        # Shape inventory from extractions, with neighbor constraints
        if report.extractions:
            parts.append("\n## Shape Data (with neighbor constraints)")
            parts.append("IMPORTANT: When expanding a shape, check that it does not overlap its neighbors listed below.")
            sw = report.slide_width_emu
            sh = report.slide_height_emu
            slide_area = sw * sh if sw and sh else 1

            for slide_ext in report.extractions:
                objs = slide_ext.objects
                parts.append(f"\n### Slide {slide_ext.slide_index} (bounds: {sw/914400:.2f}x{sh/914400:.2f}in)")
                for i, obj in enumerate(objs):
                    bbox = obj.bbox_emu if obj.bbox_emu else [0, 0, 0, 0]
                    l, t, w, h = bbox[0], bbox[1], bbox[2], bbox[3]
                    # Skip backgrounds
                    if slide_area > 0 and (w * h / slide_area) > 0.85:
                        continue
                    right = l + w
                    bottom = t + h

                    # Find nearest neighbor to the right
                    nearest_right = ""
                    min_gap_right = sw - right
                    for j, other in enumerate(objs):
                        if j == i:
                            continue
                        ob = other.bbox_emu if other.bbox_emu else [0, 0, 0, 0]
                        ol, ot, ow, oh = ob
                        if slide_area > 0 and (ow * oh / slide_area) > 0.85:
                            continue
                        # To the right and vertically overlapping
                        if ol >= right and ot < bottom and ot + oh > t:
                            gap = ol - right
                            if gap < min_gap_right:
                                min_gap_right = gap
                                nearest_right = f" | RIGHT_NEIGHBOR: '{other.shape_name}' at {ol/914400:.2f}in (gap={gap/914400:.2f}in)"

                    parts.append(
                        f"  '{obj.shape_name}': "
                        f"pos=({l/914400:.2f},{t/914400:.2f}) "
                        f"size=({w/914400:.2f}x{h/914400:.2f}) "
                        f"right_edge={right/914400:.2f}in "
                        f"text=\"{obj.text_content[:40]}\""
                        f"{nearest_right}"
                    )

        return "\n".join(parts)
