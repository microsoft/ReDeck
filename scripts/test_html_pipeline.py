#!/usr/bin/env python3.11
"""Quick test: run one PresentBench case with HTML codegen pipeline."""

import json
import sys
import os
import logging
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from app.schemas.experiment_config import ExperimentConfig
from app.orchestrator.run_manager import RunManager

# Minimal config with HTML codegen enabled
config_dict = {
    "run_id": "html_test_attention",
    "use_html_codegen": True,
    "repair_strategy": "redeck",
    "layout_strategy": "template",
    "max_turns": 2,
    "models": {
        "default": "gpt-5.4",
    },
    "eval_mode": {
        "enabled": True,
        "use_judge_agent": True,
    },
    "render_mode": {
        "fast_backend": "linux_lo_pdf",
        "reference_backend": "linux_lo_pdf",
    },
}

config = ExperimentConfig.model_validate(config_dict)

print(f"Config: use_html_codegen={config.use_html_codegen}")
print(f"Starting run for Attention case...")

runner = RunManager(
    config=config,
    cases_dir="cases",
    base_dir="runs",
)

try:
    summaries = runner.run("pb_ICLR_2025_Attention_as_a_Hypernetwork")
    print(f"\n{'='*60}")
    print(f"DONE — {len(summaries)} turns completed")
    for s in summaries:
        print(f"  Turn {s.turn_index}: {s.issues_found} issues found")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
