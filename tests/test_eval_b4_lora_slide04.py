"""Minimal test: Does visual_judge detect text_overflow on lora slide 04?

T0 slide has cards with 280px height but content overflows the container.
The pipeline only flagged density_imbalance, not text_overflow.

Usage:
    AZURE_API_KEY=... python3.11 -m tests.test_eval_b4_lora_slide04
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm_client import LLMClient
from app.schemas.experiment_config import ExperimentConfig
from app.schemas.extraction import SlideExtraction, ExtractedObject
from app.modules.evaluators.visual_judge import VisualJudge

RUN_DIR = Path("runs/pdf_2106.09685_lora_html_codegen_3turns")


def make_extraction() -> SlideExtraction:
    """Build a minimal SlideExtraction for slide 04."""
    objects = [
        ExtractedObject(
            object_id="title",
            object_type="text_box",
            text_content="Aren't Existing Solutions Good Enough?",
            font_sizes_pt=[40.0],
        ),
        ExtractedObject(
            object_id="left_card",
            object_type="text_box",
            text_content=(
                "Adapters: efficient, but slower at inference\n"
                "Adapter layers: introduce extra modules into each Transformer block, adding inference latency.\n"
                "Sequential path: adapter layers still have to be processed in order with the base network.\n"
                "No bypass: there are no direct ways to skip the additional compute once adapters are inserted."
            ),
            font_sizes_pt=[22.0, 21.0],
        ),
        ExtractedObject(
            object_id="right_card",
            object_type="text_box",
            text_content=(
                "Activation tuning: cheaper, but weaker\n"
                "Activation-based methods: optimize some forms of the input-layer activations instead of full weights.\n"
                "Sequence trade-off: they can reduce the model's usable sequence length by consuming part of the context budget.\n"
                "Quality gap: these approaches often fail to match strong fine-tuning baselines on downstream tasks."
            ),
            font_sizes_pt=[22.0, 21.0],
        ),
        ExtractedObject(
            object_id="callout",
            object_type="text_box",
            text_content="DESIGN GOAL\nmake model adaptation more parameter- and compute-efficient",
            font_sizes_pt=[16.0, 28.0],
        ),
    ]
    return SlideExtraction(
        slide_id=4,
        slide_index=3,
        title="Aren't Existing Solutions Good Enough?",
        objects=objects,
        total_text_length=sum(len(o.text_content) for o in objects),
        total_objects=len(objects),
    )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    cfg = ExperimentConfig.model_validate(
        json.load(open(RUN_DIR / "experiment_config.json"))
    )
    llm = LLMClient(default_model=cfg.models.default)
    judge = VisualJudge(llm, cfg)

    screenshot = str(RUN_DIR / "turn_00" / "html_renders" / "slide_04.png")
    print(f"Screenshot: {screenshot}")
    print()

    ext = make_extraction()

    print("=" * 60)
    print("Running visual_judge evaluation on lora slide 04 T0...")
    print("Expected: should detect text_overflow in card containers")
    print("=" * 60)

    issues = judge.evaluate(
        extractions=[ext],
        png_paths=[screenshot],
        scope_slides=[4],
        turn_index=0,
    )

    print(f"\nFound {len(issues)} issues:")
    has_text_overflow = False
    for iss in issues:
        print(f"  {iss.issue_id} [{iss.issue_type}] {iss.severity.value}")
        print(f"    {iss.evidence.description[:200]}")
        if iss.issue_type == "text_overflow":
            has_text_overflow = True

    print()
    if has_text_overflow:
        print("✅ Visual judge detected text_overflow")
    else:
        print("❌ Visual judge MISSED text_overflow — sensitivity too low")
        print("   Cards are 280px tall with ~222px+ of content in 188px usable space")


if __name__ == "__main__":
    main()
