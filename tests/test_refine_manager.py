"""Smoke tests for RefineManager."""
import os
from pathlib import Path

import pytest

from app.orchestrator.refine_manager import RefineManager


def test_init(tmp_path):
    pptx_path = Path(os.environ.get(
        "REDECK_REAL_PPTX",
        Path(__file__).resolve().parent.parent / "final_merged.pptx",
    ))
    if not pptx_path.exists():
        pytest.skip("final_merged.pptx not available")
    mgr = RefineManager(pptx_path=pptx_path, output_dir=tmp_path / "refine_out", max_turns=1)
    assert mgr.pptx_path == pptx_path
    assert mgr.max_turns == 1
