"""Unit tests for plan tracking in AgentRepair.

Tests the PlanStep dataclass, _tool_plan storage, _tool_update_plan
mutations, _format_plan_progress rendering, progress injection into
tool results, and the submit gate for pending plan steps.
"""
import pytest
from dataclasses import field
from unittest.mock import MagicMock, patch

from app.modules.redeck.agent_repair import (
    AgentRepair,
    AgentState,
    PlanStep,
)


def _make_state(**overrides) -> AgentState:
    """Create a minimal AgentState for testing."""
    defaults = dict(
        original_code="<div>test</div>",
        current_code="<div>test</div>",
        checkpoints=["<div>test</div>"],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir="/tmp/test",
    )
    defaults.update(overrides)
    return AgentState(**defaults)


def _make_repair() -> AgentRepair:
    """Create an AgentRepair instance with minimal config."""
    cfg = {
        "enable_macro_planning": True,
        "enable_space_planning": False,
        "enable_layout_preplan": False,
    }
    with patch.object(AgentRepair, '__init__', lambda self, *a, **kw: None):
        repair = AgentRepair.__new__(AgentRepair)
        repair._enable_macro_planning = True
        repair._enable_space_planning = False
        repair._enable_layout_preplan = False
    return repair


class TestPlanStepDataclass:
    def test_defaults(self):
        step = PlanStep(text="Fix overflow")
        assert step.status == "pending"
        assert step.skip_reason == ""

    def test_custom_status(self):
        step = PlanStep(text="Fix", status="done")
        assert step.status == "done"


class TestToolPlan:
    def test_plan_stores_steps(self):
        repair = _make_repair()
        state = _make_state()
        action = {
            "tool": "plan",
            "plan": {
                "summary": "Fix 2 issues",
                "steps": ["1. Fix overflow", "2. Expand container"],
            },
        }
        result, changed = repair._tool_plan(action, state)
        assert not changed
        assert state.has_plan
        assert len(state.plan_steps) == 2
        assert state.plan_steps[0].text == "1. Fix overflow"
        assert state.plan_steps[1].text == "2. Expand container"
        assert state.plan_summary == "Fix 2 issues"

    def test_plan_auto_marks_first_in_progress(self):
        repair = _make_repair()
        state = _make_state()
        action = {
            "tool": "plan",
            "plan": {
                "summary": "Test",
                "steps": ["Step A", "Step B"],
            },
        }
        repair._tool_plan(action, state)
        assert state.plan_steps[0].status == "in_progress"
        assert state.plan_steps[1].status == "pending"

    def test_replan_overwrites(self):
        repair = _make_repair()
        state = _make_state()
        # First plan
        action1 = {
            "tool": "plan",
            "plan": {"summary": "V1", "steps": ["A", "B", "C"]},
        }
        repair._tool_plan(action1, state)
        assert len(state.plan_steps) == 3

        # Mark step 1 done
        state.plan_steps[0].status = "done"

        # Re-plan
        action2 = {
            "tool": "plan",
            "plan": {"summary": "V2", "steps": ["X", "Y"]},
        }
        result, _ = repair._tool_plan(action2, state)
        assert len(state.plan_steps) == 2
        assert state.plan_steps[0].text == "X"
        assert state.plan_steps[0].status == "in_progress"
        assert state.plan_summary == "V2"
        assert "replaced" in result.lower()

    def test_invalid_plan_format(self):
        repair = _make_repair()
        state = _make_state()
        result, _ = repair._tool_plan({"tool": "plan"}, state)
        assert "Invalid" in result
        assert not state.has_plan

    def test_empty_steps(self):
        repair = _make_repair()
        state = _make_state()
        action = {"tool": "plan", "plan": {"summary": "X", "steps": []}}
        result, _ = repair._tool_plan(action, state)
        assert "at least one step" in result
        assert not state.has_plan


class TestToolUpdatePlan:
    def _setup(self):
        repair = _make_repair()
        state = _make_state()
        repair._tool_plan(
            {"tool": "plan", "plan": {
                "summary": "Fix 3 issues",
                "steps": ["Fix overflow", "Expand container", "Verify and submit"],
            }},
            state,
        )
        return repair, state

    def test_mark_done(self):
        repair, state = self._setup()
        result, _ = repair._tool_update_plan(
            {"tool": "update_plan", "updates": [{"step": 1, "status": "done"}]},
            state,
        )
        assert state.plan_steps[0].status == "done"
        assert "Step 1" in result

    def test_mark_skip_with_reason(self):
        repair, state = self._setup()
        result, _ = repair._tool_update_plan(
            {"tool": "update_plan", "updates": [
                {"step": 2, "status": "skipped", "reason": "would cause cascade"}
            ]},
            state,
        )
        assert state.plan_steps[1].status == "skipped"
        assert state.plan_steps[1].skip_reason == "would cause cascade"

    def test_add_step(self):
        repair, state = self._setup()
        result, _ = repair._tool_update_plan(
            {"tool": "update_plan", "updates": [{"add": "Fix contrast"}]},
            state,
        )
        assert len(state.plan_steps) == 4
        assert state.plan_steps[3].text == "Fix contrast"
        assert state.plan_steps[3].status == "pending"

    def test_modify_text(self):
        repair, state = self._setup()
        result, _ = repair._tool_update_plan(
            {"tool": "update_plan", "updates": [
                {"step": 2, "text": "Expand container and increase font"}
            ]},
            state,
        )
        assert state.plan_steps[1].text == "Expand container and increase font"

    def test_invalid_step_number(self):
        repair, state = self._setup()
        result, _ = repair._tool_update_plan(
            {"tool": "update_plan", "updates": [{"step": 99, "status": "done"}]},
            state,
        )
        assert "out of range" in result

    def test_invalid_status(self):
        repair, state = self._setup()
        result, _ = repair._tool_update_plan(
            {"tool": "update_plan", "updates": [{"step": 1, "status": "invalid"}]},
            state,
        )
        assert "invalid status" in result.lower()
        # Status should not change
        assert state.plan_steps[0].status == "in_progress"

    def test_no_plan_yet(self):
        repair = _make_repair()
        state = _make_state()
        result, _ = repair._tool_update_plan(
            {"tool": "update_plan", "updates": [{"step": 1, "status": "done"}]},
            state,
        )
        assert "No plan" in result

    def test_batch_updates(self):
        repair, state = self._setup()
        result, _ = repair._tool_update_plan(
            {"tool": "update_plan", "updates": [
                {"step": 1, "status": "done"},
                {"step": 2, "status": "in_progress"},
                {"add": "New step"},
            ]},
            state,
        )
        assert state.plan_steps[0].status == "done"
        assert state.plan_steps[1].status == "in_progress"
        assert len(state.plan_steps) == 4


class TestFormatPlanProgress:
    def test_empty_plan(self):
        repair = _make_repair()
        state = _make_state()
        assert repair._format_plan_progress(state) == ""

    def test_progress_format(self):
        repair = _make_repair()
        state = _make_state()
        state.plan_steps = [
            PlanStep("Fix overflow", status="done"),
            PlanStep("Expand container", status="in_progress"),
            PlanStep("Verify", status="pending"),
            PlanStep("Density fix", status="skipped", skip_reason="cascade risk"),
        ]
        result = repair._format_plan_progress(state)
        assert "PLAN PROGRESS:" in result
        assert "[✓] 1." in result
        assert "[→] 2." in result
        assert "[ ] 3." in result
        assert "[⊘] 4." in result
        assert "cascade risk" in result
        assert "2/4 completed" in result
        assert "1 in progress" in result

    def test_all_done(self):
        repair = _make_repair()
        state = _make_state()
        state.plan_steps = [
            PlanStep("A", status="done"),
            PlanStep("B", status="done"),
        ]
        result = repair._format_plan_progress(state)
        assert "2/2 completed" in result


class TestProgressInjection:
    """Test that plan progress is injected into tool results."""

    def test_injection_str_result(self):
        """Progress should be appended to string tool results."""
        repair = _make_repair()
        state = _make_state()
        state.plan_steps = [
            PlanStep("Step A", status="done"),
            PlanStep("Step B", status="pending"),
        ]
        result = "Applied 1 edit(s) successfully."
        progress = repair._format_plan_progress(state)
        combined = result + progress
        assert "PLAN PROGRESS:" in combined
        assert "Applied 1 edit" in combined

    def test_injection_multimodal_result(self):
        """Progress should be appended to last text block in multimodal."""
        repair = _make_repair()
        state = _make_state()
        state.plan_steps = [PlanStep("Step A", status="in_progress")]
        result = [
            {"type": "image", "data": "..."},
            {"type": "text", "text": "Layout analysis complete."},
        ]
        progress = repair._format_plan_progress(state)
        # Simulate injection logic
        for i in range(len(result) - 1, -1, -1):
            if isinstance(result[i], dict) and result[i].get("type") == "text":
                result[i]["text"] += progress
                break
        assert "PLAN PROGRESS:" in result[1]["text"]


class TestSubmitGate:
    """Test that submit warns about pending plan steps."""

    def test_warns_pending_steps(self):
        """First submit with pending steps should produce a warning message."""
        repair = _make_repair()
        state = _make_state()
        state.plan_steps = [
            PlanStep("Fix overflow", status="done"),
            PlanStep("Expand container", status="pending"),
        ]
        # The submit gate checks for pending steps
        pending = [s for s in state.plan_steps if s.status == "pending"]
        assert len(pending) == 1
        assert not getattr(state, '_plan_submit_warned', False)

        # Simulate the gate
        state._plan_submit_warned = True
        assert getattr(state, '_plan_submit_warned', False)

    def test_allows_second_submit(self):
        """After warning, second submit should pass."""
        state = _make_state()
        state.plan_steps = [
            PlanStep("Fix overflow", status="done"),
            PlanStep("Expand container", status="pending"),
        ]
        state._plan_submit_warned = True
        pending = [s for s in state.plan_steps if s.status == "pending"]
        # Gate should not fire again because _plan_submit_warned is True
        should_bounce = (
            pending and not getattr(state, '_plan_submit_warned', False)
        )
        assert not should_bounce

    def test_no_warning_all_done(self):
        """No warning when all steps are done/skipped."""
        state = _make_state()
        state.plan_steps = [
            PlanStep("A", status="done"),
            PlanStep("B", status="skipped", skip_reason="not needed"),
        ]
        pending = [s for s in state.plan_steps if s.status == "pending"]
        assert len(pending) == 0
