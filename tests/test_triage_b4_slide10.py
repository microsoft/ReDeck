"""Minimal test: B4_slide10_00 triage — verify visual judge verdict.

The third bullet in 'Key caveats' panel is still truncated at the bottom
in T2, yet visual judge marked it RESOLVED. This test reproduces the issue.

Usage:
    python -m tests.test_triage_b4_slide10
"""

import copy
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm_client import LLMClient
from app.schemas.experiment_config import ExperimentConfig
from app.schemas.issue import Issue
from app.modules.evaluators.visual_judge import VisualJudge
from app.utils.image_ops import image_to_base64

RUN_DIR = Path("runs/pdf_2303.08774_gpt4_html_codegen_3turns")

logger = logging.getLogger(__name__)


def load_issue() -> Issue:
    """Load B4_slide10_00 from T1 issues (where it was first discovered as open)."""
    issues_path = RUN_DIR / "turn_01" / "eval" / "issues.jsonl"
    with open(issues_path) as f:
        for line in f:
            iss = Issue.model_validate(json.loads(line))
            if iss.issue_id == "B4_slide10_00":
                return iss
    raise ValueError("B4_slide10_00 not found in " + str(issues_path))


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
    issue = load_issue()

    # Use T2 screenshot (the one after repair attempt)
    screenshot = str(RUN_DIR / "turn_02" / "html_renders" / "slide_10.png")
    print(f"Screenshot: {screenshot}")
    print(f"Issue: {issue.issue_id} [{issue.issue_type}]")
    print(f"  Description: {issue.evidence.description[:200]}...")
    print()

    img_b64 = image_to_base64(screenshot, max_size=1920)
    user_text = json.dumps({
        "scope_slides": [10],
        "slide_info": [{
            "slide_id": 10,
            "title": "Benchmark Interpretation and Contamination Caveats",
            "total_words": 120,
            "object_count": 6,
        }],
    }, indent=2)

    issue_copy = copy.deepcopy(issue)

    print("=" * 60)
    print("Running triage on B4_slide10_00 with T2 screenshot...")
    print("Expected: PERSISTED (text is still truncated)")
    print("=" * 60)

    triaged = judge._triage_previous_issues(
        previous_issues=[issue_copy],
        scope_slides=[10],
        user_content=user_text,
        model="gpt-5.4",
        turn_index=2,
        image_urls=[img_b64],
    )

    for t in triaged:
        status = t.status.value
        fix = (t.planned_fix or "N/A")[:300]
        print(f"\n  issue_id:    {t.issue_id}")
        print(f"  status:      {status}")
        print(f"  planned_fix: {fix}")
        if hasattr(t, 'verdict'):
            print(f"  verdict:     {t.verdict}")

    print()
    if triaged and triaged[0].status.value == "resolved":
        print("❌ BUG REPRODUCED: Visual judge incorrectly marked as RESOLVED")
        print("   The third bullet is still truncated at the panel bottom.")
    elif triaged and triaged[0].status.value != "resolved":
        print("✅ Visual judge correctly identified as NOT resolved")
    else:
        print("⚠ No triage result returned")


if __name__ == "__main__":
    main()
