"""SpatialJudge — VLM-based spatial layout evaluation for PPTX refiner.

Unlike the generic VisualJudge, this judge focuses specifically on
layout quality (alignment, spacing, truncation) and produces
actionable planned_fix instructions that the FixPlanner can consume.
"""

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from ....llm_client import LLMClient
from ....schemas.common import Severity
from ....schemas.extraction import SlideExtraction
from ....schemas.issue import Issue, IssueEvidence
from ....utils.image_ops import image_to_base64
from ....utils.io_utils import read_text

logger = logging.getLogger(__name__)


class SpatialIssue(BaseModel):
    """A spatial issue detected by the VLM."""
    issue_type: str
    severity: str = "minor"
    affected_slides: list[int] = Field(default_factory=list)
    why_this_fails: str = ""
    planned_fix: str = ""
    evidence: dict = Field(default_factory=dict)


class SpatialJudgeResponse(BaseModel):
    """Response from the spatial judge VLM call."""
    issues: list[SpatialIssue] = Field(default_factory=list)


class SpatialJudge:
    """VLM-based judge that detects spatial layout issues in slides.

    Produces Issues with planned_fix fields that contain concrete
    spatial adjustment instructions (shape names, target positions).
    """

    def __init__(self, llm: LLMClient, model: str | None = None):
        self._llm = llm
        self._model = model
        self._system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = (
            Path(__file__).parent.parent.parent.parent
            / "prompts" / "refiner" / "spatial_judge.system.md"
        )
        return read_text(prompt_path)

    def evaluate(
        self,
        extractions: list[SlideExtraction],
        png_paths: list[str],
    ) -> list[Issue]:
        """Evaluate slides for spatial layout issues.

        Sends slide images + structural data to VLM **one slide at a time**
        for thorough per-slide analysis.
        """
        if not png_paths:
            return []

        all_issues: list[Issue] = []

        # Evaluate each slide independently for thorough analysis
        for slide_idx, (ext, png_path) in enumerate(zip(extractions, png_paths)):
            # Build per-slide structural context
            context_parts = [f"### Slide {ext.slide_id} — \"{ext.title[:60]}\""]
            context_parts.append(f"NOTE: The slide background is a single image. Icons, borders, and decorative elements are baked into the background. Only the text boxes listed below are movable shapes.")
            for obj in ext.objects:
                if not obj.bbox_emu or len(obj.bbox_emu) < 4:
                    continue
                l, t, w, h = obj.bbox_emu
                text_preview = obj.text_content[:50] if obj.text_content else ""
                font_info = f" fonts={obj.font_sizes_pt}" if obj.font_sizes_pt else ""
                context_parts.append(
                    f"  '{obj.shape_name}' ({obj.object_type}): "
                    f"pos=({l / 914400:.2f}, {t / 914400:.2f})in "
                    f"size=({w / 914400:.2f} x {h / 914400:.2f})in"
                    f"{font_info} "
                    f"text=\"{text_preview}\""
                )

            text_content = "\n".join(context_parts)

            # Load single slide image
            try:
                b64 = image_to_base64(png_path)
            except Exception as e:
                logger.warning("Failed to load PNG %s: %s", png_path, e)
                continue

            # Call VLM for this slide
            try:
                response = self._llm.call_vision_json(
                    system_prompt=self._system_prompt,
                    text_content=text_content,
                    image_urls=[b64],
                    response_model=SpatialJudgeResponse,
                    model=self._model,
                    module_name="spatial_judge",
                    max_tokens=4096,
                    temperature=0.1,
                )
            except Exception as e:
                logger.warning("SpatialJudge VLM call failed on slide %d: %s", slide_idx, e)
                continue

            # Convert to Issues
            for i, si in enumerate(response.issues):
                severity_map = {
                    "critical": Severity.CRITICAL,
                    "major": Severity.MAJOR,
                    "minor": Severity.MINOR,
                    "info": Severity.INFO,
                }
                issue = Issue(
                    issue_id=f"spatial_s{ext.slide_id}_{i:02d}",
                    rubric_id="B_spatial",
                    issue_type=si.issue_type,
                    severity=severity_map.get(si.severity, Severity.MINOR),
                    affected_slides=[ext.slide_id],
                    evidence=IssueEvidence(
                        description=json.dumps(si.evidence) if si.evidence else "",
                    ),
                    why_this_fails=si.why_this_fails,
                    planned_fix=si.planned_fix,
                )
                all_issues.append(issue)

        logger.info("SpatialJudge found %d layout issues across %d slides", len(all_issues), len(png_paths))
        return all_issues
