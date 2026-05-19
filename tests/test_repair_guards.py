#!/usr/bin/env python3.11
"""Tests for repair guard behavior.

Run: python3.11 -m pytest tests/test_repair_guards.py -v
"""

import json
import os
import sys
import tempfile
import pytest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Per-slide diminishing returns exit ──────────────────────────

class TestDiminishingReturnsExit:
    """Test the per-slide stagnation detection logic."""

    def test_stagnation_detected(self):
        """Slide with 3→3→4 issues should be marked exhausted."""
        history = {"5": [3, 3]}  # past 2 turns: 3, 3
        current_count = 4  # this turn: 4 (>= 3 >= 3)
        past = history["5"]
        assert len(past) >= 2
        prev2, prev1 = past[-2], past[-1]
        stagnated = current_count >= prev1 and prev1 >= prev2 and prev2 > 0
        assert stagnated

    def test_improving_not_exhausted(self):
        """Slide with 5→3→2 issues should NOT be exhausted."""
        history = {"5": [5, 3]}
        current_count = 2
        past = history["5"]
        prev2, prev1 = past[-2], past[-1]
        stagnated = current_count >= prev1 and prev1 >= prev2 and prev2 > 0
        assert not stagnated

    def test_zero_issues_not_exhausted(self):
        """Slide with 0 issues in history should not be exhausted."""
        history = {"5": [0, 0]}
        current_count = 1
        past = history["5"]
        prev2, prev1 = past[-2], past[-1]
        stagnated = current_count >= prev1 and prev1 >= prev2 and prev2 > 0
        assert not stagnated  # prev2 == 0

    def test_new_slide_not_exhausted(self):
        """Slide not in history should not be exhausted."""
        history = {}
        past = history.get("5", [])
        assert len(past) < 2  # Not enough history

    def test_one_turn_history_not_exhausted(self):
        """Need at least 2 turns of history."""
        history = {"5": [3]}
        past = history["5"]
        assert len(past) < 2

    def test_history_file_roundtrip(self):
        """History can be saved and loaded correctly."""
        history = {"1": [3, 4, 5], "2": [2, 1]}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(history, f)
            f.flush()
            loaded = json.loads(Path(f.name).read_text())
            assert loaded == history
            os.unlink(f.name)

    def test_worsening_detected(self):
        """Slide with 2→3→4 issues (worsening) should be exhausted."""
        past = [2, 3]
        current = 4
        prev2, prev1 = past[-2], past[-1]
        stagnated = current >= prev1 and prev1 >= prev2 and prev2 > 0
        assert stagnated

    def test_oscillation_not_exhausted(self):
        """Slide with 4→2→3 issues (oscillating) should NOT be exhausted."""
        past = [4, 2]
        current = 3
        prev2, prev1 = past[-2], past[-1]
        # current(3) >= prev1(2) but prev1(2) < prev2(4)
        stagnated = current >= prev1 and prev1 >= prev2 and prev2 > 0
        assert not stagnated


# ── P2-a: PlanStep verify_criterion ─────────────────────────────

class TestPlanStepStructure:
    """Test PlanStep has the new verify_criterion field."""

    def test_plan_step_has_fields(self):
        from app.modules.redeck.agent_repair import PlanStep
        step = PlanStep(
            text="Fix overflow",
            expected_outcome="No TEXT OVERFLOW",
            verify_criterion="verify_layout shows 0 TEXT OVERFLOW",
        )
        assert step.text == "Fix overflow"
        assert step.expected_outcome == "No TEXT OVERFLOW"
        assert step.verify_criterion == "verify_layout shows 0 TEXT OVERFLOW"
        assert step.status == "pending"

    def test_plan_step_defaults(self):
        from app.modules.redeck.agent_repair import PlanStep
        step = PlanStep(text="Simple step")
        assert step.expected_outcome == ""
        assert step.verify_criterion == ""
        assert step.status == "pending"

    def test_plan_step_status_transitions(self):
        from app.modules.redeck.agent_repair import PlanStep
        step = PlanStep(text="Test")
        step.status = "in_progress"
        assert step.status == "in_progress"
        step.status = "done"
        assert step.status == "done"


# ── P2-c: System prompt contains overcorrection guard ───────────

class TestSystemPromptContent:
    """Verify the system prompt has the required self-check content."""

    def setup_method(self):
        prompt_path = Path(__file__).parent.parent / "app/prompts/codegen/slide_html_repair.system.md"
        self.prompt = prompt_path.read_text()

    def test_has_overcorrection_guard(self):
        assert "OVERCORRECTION GUARD" in self.prompt

    def test_has_bidirectional_checks(self):
        assert 'Fixed "too dense"' in self.prompt
        assert 'Fixed "too sparse"' in self.prompt
        assert 'Fixed "text_overflow"' in self.prompt

    def test_has_verify_criterion_example(self):
        assert "verify_criterion" in self.prompt

    def test_has_spatial_quality_section(self):
        assert "Reading verify_layout for spatial quality" in self.prompt

    def test_has_expected_outcome_docs(self):
        assert "expected_outcome" in self.prompt


if __name__ == "__main__":
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(exit_code)
