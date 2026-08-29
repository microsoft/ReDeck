#!/usr/bin/env python3.11
"""Tests for P0/P2 implementations:
- P0-a: Per-slide diminishing returns exit
- P0-b: Text content retention gate
- P2-a: PlanStep verify_criterion
- P2-b: verify_layout target reminder (already tested implicitly)

Run: python3.11 -m pytest tests/test_repair_guards.py -v
"""

import json
import os
import sys
import tempfile
import pytest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── P0-b: Text retention gate REMOVED ─────────────────────────
# The word-count retention gate was removed because it treats
# content *replacement* (fixing fabricated claims) the same as
# content *deletion*, silently rejecting valid repairs.
# Coverage-drop and spatial-regression gates already catch real
# over-deletion.  Tests for _count_visible_words removed.


# ── P0-a: Per-slide diminishing returns exit ────────────────────


def test_code_change_invalidates_stale_verify_state():
    from app.modules.redeck.agent_repair import AgentRepair

    state = SimpleNamespace(
        layout_revision=3,
        last_verify_revision=3,
        last_verify_stale_reason="",
        last_verify_result={"t1_total": 2},
        _last_verify_text_regression=True,
        _last_verify_text_signal=True,
        _last_verify_text_signal_reason="visible-token order changed",
        _last_verify_spatial_regression_total=4,
        _last_verify_targeted_residual_total=5,
        _last_verify_compact_issues=6,
        _last_html_state=object(),
        spatial_regression_streak=2,
        last_spatial_regression_signature=("interaction:overlap",),
    )

    AgentRepair._invalidate_verify_after_code_change(state, "rollback changed code")

    assert state.layout_revision == 4
    assert state.last_verify_revision == -1
    assert state.last_verify_stale_reason == "rollback changed code"
    assert state.last_verify_result is None
    assert state._last_verify_text_regression is False
    assert state._last_verify_text_signal is False
    assert state._last_verify_text_signal_reason == ""
    assert state._last_verify_spatial_regression_total == 0
    assert state._last_verify_targeted_residual_total == 0
    assert state.last_verify_targeted_residual_counts == {}
    assert state._last_verify_compact_issues == 0
    assert state._last_html_state is None
    assert state.spatial_regression_streak == 0
    assert state.last_spatial_regression_signature == ()


def test_summary_cannot_justify_named_region_clipping_as_a_pass(tmp_path):
    from app.modules.redeck.agent_repair import AgentRepair
    from app.schemas.common import Severity
    from app.schemas.issue import Issue

    repair = AgentRepair(MagicMock())
    repair._current_issues = [Issue(
        issue_id="B04_slide1",
        rubric_id="B04",
        issue_type="text_overflow",
        severity=Severity.MAJOR,
        affected_slides=[1],
    )]
    state = SimpleNamespace(
        current_code="<html>edited</html>",
        original_code="<html>original</html>",
        last_verify_result={"t1_total": 1},
        last_verify_revision=1,
        layout_revision=1,
        last_verify_stale_reason="",
        _last_verify_targeted_residual_total=1,
        last_verify_targeted_residual_counts={"clipped": 1},
        repair_summary=None,
    )
    action = {
        "issues_targeted": ["B04_slide1"],
        "actions_taken": ["Tried a regional reflow and rolled it back."],
        "self_assessment": (
            "A stronger strategy failed and no credible alternative remains, "
            "so the residual is unavoidable."
        ),
        "confidence": "medium",
        "unresolved_concerns": [],
    }

    message, changed = repair._tool_submit_repair_summary(
        action, state, 1, str(tmp_path), 1,
    )

    assert changed is False
    assert "objective visibility failure" in message
    assert "clipped=1" in message


def test_equal_verify_counts_with_changing_signatures_do_not_reconsider():
    from app.modules.redeck.agent_repair import AgentRepair

    assert not AgentRepair._verify_needs_strategy_reconsideration(
        [3, 3, 3],
        ["overlap:a-b", "overflow:c", "clip:d"],
    )


def test_three_identical_verify_signatures_reconsider_strategy():
    from app.modules.redeck.agent_repair import AgentRepair

    assert AgentRepair._verify_needs_strategy_reconsideration(
        [3, 3, 3],
        ["overlap:a-b", "overlap:a-b", "overlap:a-b"],
    )


def test_strictly_worsening_verify_counts_reconsider_strategy():
    from app.modules.redeck.agent_repair import AgentRepair

    assert AgentRepair._verify_needs_strategy_reconsideration(
        [1, 2, 3],
        ["overlap:a-b", "overflow:c", "clip:d"],
    )


def test_stagnation_guidance_does_not_equate_persistence_with_topology_failure():
    source = Path("app/modules/redeck/agent_repair.py").read_text()

    assert "This does not by itself" in source
    assert "show that the current topology is wrong" in source
    assert "edits between these verifies actually changed that region" in source
    assert "a vertical stack into side-by-side columns" in source
    assert "Re-read the render and original issue" not in source


def test_update_plan_warns_when_verify_is_stale_after_edit():
    from app.modules.redeck.agent_repair import AgentRepair, PlanStep

    repair = object.__new__(AgentRepair)
    state = SimpleNamespace(
        plan_steps=[PlanStep(text="Fix crowded lower table", status="in_progress")],
        current_code="<html>edited</html>",
        original_code="<html>original</html>",
        last_verify_result={"t1_total": 0},
        layout_revision=2,
        last_verify_revision=1,
        last_verify_stale_reason="apply_edits changed code",
    )

    feedback, ok = repair._tool_update_plan(
        {"updates": [{"step": 1, "status": "done"}]},
        state,
    )

    assert ok is False
    assert "no current verify_layout" in feedback
    assert "apply_edits changed code" in feedback


def test_update_plan_rejects_skip_when_verify_is_stale_after_rollback():
    from app.modules.redeck.agent_repair import AgentRepair, PlanStep

    repair = object.__new__(AgentRepair)
    state = SimpleNamespace(
        plan_steps=[PlanStep(text="[same-topology calibration] fit table rows")],
        current_code="<html>original</html>",
        original_code="<html>original</html>",
        last_verify_result=None,
        layout_revision=3,
        last_verify_revision=-1,
        last_verify_stale_reason="rollback changed code",
    )

    feedback, ok = repair._tool_update_plan(
        {"updates": [{"step": 1, "status": "skipped"}]},
        state,
    )

    assert ok is False
    assert "skip not applied" in feedback
    assert "rollback changed code" in feedback
    assert state.plan_steps[0].status == "pending"


def test_update_plan_rejects_core_skip_without_replacement_when_residuals_remain():
    from app.modules.redeck.agent_repair import AgentRepair, PlanStep

    repair = object.__new__(AgentRepair)
    state = SimpleNamespace(
        plan_steps=[PlanStep(text="[same-topology calibration] fit table rows")],
        current_code="<html>edited</html>",
        original_code="<html>original</html>",
        last_verify_result={"t1_total": 30},
        layout_revision=3,
        last_verify_revision=3,
        last_verify_stale_reason="",
        _last_verify_targeted_residual_total=30,
    )

    feedback, ok = repair._tool_update_plan(
        {"updates": [{"step": 1, "status": "skipped"}]},
        state,
    )

    assert ok is False
    assert "skip not applied" in feedback
    assert "30 targeted residual" in feedback
    assert state.plan_steps[0].status == "pending"


def test_update_plan_accepts_structured_replacement_step_in_same_call():
    from app.modules.redeck.agent_repair import AgentRepair, PlanStep

    repair = object.__new__(AgentRepair)
    state = SimpleNamespace(
        plan_steps=[PlanStep(text="[dashboard-fit] fit repeated cards")],
        plan_summary="Repair repeated card pressure.",
        current_code="<html>edited</html>",
        original_code="<html>original</html>",
        last_verify_result={"t1_total": 24},
        layout_revision=3,
        last_verify_revision=3,
        last_verify_stale_reason="",
        _last_verify_targeted_residual_total=24,
        issue_types=set(),
    )

    feedback, ok = repair._tool_update_plan({
        "updates": [{"step": 1, "status": "skipped"}],
        "new_steps": [{
            "action": "[body recompose] preserve peers in a stronger allocation",
            "expected_outcome": "All peer roles remain visible.",
            "verify_criterion": "Peer descendants stay inside their owners.",
        }],
    }, state)

    assert ok is False
    assert state.plan_steps[0].status == "skipped"
    assert len(state.plan_steps) == 2
    assert state.plan_steps[1].text.startswith("[body recompose]")
    assert state.plan_steps[1].expected_outcome == "All peer roles remain visible."
    assert state.plan_steps[1].verify_criterion == (
        "Peer descendants stay inside their owners."
    )
    assert "Added step 2" in feedback


def test_apply_edits_accepts_broad_structural_html_batch_with_advisory():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    css = "\n".join(
        f".r{i}{{height:{100 + i}px;}}" for i in range(7)
    )
    state = SimpleNamespace(
        current_code=f"<!DOCTYPE html><html><head><style>{css}</style></head><body></body></html>",
        issue_types={"text_overflow"},
        codegen_compiler=None,
        case_dir="",
        slide_id=1,
        cumulative_words_lost=0,
        allow_visible_text_change=False,
        text_loss_locked=False,
        text_loss_budget=4,
        checkpoints=[],
        checkpoint_text_loss=[],
        layout_revision=0,
        attempted_code_change=False,
        last_verify_revision=-1,
        last_verify_result=None,
        last_verify_stale_reason="",
    )
    edits = [
        {
            "search": f".r{i}{{height:{100 + i}px;}}",
            "replace": f".r{i}{{height:{90 + i}px;}}",
        }
        for i in range(7)
    ]

    feedback, ok = repair._tool_apply_edits(
        {"edits": edits},
        state,
    )

    assert ok is True
    assert "Applied 7 edit(s) successfully" in feedback
    assert "BROAD EDIT ADVISORY" in feedback
    assert "guidance, not a request to undo the edit" in feedback
    assert ".r0{height:90px;}" in state.current_code


def test_apply_edits_rejects_oversized_batch_without_partial_prefix():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    css = "".join(f".r{i}{{height:{i}px}}" for i in range(25))
    code = f"<!DOCTYPE html><style>{css}</style>"
    repair = AgentRepair(MagicMock(), repair_config={"max_edits_per_call": 24})
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )
    edits = [
        {
            "search": f".r{i}{{height:{i}px}}",
            "replace": f".r{i}{{height:{i + 1}px}}",
        }
        for i in range(25)
    ]

    message, changed = repair._tool_apply_edits({"edits": edits}, state)

    assert changed is False
    assert "EDIT BATCH NOT APPLIED" in message
    assert "No partial prefix was applied" in message
    assert state.current_code == code
    repair._test_compile.assert_not_called()


def test_coupled_edit_batches_keep_scope_until_coherent_checkpoint():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = (
        "<!DOCTYPE html><style>"
        ".content{height:500px}.table-wrap{height:300px}"
        "</style>"
    )
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )

    first_message, first_changed = repair._tool_apply_edits({
        "cluster_complete": False,
        "edits": [{
            "search": ".content{height:500px}",
            "replace": ".content{height:480px}",
        }],
    }, state)

    assert first_changed is True
    assert state.pending_edit_cluster is True
    assert state.last_edit_scope == (".content",)
    assert "unfinished coupled edit cluster" in first_message

    second_message, second_changed = repair._tool_apply_edits({
        "cluster_complete": True,
        "edits": [{
            "search": ".table-wrap{height:300px}",
            "replace": ".table-wrap{height:280px}",
        }],
    }, state)

    assert second_changed is True
    assert state.pending_edit_cluster is False
    assert state.last_edit_scope == (".content", ".table-wrap")
    assert "checkpoint marked complete" in second_message


def test_rejected_text_loss_does_not_lock_later_dom_reflow():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = (
        "<!DOCTYPE html><body><section class='summary'>"
        "<p>Strategic implication for deployment planning</p>"
        "</section></body>"
    )
    repair = AgentRepair(MagicMock(), repair_config={"text_loss_budget": 0})
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        text_loss_budget=0,
    )

    message, changed = repair._tool_apply_edits({
        "edits": [{
            "search": "<p>Strategic implication for deployment planning</p>",
            "replace": "",
        }],
    }, state)

    assert changed is False
    assert "DOM reflow remains available" in message
    assert state.text_loss_locked is False
    assert state.current_code == code


def test_changed_css_properties_ignore_unchanged_shifted_declarations():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {
            "search": """
  .hero{
    padding:18px 20px;
    position:relative;
    overflow:hidden;
  }
  .hero .big{
    font-size:92px;
    line-height:.9;
    font-weight:900;
    margin-top:10px;
    color:var(--ink);
    /* old diagnostic comment */
  }
""",
            "replace": """
  .hero{
    padding:14px 16px;
    position:relative;
    overflow:hidden;
  }
  .hero .big{
    font-size:64px;
    line-height:.88;
    font-weight:900;
    margin-top:6px;
    color:var(--ink);
  }
""",
        }
    ]

    props = AgentRepair._changed_css_properties_from_edits(edits)

    assert {"padding", "font-size", "line-height", "margin-top"} <= props
    assert "position" not in props
    assert "overflow" not in props
    assert "font-weight" not in props
    assert "color" not in props


def test_dashboard_coupled_css_batch_not_blocked_by_unchanged_selectors():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {
            "search": """
  .table-card{
    padding:18px 18px 14px 18px;
    display:flex;
    flex-direction:column;
    min-height:0;
  }
""",
            "replace": """
  .table-card{
    padding:14px 16px 10px 16px;
    display:flex;
    flex-direction:column;
    min-height:0;
  }
""",
        },
        {
            "search": """
  .table-wrap{
    border-radius:18px;
    overflow:hidden;
    height:390px;
    /* old diagnostic comment */
  }
""",
            "replace": """
  .table-wrap{
    border-radius:18px;
    overflow:hidden;
    height:320px;
  }
""",
        },
        {
            "search": """
  thead th{
    font-size:15px;
    padding:14px 14px;
  }
  tbody td{
    padding:15px 14px;
    font-size:16px;
    vertical-align:top;
  }
""",
            "replace": """
  thead th{
    font-size:13px;
    padding:8px 10px;
    line-height:1.15;
  }
  tbody td{
    padding:8px 10px;
    font-size:13px;
    line-height:1.2;
    vertical-align:top;
  }
""",
        },
        {
            "search": ".notes{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}",
            "replace": ".notes{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}",
        },
        {
            "search": ".hero{padding:18px 20px;position:relative;overflow:hidden}.hero .big{font-size:92px;line-height:.9}",
            "replace": ".hero{padding:14px 16px;position:relative;overflow:hidden}.hero .big{font-size:64px;line-height:.88}",
        },
        {
            "search": ".summary{padding:18px;display:flex}.summary-box .text{font-size:28px;line-height:1.03}",
            "replace": ".summary{padding:12px;display:flex}.summary-box .text{font-size:20px;line-height:1.05}",
        },
        {
            "search": ".ranking li{display:flex;padding:11px 0;font-size:17px}",
            "replace": ".ranking li{display:flex;padding:7px 0;font-size:15px}",
        },
    ]

    feedback = AgentRepair._broad_structural_html_edit_message(
        edits,
        _dashboard_pressure_state(),
    )

    assert "BROAD EDIT ADVISORY" in feedback
    assert "accepted checkpoint" in feedback
    assert "not a request to undo the edit" in feedback



def test_dashboard_pressure_allows_coupled_css_calibration_with_pill_flex_sizing():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {"search": ".table-wrap{height:390px}", "replace": ".table-wrap{height:352px}"},
        {"search": "thead th{font-size:15px;padding:14px}", "replace": "thead th{font-size:14px;padding:10px;line-height:1.15}"},
        {"search": "tbody td{font-size:16px;padding:15px}", "replace": "tbody td{font-size:13px;padding:8px;line-height:1.16}"},
        {"search": ".notes{gap:14px;margin-top:16px}.mini{padding:14px 16px}", "replace": ".notes{gap:10px;margin-top:10px}.mini{padding:10px 12px}"},
        {"search": ".side{grid-template-rows:160px 170px 1fr;gap:18px}", "replace": ".side{grid-template-rows:136px 150px 1fr;gap:12px}"},
        {"search": ".hero .big{font-size:92px;line-height:.9}.hero .desc{bottom:16px;left:20px;right:20px}", "replace": ".hero .big{font-size:72px;line-height:.88}.hero .desc{bottom:12px;left:18px;right:18px}"},
        {"search": ".ranking li{padding:11px 0;font-size:17px}.pill{padding:6px 10px;font-size:13px}", "replace": ".ranking li{padding:8px 0;font-size:15px;gap:10px}.pill{padding:5px 9px;font-size:12px;white-space:nowrap;flex:0 0 auto}"},
        {"search": ".summary-grid{gap:12px}.summary-box .text{font-size:28px;line-height:1.03}", "replace": ".summary-grid{gap:8px}.summary-box .text{font-size:20px;line-height:1.05}"},
    ]

    feedback = AgentRepair._broad_structural_html_edit_message(
        edits,
        _dashboard_pressure_state(),
    )

    assert "BROAD EDIT ADVISORY" in feedback
    assert "causal hypothesis" in feedback
    assert "not a request to undo the edit" in feedback


def test_dashboard_pressure_allows_coupled_css_calibration_batch():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {"search": ".table-wrap{height:390px}", "replace": ".table-wrap{height:322px}"},
        {"search": "thead th{font-size:15px;padding:14px}", "replace": "thead th{font-size:12px;padding:7px;line-height:1.1}"},
        {"search": "tbody td{font-size:16px;padding:15px}", "replace": "tbody td{font-size:10px;padding:5px;line-height:1.1}"},
        {"search": ".notes{gap:14px;margin-top:16px}", "replace": ".notes{gap:10px;margin-top:10px}"},
        {"search": ".mini{padding:14px 16px}", "replace": ".mini{padding:8px 10px}"},
        {"search": ".side{grid-template-rows:160px 170px 1fr;gap:18px}", "replace": ".side{grid-template-rows:118px 128px 1fr;gap:8px}"},
        {"search": ".hero .big{font-size:92px;line-height:.9}", "replace": ".hero .big{font-size:58px;line-height:.86}"},
        {"search": ".ranking li{padding:11px 0;font-size:17px}", "replace": ".ranking li{padding:1px 0;font-size:12px}"},
        {"search": ".summary-box .text{font-size:28px;line-height:1.03}", "replace": ".summary-box .text{font-size:14px;line-height:1.02}"},
    ]

    feedback = AgentRepair._broad_structural_html_edit_message(
        edits,
        _dashboard_pressure_state(),
    )

    assert "BROAD EDIT ADVISORY" in feedback
    assert "causal hypothesis" in feedback
    assert "not a request to undo the edit" in feedback


def test_dashboard_pressure_allows_coupled_body_budget_css_batch():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {"search": ".content{height:610px;gap:20px}", "replace": ".content{height:500px;gap:18px}"},
        {"search": ".title{font-size:38px;line-height:1.05}.subtitle{font-size:18px;line-height:1.35}", "replace": ".title{font-size:34px;line-height:1.03}.subtitle{font-size:16px;line-height:1.25}"},
        {"search": ".badge{padding:16px 18px}.footer{bottom:14px}", "replace": ".badge{padding:12px 16px}.footer{bottom:8px}"},
        {"search": ".table-wrap{height:390px}", "replace": ".table-wrap{height:322px}"},
        {"search": "thead th{font-size:15px;padding:14px}tbody td{font-size:16px;padding:15px}", "replace": "thead th{font-size:12px;padding:7px;line-height:1.1}tbody td{font-size:10px;padding:5px;line-height:1.1}"},
        {"search": ".notes{gap:14px;margin-top:16px}.mini{padding:14px 16px}", "replace": ".notes{gap:10px;margin-top:10px}.mini{padding:8px 10px}"},
        {"search": ".side{grid-template-rows:160px 170px 1fr;gap:18px}.hero .big{font-size:92px;line-height:.9}", "replace": ".side{grid-template-rows:118px 128px 1fr;gap:8px}.hero .big{font-size:58px;line-height:.86}"},
        {"search": ".ranking li{padding:11px 0;font-size:17px}.summary-box .text{font-size:28px;line-height:1.03}", "replace": ".ranking li{padding:1px 0;font-size:12px}.summary-box .text{font-size:14px;line-height:1.02}"},
    ]
    state = _dashboard_pressure_state()

    local_first_feedback = AgentRepair._dashboard_local_first_html_edit_message(edits, state)
    broad_feedback = AgentRepair._broad_structural_html_edit_message(edits, state)

    assert "DASHBOARD STRATEGY CUE" in local_first_feedback
    assert "That is allowed" in local_first_feedback
    assert "no required local-first ordering" in local_first_feedback
    assert "BROAD EDIT ADVISORY" in broad_feedback
    assert "not a request to undo the edit" in broad_feedback


def test_dashboard_pressure_allows_same_topology_column_calibration_in_coupled_batch():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {
            "search": ".content{display:grid;grid-template-columns:1.55fr .9fr;gap:20px;height:610px}",
            "replace": ".content{display:grid;grid-template-columns:1.58fr .86fr;gap:18px;height:548px}",
        },
        {"search": ".title{font-size:38px}", "replace": ".title{font-size:34px}"},
        {"search": ".table-wrap{height:390px}", "replace": ".table-wrap{height:322px}"},
        {
            "search": "thead th{font-size:15px;padding:14px}tbody td{font-size:16px;padding:15px}",
            "replace": "thead th{font-size:12px;padding:7px;line-height:1.1}tbody td{font-size:10px;padding:5px;line-height:1.1}",
        },
        {
            "search": ".notes{gap:14px;margin-top:16px}.mini{padding:14px 16px}",
            "replace": ".notes{gap:10px;margin-top:10px}.mini{padding:8px 10px}",
        },
        {
            "search": ".side{grid-template-rows:160px 170px 1fr;gap:18px}.hero .big{font-size:92px}.hero .desc{position:absolute;bottom:16px}",
            "replace": ".side{grid-template-rows:118px 128px 1fr;gap:8px}.hero .big{font-size:58px}.hero .desc{position:static;margin-top:4px}",
        },
        {
            "search": ".ranking li{padding:11px 0;font-size:17px}.summary-box .text{font-size:28px}",
            "replace": ".ranking li{padding:1px 0;font-size:12px}.summary-box .text{font-size:14px}",
        },
    ]
    state = _dashboard_pressure_state()

    local_first_feedback = AgentRepair._dashboard_local_first_html_edit_message(edits, state)
    broad_feedback = AgentRepair._broad_structural_html_edit_message(edits, state)

    assert "DASHBOARD STRATEGY CUE" in local_first_feedback
    assert "That is allowed" in local_first_feedback
    assert "no required local-first ordering" in local_first_feedback
    assert "BROAD EDIT ADVISORY" in broad_feedback
    assert "not a request to undo the edit" in broad_feedback


def test_dashboard_plan_accepts_serial_steps_with_directional_shared_pressure_note():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    state = _dashboard_pressure_state()
    state.has_plan = False
    state.checkpoints = ["<html>original</html>"]
    state.slide_id = 13

    feedback, ok = repair._tool_plan(
        {
            "plan": {
                "summary": "Fix the coupled dashboard cluster in the shared body budget.",
                "steps": [
                        {
                            "action": (
                                "[dashboard-fit] tighten the table rows so the "
                                "clipped rows fit"
                            ),
                    },
                    {
                        "action": (
                            "[dashboard-fit] recalibrate the right rail ranking, "
                            "hero, and summary cards"
                        ),
                    },
                ],
            },
        },
        state,
    )

    assert ok is False
    assert "Plan accepted" in feedback
    assert "DASHBOARD STRATEGY NOTE" in feedback
    assert "independent defects or symptoms of one shared constraint" in feedback
    assert "a serial plan is appropriate" in feedback
    assert "locally improved subregion as provisional" in feedback
    assert "not a requirement to merge the steps or use a fixed topology" in feedback
    assert state.has_plan is True


def test_dashboard_plan_note_only_offers_direction_for_separate_regions():
    from app.modules.redeck.agent_repair import AgentRepair, PlanStep

    state = _dashboard_pressure_state()
    steps = [
        PlanStep(
            text=(
                "[dashboard-fit] tighten the table rows while preserving content"
            )
        ),
        PlanStep(text="[dashboard-fit] compact hero, ranking, and summary cards"),
    ]

    notes = AgentRepair._dashboard_coupled_plan_notes(
        steps, state, "Fix the coupled dashboard cluster",
    )

    assert any("independent defects or symptoms of one shared constraint" in note for note in notes)
    assert any("a serial plan is appropriate" in note for note in notes)
    assert any("locally improved subregion as provisional" in note for note in notes)
    assert any("not a requirement to merge the steps or use a fixed topology" in note for note in notes)


def test_dashboard_plan_accepts_one_coupled_checkpoint_then_verify():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    state = _dashboard_pressure_state()
    state.has_plan = False
    state.checkpoints = ["<html>original</html>"]
    state.slide_id = 13

    feedback, ok = repair._tool_plan(
        {
            "plan": {
                "summary": "Fit the coupled dashboard in one shared body budget.",
                "steps": [
                    {
                        "action": (
                            "[dashboard-fit] in one same-topology checkpoint, "
                            "modestly tighten the header/title/subtitle/content "
                            "budget while calibrating the table frame and row/cell "
                            "rhythm, notes, hero KPI, ranking, and summary rail"
                        ),
                    },
                    {
                        "action": "[verification] verify the full dashboard cluster",
                    },
                ],
            },
        },
        state,
    )

    assert ok is False
    assert "Plan accepted" in feedback
    assert state.has_plan is True
    assert state.plan_steps[0].status == "in_progress"


def test_dashboard_dominant_compression_is_recoverable_inside_loop():
    from app.modules.redeck.agent_repair import AgentRepair

    state = _dashboard_pressure_state()

    assert AgentRepair._is_recoverable_dashboard_dominant_compression(
        state,
        "dominant font shrank 92px->52px (43% reduction)",
    )
    assert not AgentRepair._is_recoverable_dashboard_dominant_compression(
        state,
        "average font size shrank 18px->11px (39% reduction)",
    )


def test_dashboard_plan_accepts_deferred_parent_budget_decision():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    state = _dashboard_pressure_state()
    state.has_plan = False
    state.checkpoints = ["<html>original</html>"]
    state.slide_id = 13

    feedback, ok = repair._tool_plan(
        {
            "plan": {
                "summary": "Fix the coupled dashboard cluster.",
                "steps": [
                    {
                        "action": (
                            "[dashboard-fit] calibrate table rows, notes, hero, "
                            "ranking, and summary cards together"
                        ),
                    },
                    {
                        "action": (
                            "[dashboard-fit] later adjust the parent content track "
                            "height and footer budget if needed"
                        ),
                    },
                ],
            },
        },
        state,
    )

    assert ok is False
    assert "Plan accepted" in feedback
    assert "DASHBOARD PLAN REVISION REQUIRED" not in feedback
    assert state.has_plan is True


def test_dashboard_plan_accepts_split_outer_and_internal_calibration():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    state = _dashboard_pressure_state()
    state.has_plan = False
    state.checkpoints = ["<html>original</html>"]
    state.slide_id = 13

    feedback, ok = repair._tool_plan(
        {
            "plan": {
                "summary": "Fix the coupled dashboard body budget.",
                "steps": [
                    {
                        "action": (
                            "[dashboard-fit] rebalance the content grid and card "
                            "heights for the table and right rail"
                        ),
                    },
                    {
                        "action": (
                            "[dashboard-fit] tighten table row rhythm, notes padding, "
                            "hero, ranking, and summary typography"
                        ),
                    },
                ],
            },
        },
        state,
    )

    assert ok is False
    assert "Plan accepted" in feedback
    assert "same-topology edit" not in feedback
    assert state.has_plan is True



def test_dashboard_pressure_allows_followup_same_cluster_css_reflow_after_verify():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {"search": ".table-wrap{height:320px;overflow:hidden}", "replace": ".table-wrap{height:350px;overflow:auto}"},
        {"search": "table{display:table;width:100%}", "replace": "table{display:table;width:100%;table-layout:fixed}"},
        {"search": "thead th{font-size:13px;padding:8px}", "replace": "thead th{font-size:12px;padding:6px;line-height:1.1}"},
        {"search": ".notes{display:grid;grid-template-columns:1fr 1fr;gap:10px}", "replace": ".notes{display:flex;flex-direction:row;gap:8px}"},
        {"search": ".mini{padding:12px;min-height:90px}", "replace": ".mini{padding:8px;min-height:0}"},
        {"search": ".side{display:grid;grid-template-rows:120px 130px 1fr;gap:10px}", "replace": ".side{display:grid;grid-template-rows:96px 112px 1fr;gap:8px}"},
        {"search": ".hero{display:flex;align-items:center}.ranking li{display:flex;padding:7px 0}", "replace": ".hero{display:flex;align-items:flex-start}.ranking li{display:flex;padding:4px 0}"},
        {"search": ".summary{display:flex;flex-direction:column}.summary-box{padding:12px}", "replace": ".summary{display:grid;grid-template-rows:auto 1fr}.summary-box{padding:8px}"},
    ]
    state = _dashboard_pressure_state(
        attempted_code_change=True,
        layout_revision=1,
        last_verify_revision=1,
        last_verify_result={"t1_total": 57},
        _last_verify_spatial_regression_total=25,
        _last_verify_targeted_residual_total=57,
        checkpoints=["<html>original</html>", "<html>edited</html>"],
    )

    feedback = AgentRepair._broad_structural_html_edit_message(edits, state)

    assert "BROAD EDIT ADVISORY" in feedback
    assert "not a request to undo the edit" in feedback


def test_dashboard_pressure_does_not_block_reflow_without_fresh_verify():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {"search": ".table-wrap{height:320px;overflow:hidden}", "replace": ".table-wrap{height:350px;overflow:auto}"},
        {"search": "table{display:table;width:100%}", "replace": "table{display:table;width:100%;table-layout:fixed}"},
        {"search": "thead th{font-size:13px;padding:8px}", "replace": "thead th{font-size:12px;padding:6px;line-height:1.1}"},
        {"search": ".notes{display:grid;grid-template-columns:1fr 1fr;gap:10px}", "replace": ".notes{display:flex;flex-direction:row;gap:8px}"},
        {"search": ".mini{padding:12px;min-height:90px}", "replace": ".mini{padding:8px;min-height:0}"},
        {"search": ".side{display:grid;grid-template-rows:120px 130px 1fr;gap:10px}", "replace": ".side{display:grid;grid-template-rows:96px 112px 1fr;gap:8px}"},
        {"search": ".hero{display:flex;align-items:center}.ranking li{display:flex;padding:7px 0}", "replace": ".hero{display:flex;align-items:flex-start}.ranking li{display:flex;padding:4px 0}"},
        {"search": ".summary{display:flex;flex-direction:column}.summary-box{padding:12px}", "replace": ".summary{display:grid;grid-template-rows:auto 1fr}.summary-box{padding:8px}"},
    ]

    feedback = AgentRepair._broad_structural_html_edit_message(
        edits,
        _dashboard_pressure_state(),
    )

    assert feedback is not None
    assert "BROAD EDIT ADVISORY" in feedback
    assert "not a request to undo the edit" in feedback
    assert "fresh verify" not in feedback.lower()


def test_dashboard_broad_edit_only_receives_debuggability_advisory():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {"search": ".header{margin-bottom:20px}", "replace": ".header{margin-bottom:10px}"},
        {"search": ".title{font-size:38px}", "replace": ".title{font-size:34px}"},
        {"search": ".subtitle{font-size:18px}", "replace": ".subtitle{font-size:16px}"},
        {"search": ".content{height:596px}", "replace": ".content{height:500px}"},
        {"search": ".side{grid-template-rows:142px 156px 1fr}", "replace": ".side{grid-template-rows:118px 128px 1fr}"},
        {"search": ".hero .big{font-size:72px}", "replace": ".hero .big{font-size:58px}"},
        {"search": ".ranking li{padding:8px 0}", "replace": ".ranking li{padding:1px 0}"},
        {"search": ".summary-box .text{font-size:22px}", "replace": ".summary-box .text{font-size:14px}"},
    ]
    state = _dashboard_pressure_state(
        attempted_code_change=True,
        layout_revision=1,
        last_verify_revision=1,
        last_verify_result={"t1_total": 57},
        _last_verify_spatial_regression_total=13,
        checkpoints=["<html>original</html>", "<html>edited</html>"],
    )

    feedback = AgentRepair._broad_structural_html_edit_message(edits, state)

    assert feedback is not None
    assert "BROAD EDIT ADVISORY" in feedback
    assert "causal hypothesis" in feedback
    assert "A broad edit is appropriate when one coherent reflow requires it" in feedback
    assert "guidance, not a request to undo the edit" in feedback


def test_dashboard_rollback_first_warns_to_try_same_cluster_closure():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    current_html = _dashboard_pressure_state().current_code
    state = _dashboard_pressure_state(
        current_code=current_html,
        original_code="<html>original</html>",
        checkpoints=["<html>original</html>", "<html>original</html>"],
        checkpoint_text_loss=[0, 0],
        cumulative_words_lost=0,
        attempted_code_change=True,
        layout_revision=1,
        last_verify_revision=1,
        last_verify_result={"t1_total": 57},
        _last_verify_spatial_regression_total=25,
        _last_verify_targeted_residual_total=57,
        _last_html_state=object(),
        spatial_regression_streak=1,
        last_spatial_regression_signature=("interaction:overlap",),
    )

    feedback, ok = repair._tool_rollback({"steps": 1}, state)

    assert ok is True
    assert "Rolled back 1 step" in feedback
    assert "DASHBOARD CLOSURE CHECK" not in feedback
    assert "ROLLBACK DEPTH CHECK" in feedback
    assert "roll back farther or replace that strategy's patch" in feedback
    assert state.current_code == "<html>original</html>"
    assert state.current_code == "<html>original</html>"
    assert state.last_verify_revision == -1


@pytest.mark.parametrize(
    "quality_flag",
    ["_last_verify_visual_compression_failed", "_last_verify_scope_failed"],
)
def test_dashboard_rollback_does_not_warn_when_hard_quality_gate_failed(quality_flag):
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    current_html = _dashboard_pressure_state().current_code
    state = _dashboard_pressure_state(
        current_code=current_html,
        original_code="<html>original</html>",
        checkpoints=["<html>original</html>", "<html>original</html>"],
        checkpoint_text_loss=[0, 0],
        cumulative_words_lost=0,
        attempted_code_change=True,
        layout_revision=1,
        last_verify_revision=1,
        last_verify_result={"t1_total": 57},
        _last_verify_spatial_regression_total=25,
        _last_verify_targeted_residual_total=57,
        _last_html_state=object(),
        spatial_regression_streak=1,
        last_spatial_regression_signature=("interaction:overlap",),
        **{quality_flag: True},
    )

    feedback, ok = repair._tool_rollback({"steps": 1}, state)

    assert ok is True
    assert "DASHBOARD CLOSURE CHECK" not in feedback
    assert "Rolled back 1 step" in feedback
    assert "Verify the restored checkpoint" in feedback
    assert "rollback another step" in feedback
    assert state.current_code == "<html>original</html>"
    assert getattr(state, "_dashboard_rollback_caution_used", False) is False


def _dashboard_pressure_state(**overrides):
    html = """
<!DOCTYPE html><html><head><style>
.slide{height:720px}.header{height:100px}.content{height:610px}
.table-wrap{height:390px}.ranking{height:170px}.summary{height:488px}
</style></head><body>
<div class="slide"><div class="header"></div><div class="content">
<div class="table-wrap"><table><tr><td>A</td></tr></table></div>
<div class="ranking"></div><div class="summary"></div>
</div></div></body></html>
"""
    state = SimpleNamespace(
        current_code=html,
        issue_types={"text_overflow", "overlap"},
        attempted_code_change=False,
        layout_revision=0,
        last_verify_revision=-1,
        last_verify_result=None,
        last_verify_stale_reason="",
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_dashboard_pressure_allows_scaffold_edit_with_directional_cue():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [{"search": ".content{height:610px}", "replace": ".content{height:500px}"}]

    feedback = AgentRepair._dashboard_local_first_html_edit_message(
        edits,
        _dashboard_pressure_state(),
    )

    assert feedback is not None
    assert "DASHBOARD STRATEGY CUE" in feedback
    assert "this edit touches surrounding scaffold (.content)" in feedback
    assert "That is allowed" in feedback
    assert "no required local-first ordering" in feedback


def test_dashboard_pressure_initial_message_names_coupled_cluster():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.schemas.common import Confidence, Severity, Verdict
    from app.schemas.issue import Issue, IssueEvidence

    repair = AgentRepair(
        llm=MagicMock(),
        repair_config={
            "enable_space_planning": False,
            "enable_redistrib_guide": False,
        },
    )
    state = _dashboard_pressure_state()
    issue = Issue(
        issue_id="spatial_0",
        rubric_id="B04",
        issue_type="text_overflow",
        severity=Severity.MAJOR,
        confidence=Confidence.HIGH,
        affected_slides=[13],
        evidence=IssueEvidence(description="table rows clipped near the bottom"),
        why_this_fails="hidden table content",
        planned_fix="repair the table/card body pressure",
        verdict=Verdict.FAIL,
    )

    message = repair._build_initial_message(
        code=state.current_code,
        all_issues=[issue],
        spatial_info="SPACE MAP: table and right rail share body height",
        evidence_text="",
        must_contain=[],
        must_not=[],
        content_checklist="",
        bp_slide=None,
        viz_data=None,
        adjacent_context="",
    )

    assert "Current Dashboard Strategy Cue" in message
    assert "hypothesis to inspect, not as a mandatory repair recipe" in message
    assert "role-aware same-topology calibration" in message
    assert "regional/body reflow" in message
    assert "sparse footer as a full-width exclusion band" in message
    assert "Choose the actual selectors, edit scope, ordering, and scale" in message
    assert "No named selector, font size, body height, or one-batch trajectory is required" in message
    assert "Repeated padding, gaps, line-height, and wrapping" in message
    assert "A hypothesis is incomplete when its stated cause was never tested" in message
    assert "anchored child with matching owner inset" in message
    assert "roll back farther or replace that patch before branching" in message
    assert "current HTML/CSS, LAYOUT ANCHOR, RELATION MAP, SPACE MAP" in message
    assert "Worked Golden Checkpoint For This Exact Profile" not in message
    assert "This run is intentionally text/spatial only" in message
    assert "Do not call it" in message
    assert "Detector counts are evidence, not a requirement to reach zero" in message


def test_repeated_card_dashboard_receives_coupled_pressure_guidance():
    from app.modules.redeck.agent_repair import AgentRepair

    code = """
    <html><body>
      <div class="summary"><div class="kpi">Top metric</div></div>
      <div class="mini-chart"></div>
      <div class="bottom">
        <div class="card grid-card"><div class="score"></div><div class="metric-list"></div></div>
        <div class="card grid-card"><div class="score"></div><div class="metric-list"></div></div>
        <div class="card grid-card"><div class="score"></div><div class="metric-list"></div></div>
      </div>
    </body></html>
    """

    assert AgentRepair._looks_like_table_dashboard_pressure_from(
        code,
        {"density_imbalance"},
    )
    guidance = AgentRepair._dashboard_coupled_cluster_guidance(code)
    assert "Parent height, `flex-shrink`, or a grid declaration" in guidance
    assert "Repeated padding, gaps, line-height, and wrapping" in guidance
    assert "minimal reallocation of an existing terminal child" in guidance
    assert "Add wrappers only when" in guidance
    assert "A topology change must improve one complete peer" in guidance
    assert "sparse footer as a full-width exclusion band" in guidance
    assert "whole-slide budget" in guidance
    assert "planned support-copy calibration remains unchanged" in guidance
    assert "explicit owner track" in guidance


def test_dashboard_decision_summary_surfaces_causal_budget_and_completed_hypothesis():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    original = """
    <html><style>
    .grid-card{position:relative;padding:10px}
    .findings{margin-top:10px}
    </style><div class="summary"><div class="kpi">Top</div></div>
    <div class="bottom">
      <div class="card grid-card"><div class="metric-list"><div class="m-note">A long explanatory proposition that wraps over several rendered lines.</div></div><div class="findings">A long terminal recommendation with additional explanatory wording.</div></div>
      <div class="card grid-card"><div class="metric-list"><div class="m-note">Another long explanatory proposition that wraps over several rendered lines.</div></div><div class="findings">Another long terminal recommendation with additional explanatory wording.</div></div>
    </div><div class="footer">Source</div></html>
    """
    current = """
    <html><style>
    .grid-card{position:relative;padding:10px 10px 80px}
    .findings{position:absolute;left:10px;right:10px;bottom:6px}
    </style><div class="summary"><div class="kpi">Top</div></div>
    <div class="bottom">
      <div class="card grid-card"><div class="metric-list"><div class="m-note">Short explanation.</div></div><div class="findings">Short recommendation.</div></div>
      <div class="card grid-card"><div class="metric-list"><div class="m-note">Short explanation.</div></div><div class="findings">Short recommendation.</div></div>
    </div><div class="footer">Source</div></html>
    """

    def measured_state(*, support_lines: int) -> SlideState:
        blocks = [
            ContentBlock(
                block_id="summary", var_name="div", shape_type="shape",
                css_selector=".summary", css_classes=("card", "summary"),
                dom_path="html/body/div[0]", bbox_px=(30, 120, 560, 160),
            ),
            ContentBlock(
                block_id="kpi", var_name="div", shape_type="textbox",
                css_selector=".kpi", css_classes=("kpi",),
                dom_path="html/body/div[0]/div[0]", bbox_px=(50, 180, 160, 130),
                rendered_lines=2, text_lines=["Top"],
            ),
        ]
        for index, left in enumerate((30, 340)):
            path = f"html/body/div[1]/div[{index}]"
            blocks.extend([
                ContentBlock(
                    block_id=f"card_{index}", var_name="div", shape_type="shape",
                    css_selector=".grid-card", css_classes=("card", "grid-card"),
                    dom_path=path, bbox_px=(left, 300, 280, 400),
                ),
                ContentBlock(
                    block_id=f"note_{index}", var_name="div", shape_type="textbox",
                    css_selector=".m-note", css_classes=("m-note",),
                    dom_path=f"{path}/div[0]/div[0]", bbox_px=(left + 12, 560, 256, 70),
                    rendered_lines=support_lines,
                    text_lines=["Support copy"],
                ),
                ContentBlock(
                    block_id=f"findings_{index}", var_name="div", shape_type="textbox",
                    css_selector=".findings", css_classes=("findings",),
                    dom_path=f"{path}/div[1]", bbox_px=(left + 12, 650, 256, 70),
                    rendered_lines=support_lines,
                    text_lines=["Terminal support"],
                ),
            ])
        blocks.append(ContentBlock(
            block_id="footer", var_name="footer", shape_type="textbox",
            css_selector=".footer", css_classes=("footer",),
            dom_path="html/body/div[2]", bbox_px=(36, 700, 1208, 14),
            rendered_lines=1, text_lines=["Source"],
        ))
        return SlideState(slide_id=1, blocks=blocks)

    baseline = measured_state(support_lines=4)
    present = measured_state(support_lines=1)
    state = SimpleNamespace(
        original_code=original,
        current_code=current,
        _t0_html_state=baseline,
    )

    summary = AgentRepair._dashboard_decision_summary(state, present)

    assert summary.startswith("DASHBOARD DECISION SUMMARY")
    assert "one row with 2 peer columns" in summary
    assert "owner height 400px" in summary
    assert "deepest descendant demand 420px" in summary
    assert "Hypothesis completeness:" in summary
    assert "upstream deepest descendant bottom=310px" in summary
    assert "first peer top=300px" in summary
    assert "footer/source top=700px" in summary
    assert "usable peer height 400px" in summary
    assert "owner-vs-usable-height 0px" in summary
    assert "deepest descendant bottom 720px" in summary
    assert "deepest-descendant-vs-footer/source 20px" in summary
    assert "deepest peer descendant crosses the measured footer/source start" in summary
    assert "Direct terminal child: 2/2 cards" in summary
    assert "Terminal ownership implemented: yes" in summary
    assert "anchored child + positioned owner + bottom inset" in summary
    assert "Upper/terminal relation:" in summary
    assert "upper branch demand 330px" in summary
    assert "terminal branch height 70px" in summary
    assert "Support copy materially shortened: yes" in summary
    assert "support roots changed 4/4; unchanged 0" in summary
    assert "Support demand by role:" in summary
    assert "metric explanations: words" in summary
    assert "terminal support: words" in summary
    assert "current per-root lines 1" in summary
    assert "upstream content already enters the peer region" in summary
    assert "not disproved by a checkpoint that never tested" in summary
    assert "DASHBOARD NEXT-DECISION NOTE" in state._dashboard_next_strategy_note
    assert "more total body width" in state._dashboard_next_strategy_note
    assert "upper-role demand (330px)" in state._dashboard_next_strategy_note


def test_dashboard_summary_does_not_call_aggregate_support_relief_effective_when_metric_lines_hold():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    original = """
    <html><div class="bottom">
      <div class="card grid-card">
        <div class="metric-list"><div class="m-note">A verbose metric explanation with removable framing words.</div></div>
        <div class="findings">A verbose terminal recommendation with removable framing words.</div>
      </div>
      <div class="card grid-card">
        <div class="metric-list"><div class="m-note">Another verbose metric explanation with removable framing words.</div></div>
        <div class="findings">Another verbose terminal recommendation with removable framing words.</div>
      </div>
    </div><div class="footer">Source</div></html>
    """
    current = """
    <html><div class="bottom">
      <div class="card grid-card">
        <div class="metric-list"><div class="m-note">Metric explanation with framing.</div></div>
        <div class="findings">Concise recommendation.</div>
      </div>
      <div class="card grid-card">
        <div class="metric-list"><div class="m-note">Another metric explanation with framing.</div></div>
        <div class="findings">Another concise recommendation.</div>
      </div>
    </div><div class="footer">Source</div></html>
    """

    def measured_state(*, metric_lines: int, terminal_lines: int) -> SlideState:
        blocks = []
        for index, left in enumerate((30, 640)):
            card_path = f"html/body/div[0]/div[{index}]"
            blocks.extend([
                ContentBlock(
                    block_id=f"card_{index}", var_name="div", shape_type="shape",
                    css_selector=".grid-card", css_classes=("card", "grid-card"),
                    dom_path=card_path, bbox_px=(left, 300, 580, 380),
                ),
                ContentBlock(
                    block_id=f"note_{index}", var_name="div", shape_type="textbox",
                    css_selector=".m-note", css_classes=("m-note",),
                    dom_path=f"{card_path}/div[0]/div[0]", bbox_px=(left + 20, 480, 540, 60),
                    rendered_lines=metric_lines, font_size_px=13,
                    text_lines=["Metric explanation"],
                ),
                ContentBlock(
                    block_id=f"findings_{index}", var_name="div", shape_type="textbox",
                    css_selector=".findings", css_classes=("findings",),
                    dom_path=f"{card_path}/div[1]", bbox_px=(left + 20, 560, 540, 80),
                    rendered_lines=terminal_lines, font_size_px=13,
                    text_lines=["Terminal recommendation"],
                ),
            ])
        blocks.append(ContentBlock(
            block_id="footer", var_name="footer", shape_type="textbox",
            css_selector=".footer", css_classes=("footer",),
            dom_path="html/body/div[1]", bbox_px=(36, 700, 1208, 14),
            rendered_lines=1, text_lines=["Source"],
        ))
        return SlideState(slide_id=1, blocks=blocks)

    state = SimpleNamespace(
        original_code=original,
        current_code=current,
        _t0_html_state=measured_state(metric_lines=3, terminal_lines=4),
    )
    summary = AgentRepair._dashboard_decision_summary(
        state,
        measured_state(metric_lines=3, terminal_lines=1),
    )

    assert "Support copy materially shortened: partial" in summary
    assert "metric explanations changed without role-level line relief" in summary
    assert "calibration edited, but rendered line demand did not retreat" in summary
    assert "role-level support calibration is ineffective for metric explanations" in summary
    assert "aggregate support reduction do not establish effective calibration" in summary


def test_dashboard_summary_recovers_copy_evidence_after_mixed_checkpoint_rollback():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    original = """
    <html><div class="bottom">
      <div class="card grid-card"><div class="m-note">A long metric explanation.</div><div class="findings">A long terminal recommendation.</div></div>
      <div class="card grid-card"><div class="m-note">Another long metric explanation.</div><div class="findings">Another long terminal recommendation.</div></div>
    </div><div class="footer">Source</div></html>
    """

    def measured_state(lines: int) -> SlideState:
        blocks = []
        for index, left in enumerate((30, 340)):
            card_path = f"html/body/div[0]/div[{index}]"
            blocks.extend([
                ContentBlock(
                    block_id=f"card_{index}", var_name="div", shape_type="shape",
                    css_selector=".grid-card", css_classes=("card", "grid-card"),
                    dom_path=card_path, bbox_px=(left, 300, 280, 380),
                ),
                ContentBlock(
                    block_id=f"note_{index}", var_name="div", shape_type="textbox",
                    css_selector=".m-note", css_classes=("m-note",),
                    dom_path=f"{card_path}/div[0]", bbox_px=(left + 10, 500, 260, 50),
                    rendered_lines=lines, font_size_px=13,
                    text_lines=["Metric explanation"],
                ),
                ContentBlock(
                    block_id=f"findings_{index}", var_name="div", shape_type="textbox",
                    css_selector=".findings", css_classes=("findings",),
                    dom_path=f"{card_path}/div[1]", bbox_px=(left + 10, 580, 260, 70),
                    rendered_lines=lines, font_size_px=13,
                    text_lines=["Terminal recommendation"],
                ),
            ])
        blocks.append(ContentBlock(
            block_id="footer", var_name="footer", shape_type="textbox",
            css_selector=".footer", css_classes=("footer",),
            dom_path="html/body/div[1]", bbox_px=(36, 700, 1208, 14),
            rendered_lines=1, text_lines=["Source"],
        ))
        return SlideState(slide_id=1, blocks=blocks)

    state = SimpleNamespace(
        original_code=original,
        current_code=original,
        _t0_html_state=measured_state(3),
        dashboard_verify_history=[{
            "topology": "one row with 2 peer columns",
            "owner_height": "380px",
            "demand_height": "350px",
            "support_words": 8,
            "support_role_metrics": {
                "metric explanations": {
                    "words": 5,
                    "lines": 6,
                    "calibration": "edited, but rendered line demand did not retreat",
                },
                "terminal support": {
                    "words": 3,
                    "lines": 2,
                    "calibration": "rendered demand reduced",
                },
            },
        }],
    )

    summary = AgentRepair._dashboard_decision_summary(state, measured_state(3))

    assert "Rollback recovery context" in summary
    assert "geometry and copy were rolled back together" in summary
    assert "Reapply transferable copy as a standalone checkpoint" in summary
    assert "before using this restored baseline as evidence against the peer topology" in summary


def test_dashboard_mixed_copy_and_layout_checkpoint_warns_about_recovery():
    from app.modules.redeck.agent_repair import AgentRepair

    before = """
    <html><style>.grid-card{display:block}</style><div class="summary">Overview</div><div class="bottom">
      <div class="card grid-card"><div class="m-note">A verbose support explanation with framing.</div></div>
      <div class="card grid-card"><div class="m-note">Another verbose support explanation with framing.</div></div>
    </div></html>
    """
    after = """
    <html><style>.grid-card{display:flex}</style><div class="summary">Overview</div><div class="bottom">
      <div class="card grid-card"><div class="m-note">Concise explanation.</div></div>
      <div class="card grid-card"><div class="m-note">Another concise explanation.</div></div>
    </div></html>
    """
    state = SimpleNamespace(
        allow_support_copy_compression=True,
        current_code=before,
        issue_types={"density_imbalance"},
    )

    note = AgentRepair._dashboard_support_copy_checkpoint_note(
        state,
        before,
        after,
        cluster_complete=True,
    )

    assert "MIXED CHECKPOINT RECOVERY NOTE" in note
    assert "rollback will discard both" in note
    assert "reapply it as a standalone checkpoint after rollback" in note


def test_dashboard_decision_summary_distinguishes_contained_terminal_from_upper_intersection():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    code = """
    <html><style>
    .grid-card{display:grid;grid-template-rows:minmax(0,1fr) 80px}
    </style><div class="bottom">
      <div class="card grid-card"><div class="card-upper"><div class="m-note">Upper support one.</div></div><div class="findings">Terminal one.</div></div>
      <div class="card grid-card"><div class="card-upper"><div class="m-note">Upper support two.</div></div><div class="findings">Terminal two.</div></div>
    </div><div class="footer">Source</div></html>
    """
    blocks = []
    for index, left in enumerate((30, 340)):
        path = f"html/body/div[0]/div[{index}]"
        blocks.extend([
            ContentBlock(
                block_id=f"card_{index}", var_name="div", shape_type="shape",
                css_selector=".grid-card", css_classes=("card", "grid-card"),
                dom_path=path, bbox_px=(left, 300, 280, 400),
            ),
            ContentBlock(
                block_id=f"upper_{index}", var_name="div", shape_type="shape",
                css_selector=".card-upper", css_classes=("card-upper",),
                dom_path=f"{path}/div[0]", bbox_px=(left + 10, 310, 260, 310),
            ),
            ContentBlock(
                block_id=f"note_{index}", var_name="div", shape_type="textbox",
                css_selector=".m-note", css_classes=("m-note",),
                dom_path=f"{path}/div[0]/div[0]", bbox_px=(left + 20, 590, 240, 60),
                rendered_lines=3, text_lines=["Upper support"],
            ),
            ContentBlock(
                block_id=f"findings_{index}", var_name="div", shape_type="textbox",
                css_selector=".findings", css_classes=("findings",),
                dom_path=f"{path}/div[1]", bbox_px=(left + 10, 620, 260, 70),
                rendered_lines=3, text_lines=["Terminal support"],
            ),
        ])
    blocks.append(ContentBlock(
        block_id="footer", var_name="div", shape_type="textbox",
        css_selector=".footer", css_classes=("footer",),
        dom_path="html/body/div[1]", bbox_px=(36, 700, 1208, 14),
        rendered_lines=1, text_lines=["Source"],
    ))
    measured = SlideState(slide_id=1, blocks=blocks)
    state = SimpleNamespace(
        original_code=code,
        current_code=code,
        _t0_html_state=measured,
        dashboard_verify_history=[],
    )

    first = AgentRepair._dashboard_decision_summary(state, measured)
    second = AgentRepair._dashboard_decision_summary(state, measured)

    assert "Terminal ownership implemented: yes (direct terminal child in an explicit owner track)" in first
    assert "upper branch demand 350px" in first
    assert "terminal branch height 70px" in first
    assert "terminal support is contained by its owners" in first
    assert "upper stack still intersects that support" in first
    assert "before treating the peer organization as failed" in first
    assert "this peer organization was already measured 1 time(s)" in second
    assert "a new plan label alone is not a different strategy" in second


def test_dashboard_decision_summary_compares_detached_support_with_attached_checkpoint():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    attached_code = """
    <html><style>
    .grid-card{display:grid;grid-template-rows:minmax(0,1fr) 80px}
    </style><div class="bottom">
      <div class="card grid-card"><div class="card-upper"><div class="m-note">Compact metric explanation.</div></div><div class="findings">Terminal one.</div></div>
      <div class="card grid-card"><div class="card-upper"><div class="m-note">Compact metric explanation.</div></div><div class="findings">Terminal two.</div></div>
    </div><div class="footer">Source</div></html>
    """
    detached_code = """
    <html><div class="bottom">
      <div class="card grid-card"><div class="card-upper"><div class="m-note">Compact metric explanation.</div></div></div>
      <div class="card grid-card"><div class="card-upper"><div class="m-note">Compact metric explanation.</div></div></div>
    </div><div class="bottom-findings"><div class="findings">Terminal one.</div><div class="findings">Terminal two.</div></div><div class="footer">Source</div></html>
    """

    def measured(*, detached: bool, note_font: float) -> SlideState:
        blocks = []
        for index, left in enumerate((30, 340)):
            card_path = f"html/body/div[0]/div[{index}]"
            blocks.extend([
                ContentBlock(
                    block_id=f"card_{index}", var_name="div", shape_type="shape",
                    css_selector=".grid-card", css_classes=("card", "grid-card"),
                    dom_path=card_path, bbox_px=(left, 300, 280, 300),
                ),
                ContentBlock(
                    block_id=f"note_{index}", var_name="div", shape_type="textbox",
                    css_selector=".m-note", css_classes=("m-note",),
                    dom_path=f"{card_path}/div[0]/div[0]",
                    bbox_px=(left + 12, 500, 256, 30), rendered_lines=2,
                    font_size_px=note_font, text_chars=27,
                    text_lines=["Compact metric explanation"],
                ),
            ])
            findings_path = (
                f"html/body/div[1]/div[{index}]"
                if detached else f"{card_path}/div[1]"
            )
            blocks.append(ContentBlock(
                block_id=f"findings_{index}", var_name="div", shape_type="textbox",
                css_selector=".findings", css_classes=("findings",),
                dom_path=findings_path, bbox_px=(left, 610, 280, 70),
                rendered_lines=2, font_size_px=10, text_chars=13,
                text_lines=["Terminal support"],
            ))
        blocks.append(ContentBlock(
            block_id="footer", var_name="div", shape_type="textbox",
            css_selector=".footer", css_classes=("footer",),
            dom_path="html/body/div[2]", bbox_px=(36, 700, 1208, 14),
            rendered_lines=1, text_lines=["Source"],
        ))
        return SlideState(slide_id=1, blocks=blocks)

    attached = measured(detached=False, note_font=11)
    detached = measured(detached=True, note_font=9)
    state = SimpleNamespace(
        original_code=attached_code,
        current_code=attached_code,
        _t0_html_state=attached,
        dashboard_verify_history=[],
    )
    AgentRepair._dashboard_decision_summary(state, attached)
    state.current_code = detached_code
    comparison = AgentRepair._dashboard_decision_summary(state, detached)

    assert "Candidate ownership comparison:" in comparison
    assert "direct in-peer ownership to a detached region" in comparison
    assert "from 11px to 9px text scale" in comparison
    assert "not stronger merely because it is contained" in comparison


def test_dashboard_decision_summary_distinguishes_oversized_owner_from_canvas_fit():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    code = """
    <html><div class="bottom">
      <div class="card grid-card"><div class="metric-list"></div><div class="findings">A</div></div>
      <div class="card grid-card"><div class="metric-list"></div><div class="findings">B</div></div>
    </div><div class="footer">Source</div></html>
    """
    blocks = []
    for index, left in enumerate((30, 340)):
        path = f"html/body/div[0]/div[{index}]"
        blocks.extend([
            ContentBlock(
                block_id=f"card_{index}", var_name="div", shape_type="shape",
                css_selector=".grid-card", css_classes=("card", "grid-card"),
                dom_path=path, bbox_px=(left, 300, 280, 510),
            ),
            ContentBlock(
                block_id=f"metric_{index}", var_name="div", shape_type="shape",
                css_selector=".metric-list", css_classes=("metric-list",),
                dom_path=f"{path}/div[0]", bbox_px=(left + 10, 340, 260, 300),
            ),
            ContentBlock(
                block_id=f"findings_{index}", var_name="div", shape_type="textbox",
                css_selector=".findings", css_classes=("findings",),
                dom_path=f"{path}/div[1]", bbox_px=(left + 10, 668, 260, 100),
                rendered_lines=4, text_lines=["Terminal support"],
            ),
        ])
    blocks.append(ContentBlock(
        block_id="footer", var_name="div", shape_type="textbox",
        css_selector=".footer", css_classes=("footer",),
        dom_path="html/body/div[1]", bbox_px=(36, 698, 1208, 14),
        rendered_lines=1, text_lines=["Source"],
    ))
    measured = SlideState(slide_id=1, blocks=blocks)
    state = SimpleNamespace(
        original_code=code,
        current_code=code,
        _t0_html_state=measured,
        dashboard_verify_history=[],
    )

    summary = AgentRepair._dashboard_decision_summary(state, measured)

    assert "usable peer height 398px" in summary
    assert "owner-vs-usable-height 112px" in summary
    assert "deepest descendant bottom 768px" in summary
    assert "deepest-descendant-vs-footer/source 70px" in summary
    assert "upper branch demand 340px" in summary
    assert "terminal branch height 100px" in summary
    assert "descendants fitting inside that oversized owner do not establish" in summary
    assert "outer canvas allocation remains unresolved" in summary


def test_authorized_support_compression_uses_visible_copy_as_source_grounding():
    from app.modules.redeck.agent_repair import AgentRepair

    state = SimpleNamespace(allow_support_copy_compression=True)
    guidance = AgentRepair._text_diff_source_guidance(state, 12)

    assert "existing visible support text is the semantic source" in guidance
    assert "Do not call search_source merely because concise wording uses different tokens" in guidance
    assert "Search only if you add or change a factual proposition" in guidance


def test_dashboard_allocation_map_exposes_card_region_conflicts_and_wraps():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    blocks = []
    for index, left in enumerate((30, 340)):
        card_path = f"div[0]/div[1]/div[{index}]"
        blocks.extend([
            ContentBlock(
                block_id=f"card_{index}", var_name="div", shape_type="shape",
                css_selector=".card", css_classes=("card", "grid-card"),
                dom_path=card_path, bbox_px=(left, 300, 280, 400),
            ),
            ContentBlock(
                block_id=f"name_{index}", var_name="div", shape_type="textbox",
                css_selector=".name", css_classes=("name",),
                dom_path=f"{card_path}/div[0]/div[0]",
                bbox_px=(left + 16, 330, 130, 46), rendered_lines=2,
                text_lines=["Wrapped technology name"],
            ),
            ContentBlock(
                block_id=f"metric_{index}", var_name="div", shape_type="shape",
                css_selector=".metric", css_classes=("metric",),
                dom_path=f"{card_path}/div[2]/div[2]",
                bbox_px=(left + 16, 590, 248, 90),
                text_lines=["Operational risk"],
            ),
            ContentBlock(
                block_id=f"metric_note_{index}", var_name="div", shape_type="textbox",
                css_selector=".m-note", css_classes=("m-note",),
                dom_path=f"{card_path}/div[2]/div[2]/div[2]",
                bbox_px=(left + 28, 620, 224, 54), rendered_lines=3,
                text_lines=["A repeated metric explanation that wraps to three lines."],
            ),
            ContentBlock(
                block_id=f"support_{index}", var_name="div", shape_type="shape",
                css_selector=".findings", css_classes=("findings",),
                dom_path=f"{card_path}/div[3]",
                bbox_px=(left + 16, 650, 248, 80),
                text_lines=["Investment takeaway"],
            ),
            ContentBlock(
                block_id=f"support_line_{index}", var_name="li", shape_type="textbox",
                css_selector="li", css_classes=(),
                dom_path=f"{card_path}/div[3]/ul[0]/li[0]",
                bbox_px=(left + 32, 670, 210, 36), rendered_lines=2,
                text_lines=["Terminal support detail."],
            ),
        ])

    rendered = AgentRepair._dashboard_allocation_map(
        SlideState(slide_id=1, blocks=blocks),
    )

    assert "REPEATED CARD ALLOCATION MAP" in rendered
    assert "upper/support gap=-30px" in rendered
    assert "support vs card bottom=+30px" in rendered
    assert "rendered lines=2" in rendered
    assert "repeated upper support roles:" in rendered
    assert ".m-note bbox=" in rendered
    assert "rendered lines=3" in rendered
    assert "deepest upper contributor:" in rendered
    assert "terminal ownership: .findings direct-child=yes" in rendered
    assert "rendered leaf lines=2" in rendered
    assert "exact upper/terminal intersections:" in rendered
    assert "upper branch extents:" in rendered
    assert ".metric box=590..680px" in rendered
    assert "not a defect verdict" in rendered
    assert "Read the two relations separately" in rendered
    assert "A negative gap alone is not a rollback verdict" in rendered


def test_inline_svg_overflow_residual_includes_viewbox_and_nearby_geometry():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    label = ContentBlock(
        block_id="svg_label", var_name="text", shape_type="chart",
        css_selector="text", dom_path="body[0]/svg[0]/text[0]",
        bbox_px=(1167, 294, 221, 15), text_lines=[
            "Offshore Wind (deep-water Atlantic)",
        ],
        is_svg_text=True, is_in_svg=True, is_overflowing=True,
        overflow_right_px=167,
    )
    state = SlideState(
        slide_id=1,
        blocks=[label],
        svg_regions=[{
            "view_box": {"x": 0, "y": 0, "width": 560, "height": 118},
            "text_metrics": [{
                "label": "Offshore Wind (deep-water Atlantic)",
                "label_bbox": {"x": 1166.9, "y": 293.7, "width": 221.1, "height": 15},
                "svg_bbox": {"x": 506, "y": 100, "width": 221.1, "height": 15},
                "viewbox_edge_gaps": {
                    "left": 506, "top": 100, "right": -167.1, "bottom": 3,
                },
                "nearest_rect": {
                    "bbox": {"x": 400, "y": 24, "width": 72, "height": 72},
                    "distance_px": 34.2,
                },
                "nearest_line": {
                    "endpoints": {"x1": 44, "y1": 96, "x2": 530, "y2": 96},
                    "distance_px": 4,
                },
            }],
        }],
    )

    rendered = AgentRepair._format_svg_text_overflow_residual(state, "svg_label")

    assert "SVG viewBox (0,0,560x118)" in rendered
    assert "label SVG bbox (506,100,221.1x15)" in rendered
    assert "right=-167.1" in rendered
    assert "nearest rect bbox (400,24,72x72)" in rendered
    assert "nearest line endpoints (44,96)→(530,96)" in rendered


def test_dashboard_allocation_map_exposes_parent_descendant_extent():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    summary_path = "div[0]/div[1]/div[0]"
    state = SlideState(slide_id=1, blocks=[
        ContentBlock(
            block_id="summary", var_name="div", shape_type="shape",
            css_selector=".card", css_classes=("card", "summary"),
            dom_path=summary_path, bbox_px=(30, 120, 560, 160),
        ),
        ContentBlock(
            block_id="kpi", var_name="div", shape_type="shape",
            css_selector=".kpi", css_classes=("kpi",),
            dom_path=f"{summary_path}/div[0]/div[0]",
            bbox_px=(50, 180, 160, 125), text_lines=["Top metric"],
        ),
    ])

    rendered = AgentRepair._dashboard_allocation_map(state)

    assert "CONTAINER DESCENDANT EXTENT MAP" in rendered
    assert ".card.summary" in rendered
    assert "+25px vertical" in rendered
    assert "rendered child span y=" in rendered
    assert "lowest contributor=.kpi" in rendered
    assert "Declared parent heights are not reclaimed space" in rendered


def _dashboard_descendant_extent_state():
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    summary_path = "div[0]/div[1]/div[0]"
    spatial = SlideState(slide_id=1, blocks=[
        ContentBlock(
            block_id="summary", var_name="div", shape_type="shape",
            css_selector=".card", css_classes=("card", "summary"),
            dom_path=summary_path, bbox_px=(30, 120, 560, 160),
        ),
        ContentBlock(
            block_id="summary_row", var_name="div", shape_type="shape",
            css_selector=".summary-row", css_classes=("summary-row",),
            dom_path=f"{summary_path}/div[0]", bbox_px=(50, 170, 520, 135),
        ),
        ContentBlock(
            block_id="kpi", var_name="div", shape_type="shape",
            css_selector=".kpi", css_classes=("kpi",),
            dom_path=f"{summary_path}/div[0]/div[0]",
            bbox_px=(50, 180, 160, 125), text_lines=["Top metric"],
        ),
    ])
    html = """
    <html><style>.summary{height:160px}.summary-row{margin-top:20px}</style>
    <div class="summary"><div class="summary-row"><div class="kpi">A</div></div></div>
    <div class="grid-card metric-list"></div><div class="grid-card"></div>
    </html>
    """
    return SimpleNamespace(
        current_code=html,
        issue_types={"density_imbalance"},
        initial_spatial_state=spatial,
        layout_revision=0,
        last_verify_revision=-1,
    )


def test_dashboard_plan_warns_when_parent_boxes_are_used_to_freeze_upper_band():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    state = _dashboard_descendant_extent_state()
    state.has_plan = False
    state.checkpoints = [state.current_code]
    state.slide_id = 1

    feedback, ok = repair._tool_plan(
        {
            "reasoning": (
                "The overflow comes from the repeated lower-card stack rather than "
                "the frame, so keep the top band unchanged and shrink the lower cards."
            ),
            "plan": {
                "summary": "Compress the repeated lower cards.",
                "steps": [{"action": "[dashboard-fit] tighten card metrics"}],
            },
        },
        state,
    )

    assert ok is False
    assert "Plan accepted" in feedback
    assert "DESCENDANT-AWARE PLAN CHECK" in feedback
    assert ".card.summary descendants extend +25px" in feedback
    assert "parent heights alone" in feedback
    assert "advisory evidence" in feedback


def test_dashboard_parent_only_shrink_warns_about_real_descendant_extent():
    from app.modules.redeck.agent_repair import AgentRepair

    state = _dashboard_descendant_extent_state()
    state.layout_revision = 1

    feedback = AgentRepair._dashboard_parent_descendant_patch_warning(
        state,
        ".summary{height:140px}.bottom{height:390px}",
    )

    assert "DESCENDANT-AWARE SPACE CHECK" in feedback
    assert "parent bottom=280px" in feedback
    assert "descendants bottom=305px" in feedback
    assert "without changing the measured descendant roles" in feedback
    assert "non-blocking causal feedback" in feedback


def test_dashboard_coupled_parent_and_child_calibration_is_not_called_parent_only():
    from app.modules.redeck.agent_repair import AgentRepair

    state = _dashboard_descendant_extent_state()
    state.layout_revision = 1

    feedback = AgentRepair._dashboard_parent_descendant_patch_warning(
        state,
        (
            ".summary{height:140px}.summary-row{margin-top:8px;gap:8px}"
            ".kpi{padding:8px}.kpi .sub{font-size:12px;line-height:1.1}"
        ),
    )

    assert "DESCENDANT-AWARE SPACE CHECK" in feedback
    assert "also changes some descendant rhythm" in feedback
    assert "without changing the measured descendant roles" not in feedback
    assert "actual descendant edge retreating" in feedback


def test_dashboard_repeated_owner_shrink_uses_role_demand_not_footer_band():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    card_paths = ("div[0]/div[1]/div[0]", "div[0]/div[1]/div[1]")
    blocks = []
    for index, path in enumerate(card_paths):
        left = 40 + index * 310
        blocks.extend([
            ContentBlock(
                block_id=f"card_{index}", var_name="div", shape_type="shape",
                css_selector=".grid-card", css_classes=("card", "grid-card"),
                dom_path=path, bbox_px=(left, 220, 290, 476),
            ),
            ContentBlock(
                block_id=f"metric_{index}", var_name="div", shape_type="textbox",
                css_selector=".metric", css_classes=("metric",),
                dom_path=f"{path}/div[2]", bbox_px=(left + 12, 540, 266, 130),
                text_lines=["Repeated metric support"],
            ),
            ContentBlock(
                block_id=f"finding_{index}", var_name="div", shape_type="textbox",
                css_selector=".findings", css_classes=("findings",),
                dom_path=f"{path}/div[3]", bbox_px=(left + 12, 680, 266, 120),
                text_lines=["Terminal takeaway"],
            ),
        ])
    blocks.append(ContentBlock(
        block_id="footer", var_name="div", shape_type="textbox",
        css_selector=".footer", css_classes=("footer",),
        dom_path="div[0]/div[2]", bbox_px=(36, 700, 1208, 14),
        text_lines=["Source"],
    ))
    spatial = SlideState(slide_id=1, blocks=blocks)
    html = """
    <html><style>.summary{} .bottom{} .grid-card{} .metric-list{} .findings{} .footer{}</style>
    <div class="summary"><div class="kpi">Top</div></div>
    <div class="bottom">
      <div class="card grid-card"><div class="score">1</div><div class="metric-list"><div class="metric">M</div></div><div class="findings">F</div></div>
      <div class="card grid-card"><div class="score">2</div><div class="metric-list"><div class="metric">M</div></div><div class="findings">F</div></div>
    </div><div class="footer">Source</div></html>
    """
    state = SimpleNamespace(
        current_code=html,
        issue_types={"density_imbalance"},
        initial_spatial_state=spatial,
        layout_revision=1,
        last_verify_revision=-1,
    )

    feedback = AgentRepair._dashboard_repeated_owner_budget_warning(
        state,
        ".grid-card{height:360px}.metric{padding:4px}.findings{font-size:10px}",
    )

    assert "REPEATED OWNER DEMAND CHECK" in feedback
    assert "also changes descendant roles" in feedback
    assert "footer/source content begins near y=700px" in feedback
    assert "full-width area above them as forbidden" in feedback
    assert "non-blocking causal feedback" in feedback


def test_dashboard_allocation_map_keeps_fully_off_canvas_support_ownership():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.modules.redeck.html_spatial_state import _build_state_from_elements

    elements = []
    exceedances = []
    for index, left in enumerate((30, 340)):
        card_path = f"div[0]/div[1]/div[{index}]"
        elements.append({
            "tag": "div",
            "classes": "card grid-card",
            "shapeType": "shape",
            "bbox": {"x": left, "y": 280, "width": 280, "height": 400},
            "domPath": card_path,
        })
        exceedances.append({
            "tag": "div",
            "id": "",
            "classes": "findings",
            "label": "findings",
            "text": "Investment takeaway",
            "fullText": "Investment takeaway",
            "domPath": f"{card_path}/div[3]",
            "renderedLines": 1,
            "x": left + 16,
            "y": 886,
            "w": 248,
            "h": 80,
            "right": left + 264,
            "bottom": 966,
            "exRight": 0,
            "exBottom": 246,
        })

    state = _build_state_from_elements(
        1,
        elements,
        viewport_exceedances=exceedances,
    )
    rendered = AgentRepair._dashboard_allocation_map(state)

    assert len(state.off_canvas_elements) == 2
    assert "no explicit support/takeaway branch identified" not in rendered
    assert "support y=886..966px" in rendered
    assert "support branch extends outside the canvas" in rendered
    assert "reserved in-card support zone" in rendered
    assert "wider multi-row card is not automatically more spacious" in rendered


def test_dashboard_guidance_never_injects_case_specific_golden_checkpoint():
    from app.modules.redeck.agent_repair import AgentRepair

    code = """
    <style>
      .table-wrap{} .notes{} .hero{} .ranking{} .summary-box{}
    </style>
    <div>Renewable Energy Comparison</div>
    <div>Best Blended Score</div>
    <div>Median Project Lead Time</div>
    <div>Top Scoring Options</div>
    <div>Executive Takeaways</div>
    """

    guidance = AgentRepair._dashboard_coupled_cluster_guidance(code)

    assert "Current Dashboard Strategy Cue" in guidance
    assert "hypothesis to inspect, not as a mandatory repair recipe" in guidance
    assert "Choose the actual selectors, edit scope, ordering, and scale" in guidance
    assert "Repeated padding, gaps, line-height, and wrapping" in guidance
    assert "No candidate is a required first step" in guidance
    assert "Add wrappers only when" in guidance
    assert "sparse footer as a full-width exclusion band" in guidance
    assert "Worked Golden Checkpoint" not in guidance
    assert "Renewable Energy Comparison" not in guidance
    assert "322px" not in guidance
    assert "rows 118px 128px" not in guidance


def test_dashboard_prompt_contains_direction_not_a_fixed_trajectory():
    """Simplified: check prompt has general repair patterns, not d178-specific content."""
    prompt_path = (
        Path(__file__).resolve().parents[1]
        / "app/prompts/codegen/slide_html_repair.system.md"
    )
    prompt = prompt_path.read_text(encoding="utf-8")

    assert "Proven repair patterns" in prompt
    assert "cluster_complete" in prompt
    assert "apply_css_patch" in prompt
    assert '"scope":"cluster"' in prompt
    assert "rejected in full rather than partially applied" in prompt
    assert "after each coherent structural checkpoint" in prompt
    assert "Partition independent fixes" in prompt
    assert "Dashboard reference trajectory" not in prompt
    assert "the first code edit should" not in prompt
    assert "begin from the body cluster" not in prompt
    for fixed_recipe in (
        "610px", "500px", "92px", "58px", "10-12px", "high-50s",
    ):
        assert fixed_recipe not in prompt


def test_dashboard_strategy_note_does_not_match_stable_as_table():
    from app.modules.redeck.agent_repair import AgentRepair

    notes = AgentRepair._strategy_fit_notes_for_step_text(
        "[dashboard-fit] preserve a stable repeated-card rhythm",
        1,
    )

    assert not any("table-only repair" in note for note in notes)


def test_strategy_note_checks_width_before_horizontalizing_text_heavy_roles():
    from app.modules.redeck.agent_repair import AgentRepair

    notes = AgentRepair._strategy_fit_notes_for_step_text(
        "[regional reflow] place the metric support copy in a two-column grid",
        2,
    )

    joined = "\n".join(notes)
    assert "actual available line width" in joined
    assert "multiple tracks may narrow every text item" in joined
    assert "not a prohibition on columns" in joined


def test_trajectory_continuation_is_progress_aware_and_revision_scoped():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
    state = AgentState(
        original_code="<html><body>old</body></html>",
        current_code="<html><body>new</body></html>",
        checkpoints=[],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        layout_revision=2,
        last_verify_revision=2,
        last_verify_result={"delta_total": 1},
        last_verify_targeted_residual_counts={"clipped": 1},
        plan_steps=[PlanStep("finish the support rhythm", status="in_progress")],
    )
    state._last_verify_targeted_residual_total = 1
    state._last_verify_spatial_regression_total = 0

    message = repair._trajectory_continuation_message(
        state,
        tool_name="verify_layout",
        code_changed=False,
        tool_calls=22,
        soft_limit=22,
    )

    assert "TRAJECTORY BUDGET EXTENDED AFTER REAL PROGRESS" in message
    assert "clipped=1" in message
    assert "finish the support rhythm" in message
    assert "not an instruction to keep editing" in message
    assert "submit if" in message
    assert "continue the same coherent chain" in message
    assert "correct/rollback" in message

    state.last_trajectory_extension_revision = state.layout_revision
    assert not repair._trajectory_continuation_message(
        state,
        tool_name="verify_layout",
        code_changed=False,
        tool_calls=22,
        soft_limit=22,
    )


def test_trajectory_continuation_never_exceeds_hard_cap():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
    repair.MAX_TOOL_CALLS_CAP = 1
    state = AgentState(
        original_code="<html><body>old</body></html>",
        current_code="<html><body>new</body></html>",
        checkpoints=[],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        layout_revision=1,
    )

    assert not repair._trajectory_continuation_message(
        state,
        tool_name="apply_edits",
        code_changed=True,
        tool_calls=1,
        soft_limit=1,
    )


def test_issue_cluster_brief_keeps_disjoint_repairs_in_separate_checkpoints():
    from app.modules.redeck.agent_repair import AgentRepair
    from app.schemas.common import Severity
    from app.schemas.issue import Issue, IssueEvidence

    issues = [
        Issue(
            issue_id="body",
            rubric_id="B09",
            issue_type="density_imbalance",
            severity=Severity.MAJOR,
            affected_slides=[1],
            evidence=IssueEvidence(description="Repeated cards overflow the body grid."),
        ),
        Issue(
            issue_id="svg",
            rubric_id="B20",
            issue_type="svg_visual_defect",
            severity=Severity.MAJOR,
            affected_slides=[1],
            evidence=IssueEvidence(description="A chart SVG label is clipped."),
        ),
    ]

    brief = AgentRepair._build_issue_cluster_brief(issues)

    assert "Different clusters are separate checkpoints" in brief
    assert "do not let rollback" in brief


def test_dashboard_measurement_context_removes_prescriptive_clip_and_font_language():
    from app.modules.redeck.agent_repair import AgentRepair

    raw = (
        "❌ CLIPPED: row\n"
        "   ↳ clipped by parent .table-wrap (height:320px → grow to 390px)\n"
        '❌ TEXT OVERFLOW: "table" [.table-wrap]\n'
        "   scrollHeight: 623px | clientHeight: 321px | overflow: 302px vertical\n"
        '❌ TEXT OVERFLOW: "summary" [.summary]\n'
        "   scrollHeight: 439px | clientHeight: 180px | overflow: 259px vertical\n"
        "⚠ SMALL FONT: 8 element(s) below 14px body minimum:\n"
        "  ⚠ SMALL FONT: 4 element(s) below minimum:\n"
        "    td: font 10px (body min 14px)\n"
    )

    contextual = AgentRepair._dashboard_measurement_context(raw)

    assert "DENSE DASHBOARD MEASUREMENT CONTEXT" in contextual
    assert "grow to" not in contextual
    assert "below 14px body minimum" not in contextual
    assert "below minimum:" not in contextual
    assert "generic body reference 14px" in contextual
    assert "not a recommendation to grow the parent" in contextual
    assert "FIT MAGNITUDE CUE" in contextual
    assert ".table-wrap: intrinsic content height 623px inside 321px" in contextual
    assert ".summary: intrinsic content height 439px inside 180px" in contextual
    assert "not a target or gate" in contextual


def test_apply_css_patch_consolidates_multi_selector_html_calibration():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = "<!DOCTYPE html><html><head><style>.a{padding:20px}</style></head></html>"
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )

    message, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "css": ".a{padding:8px}\n.b{display:grid;gap:6px}",
    }, state)

    assert changed is True
    assert "REDECK_REPAIR_PATCH_START" in state.current_code
    assert ".a{padding:8px}" in state.current_code
    assert ".b{display:grid;gap:6px}" in state.current_code
    assert "checkpoint marked complete" in message
    assert state.last_cluster_start_code == code


def test_dashboard_css_patch_explains_unimplemented_terminal_support_zone():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
    )

    message, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "css": (
            ".grid-card{display:grid;grid-template-rows:auto auto 1fr auto}"
            ".findings{margin-top:0}"
        ),
    }, state)

    assert changed is True
    assert "TWO-ZONE IMPLEMENTATION CHECK" in message
    assert "implementation feedback, not a rollback gate" in message


def test_dashboard_css_patch_explains_flex_stack_without_terminal_reservation():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
    )

    message, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "css": (
            ".grid-card{display:flex;flex-direction:column}"
            ".metric-list{flex:1 1 auto;min-height:0}"
            ".findings{flex:0 0 auto}"
        ),
    }, state)

    assert changed is True
    assert "TERMINAL SUPPORT ALLOCATION CHECK" in message
    assert "ordinary vertical flex stack" in message
    assert "implementation feedback, not a rollback gate" in message


def test_dashboard_css_patch_accepts_anchored_terminal_support_with_reservation():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
    )

    message, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "css": (
            ".grid-card{display:flex;flex-direction:column;position:relative;"
            "padding-bottom:5rem}"
            ".metric-list{flex:1 1 auto;min-height:0}"
            ".findings{position:absolute;left:1rem;right:1rem;bottom:1rem}"
        ),
    }, state)

    assert changed is True
    assert "TERMINAL SUPPORT ALLOCATION CHECK" not in message
    assert "TWO-ZONE IMPLEMENTATION CHECK" not in message


def test_dashboard_edit_warns_when_plan_promises_reservation_but_keeps_plain_flow():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid}
      .grid-card{position:relative;padding:14px;height:420px}
      .findings{margin-top:8px}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        plan_steps=[PlanStep(
            "Preserve the comparison row while reserving real in-card space "
            "for metrics and findings.",
            status="in_progress",
        )],
    )

    message, changed = repair._tool_apply_edits({
        "cluster_complete": True,
        "reasoning": "Tighten the repeated rhythm before verification.",
        "edits": [{
            "search": ".grid-card{position:relative;padding:14px;height:420px}",
            "replace": ".grid-card{position:relative;padding:12px;height:380px}",
        }],
    }, state)

    assert changed is True
    assert "PLAN-IMPLEMENTATION CONSISTENCY NOTE" in message
    assert "has not tested the strategy described by the plan" in message
    assert "advisory causal feedback" in message
    assert "rollback or acceptance gate" in message


def test_dashboard_plan_implementation_note_accepts_real_anchor_and_reservation():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid}
      .grid-card{position:relative;padding:12px 12px 72px;height:420px}
      .findings{position:absolute;left:12px;right:12px;bottom:8px}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        plan_steps=[PlanStep(
            "Anchor each findings branch in a reserved terminal support zone.",
            status="in_progress",
        )],
    )

    note = AgentRepair._dashboard_plan_implementation_warning(
        state,
        cluster_complete=True,
    )

    assert note == ""


def test_dashboard_concrete_role_calibration_is_a_valid_ordinary_flow_hypothesis():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        plan_steps=[PlanStep(
            "Recalibrate the four comparison cards by reducing score scale, "
            "metric rhythm, and findings spacing until all takeaways fit.",
            status="in_progress",
        )],
    )

    note = AgentRepair._dashboard_plan_implementation_warning(
        state,
        cluster_complete=True,
    )

    assert note == ""


def test_dashboard_css_checkpoint_warns_when_reasoning_promises_unapplied_copy_calibration():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    original = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .m-note{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><div class="score">1</div><div class="metric-list"><div class="m-note">Long metric explanation.</div></div><div class="findings">Long terminal finding.</div></div>
        <div class="card grid-card"><div class="score">2</div><div class="metric-list"><div class="m-note">Another metric explanation.</div></div><div class="findings">Another terminal finding.</div></div>
      </div>
    </body></html>
    """
    current = original.replace(
        ".grid-card{}",
        ".grid-card{padding:10px;height:390px}",
    )
    state = AgentState(
        original_code=original,
        current_code=current,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
        plan_steps=[PlanStep(
            "Recalibrate score scale, metric rhythm, and support copy in the "
            "existing comparison cards.",
            status="in_progress",
        )],
    )

    note = AgentRepair._dashboard_plan_implementation_warning(
        state,
        action_text=(
            "Tighten score and metric rhythm while shortening support copy as "
            "one coupled fit hypothesis."
        ),
        cluster_complete=True,
    )

    assert "COUPLED-LEVER COMPLETION NOTE" in note
    assert "CSS-only edit cannot perform that wording change" in note
    assert "not a required repair order or rollback gate" in note


def test_completed_edit_cluster_reports_promised_terminal_allocation_not_in_delta():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    original = """
    <!DOCTYPE html><html><head><style>
      .top-band{height:170px}
      .grid-card{display:flex;flex-direction:column;height:448px}
      .findings{margin-top:8px}
    </style></head><body>
      <div class="top-band">Overview</div>
      <div class="grid-card">
        <div class="m-note">Long explanatory metric wording.</div>
        <div class="findings">Terminal takeaway remains distinct.</div>
      </div>
    </body></html>
    """
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=original,
        current_code=original,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
        plan_steps=[PlanStep(
            "Keep the peer topology while recalibrating repeated roles and "
            "giving the terminal findings real ownership.",
            status="in_progress",
        )],
    )

    message, changed = repair._tool_apply_edits({
        "cluster_complete": True,
        "reasoning": (
            "Reclaim upstream space by reducing the top-band height, shorten "
            "the metric-note support copy, and give each card a real two-part "
            "allocation so the terminal findings stay attached at the bottom."
        ),
        "edits": [
            {
                "search": ".top-band{height:170px}",
                "replace": ".top-band{height:150px}",
            },
            {
                "search": "Long explanatory metric wording.",
                "replace": "Concise metric wording.",
            },
        ],
    }, state)

    assert changed is True
    assert "EDIT-CLUSTER COVERAGE NOTE" in message
    assert "terminal/support allocation or ownership" in message
    assert "copy calibration" not in message.split("EDIT-CLUSTER COVERAGE NOTE", 1)[1]
    assert "upstream/frame-space reallocation" not in message.split(
        "EDIT-CLUSTER COVERAGE NOTE", 1,
    )[1]
    assert "advisory execution feedback" in message
    assert "rollback gate, or acceptance gate" in message


def test_completed_edit_cluster_accepts_all_explicit_coupled_levers():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    original = """
    <!DOCTYPE html><html><head><style>
      .top-band{height:170px}
      .grid-card{display:flex;flex-direction:column;height:448px}
      .findings{margin-top:8px}
    </style></head><body>
      <div class="top-band">Overview</div>
      <div class="grid-card">
        <div class="m-note">Long explanatory metric wording.</div>
        <div class="findings">Terminal takeaway remains distinct.</div>
      </div>
    </body></html>
    """
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=original,
        current_code=original,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
    )

    message, changed = repair._tool_apply_edits({
        "cluster_complete": True,
        "reasoning": (
            "Reclaim upstream space by reducing the top-band height, shorten "
            "the metric-note support copy, and allocate a dedicated lower track "
            "for the terminal findings."
        ),
        "edits": [
            {
                "search": ".top-band{height:170px}",
                "replace": ".top-band{height:150px}",
            },
            {
                "search": ".grid-card{display:flex;flex-direction:column;height:448px}",
                "replace": (
                    ".grid-card{display:grid;grid-template-rows:minmax(0,1fr) "
                    "auto;height:448px}"
                ),
            },
            {
                "search": ".findings{margin-top:8px}",
                "replace": ".findings{margin-top:8px;align-self:end}",
            },
            {
                "search": "Long explanatory metric wording.",
                "replace": "Concise metric wording.",
            },
        ],
    }, state)

    assert changed is True
    assert "EDIT-CLUSTER COVERAGE NOTE" not in message


def test_completed_copy_checkpoint_is_not_forced_to_execute_unpromised_reflow():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    original = (
        "<!DOCTYPE html><html><head><style>.m-note{}</style></head><body>"
        '<div class="m-note">Long explanatory support wording.</div>'
        "</body></html>"
    )
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=original,
        current_code=original,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
    )

    message, changed = repair._tool_apply_edits({
        "cluster_complete": True,
        "reasoning": "Shorten the support copy as an independent checkpoint.",
        "edits": [{
            "search": "Long explanatory support wording.",
            "replace": "Concise support wording.",
        }],
    }, state)

    assert changed is True
    assert "EDIT-CLUSTER COVERAGE NOTE" not in message


def test_completed_edit_cluster_reports_promised_topology_without_reflow_delta():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    original = (
        "<!DOCTYPE html><html><head><style>"
        ".bottom{display:grid;grid-template-columns:repeat(4,1fr)}"
        ".grid-card{font-size:16px}"
        "</style></head><body><div class='bottom'>"
        "<div class='grid-card'>A</div><div class='grid-card'>B</div>"
        "</div></body></html>"
    )
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=original,
        current_code=original,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
    )

    message, changed = repair._tool_apply_edits({
        "cluster_complete": True,
        "reasoning": "Recompose the lower body into a two-column matrix.",
        "edits": [{
            "search": ".grid-card{font-size:16px}",
            "replace": ".grid-card{font-size:15px}",
        }],
    }, state)

    assert changed is True
    assert "EDIT-CLUSTER COVERAGE NOTE" in message
    assert "topology/reflow" in message


def test_edit_cluster_coverage_does_not_treat_mini_chart_css_as_svg_promise():
    from app.modules.redeck.agent_repair import AgentRepair

    before = """
    <html><head><style>
      .mini-chart{height:170px}.grid-card{height:390px}
    </style></head><body>
      <div class="mini-chart"><svg><text>Offshore Wind</text></svg></div>
      <div class="grid-card">Card</div>
    </body></html>
    """
    after = before.replace(
        ".mini-chart{height:170px}.grid-card{height:390px}",
        ".mini-chart{height:146px}.grid-card{height:414px}",
    )

    note = AgentRepair._edit_cluster_execution_coverage_note(
        MagicMock(),
        before_code=before,
        after_code=after,
        action_text=(
            "CURRENT the chart label remains a separate B20 issue; "
            "TARGET is more body height; COUPLED MOVES: revise .top-band, "
            ".mini-chart, and .grid-card in one frame-space patch."
        ),
        cluster_complete=True,
    )

    assert "local media/SVG work" not in note


def test_edit_cluster_coverage_respects_explicit_no_topology_change():
    from app.modules.redeck.agent_repair import AgentRepair

    before = (
        "<html><body><div class='m-note'>Verbose support wording remains "
        "inside the same four-column topology.</div></body></html>"
    )
    after = before.replace(
        "Verbose support wording remains inside the same four-column topology.",
        "Concise support wording remains in the same four columns.",
    )

    note = AgentRepair._edit_cluster_execution_coverage_note(
        MagicMock(),
        before_code=before,
        after_code=after,
        action_text=(
            "CURRENT the four-column topology is viable and needs no topology "
            "change; COUPLED MOVES: compress the remaining metric-note support "
            "copy without reflow."
        ),
        cluster_complete=True,
    )

    assert "topology/reflow" not in note


def test_edit_cluster_coverage_ignores_other_issue_in_current_state():
    from app.modules.redeck.agent_repair import AgentRepair

    before = """
    <html><head><style>.findings{margin-top:8px}</style></head><body>
      <div class="findings">Takeaway</div>
      <svg><text x="506">Offshore Wind</text></svg>
    </body></html>
    """
    after = before.replace('x="506"', 'x="436"')

    note = AgentRepair._edit_cluster_execution_coverage_note(
        MagicMock(),
        before_code=before,
        after_code=after,
        action_text=(
            "CURRENT terminal findings still need reserved ownership in B09; "
            "COUPLED MOVES: reposition the SVG label inside the existing viewBox "
            "for this local B20 action."
        ),
        cluster_complete=True,
    )

    assert "terminal/support allocation or ownership" not in note
    assert "EDIT-CLUSTER COVERAGE NOTE" not in note


def test_edit_cluster_coverage_still_reports_explicit_svg_work_not_applied():
    from app.modules.redeck.agent_repair import AgentRepair

    before = """
    <html><head><style>.mini-chart{height:170px}</style></head><body>
      <div class="mini-chart"><svg><text x="506">Offshore Wind</text></svg></div>
    </body></html>
    """
    after = before.replace("height:170px", "height:160px")

    note = AgentRepair._edit_cluster_execution_coverage_note(
        MagicMock(),
        before_code=before,
        after_code=after,
        action_text=(
            "COUPLED MOVES: wrap and reposition the offshore SVG label inside "
            "the existing viewBox."
        ),
        cluster_complete=True,
    )

    assert "EDIT-CLUSTER COVERAGE NOTE" in note
    assert "local media/SVG work" in note


def test_dashboard_plan_implementation_note_does_not_choose_strategy_for_agent():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        plan_steps=[PlanStep(
            "Recompose the body after comparing the available peer allocations.",
            status="in_progress",
        )],
    )

    note = AgentRepair._dashboard_plan_implementation_warning(
        state,
        cluster_complete=True,
    )

    assert note == ""


def test_dashboard_plan_feedback_accepts_named_role_copy_calibration():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
    )
    steps = [PlanStep(
        "Recalibrate the repeated comparison cards by reducing score scale, "
        "metric rhythm, and findings spacing so every takeaway fits.",
    )]

    notes = AgentRepair._dashboard_coupled_plan_notes(
        steps,
        state,
        "Preserve the four-card comparison while fitting the lower grid.",
    )
    joined = "\n".join(notes)

    assert "not a falsifiable upper/support allocation hypothesis" not in joined


def test_dashboard_plan_feedback_challenges_goal_only_card_fit_hypothesis():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><h2>A</h2><div class="score">1</div><div class="metric-list">M</div><div class="findings">F</div></div>
        <div class="card grid-card"><h2>B</h2><div class="score">2</div><div class="metric-list">M</div><div class="findings">F</div></div>
      </div>
    </body></html>
    """
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
    )
    steps = [PlanStep(
        "Make the repeated comparison cards fit so every takeaway is visible.",
    )]

    notes = AgentRepair._dashboard_coupled_plan_notes(
        steps,
        state,
        "Preserve the four-card comparison while fitting the lower grid.",
    )
    joined = "\n".join(notes)

    assert "not a falsifiable role-allocation hypothesis" in joined
    assert "role/copy demand within the current flow" in joined
    assert "minimal allocation for the existing terminal child" in joined
    assert "equal options, not a required sequence" in joined
    assert "authorizes meaning-preserving support-copy compression" in joined
    assert "failed verify" in joined


def test_unfinished_support_copy_only_batch_warns_about_checkpoint_boundary():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .m-note{} .findings{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><div class="metric-list"><div class="m-note">Long explanatory support wording for the first metric.</div></div><div class="findings">Keep this takeaway.</div></div>
        <div class="card grid-card"><div class="metric-list"><div class="m-note">Long explanatory support wording for the second metric.</div></div><div class="findings">Keep this takeaway.</div></div>
      </div>
    </body></html>
    """
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
    )

    message, changed = repair._tool_apply_edits({
        "cluster_complete": False,
        "reasoning": "Shorten support copy before a possible card reflow.",
        "edits": [{
            "search": "Long explanatory support wording for the first metric.",
            "replace": "Short support wording for the first metric.",
        }],
    }, state)

    assert changed is True
    assert "CHECKPOINT BOUNDARY NOTE" in message
    assert "independent checkpoint" in message
    assert "avoid a cluster-wide rollback" in message


def test_support_copy_batch_reports_exact_no_op_edits():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = (
        "<!DOCTYPE html><html><head><style>.m-note{}</style></head><body>"
        '<div class="m-note">Community acceptance can delay schedules.</div>'
        '<div class="m-note">Long explanatory support wording.</div>'
        "</body></html>"
    )
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
    )

    message, changed = repair._tool_apply_edits({
        "cluster_complete": True,
        "edits": [
            {
                "search": "Community acceptance can delay schedules.",
                "replace": "Community acceptance can delay schedules.",
            },
            {
                "search": "Long explanatory support wording.",
                "replace": "Concise support wording.",
            },
        ],
    }, state)

    assert changed is True
    assert "NO-OP EDIT NOTE" in message
    assert "edit entries 1" in message
    assert "make no code or rendered-demand change" in message
    assert "Concise support wording." in state.current_code


def test_dashboard_css_patch_warns_on_equal_fractional_text_tracks():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = """
    <!DOCTYPE html><html><head><style>
      .summary{} .bottom{display:grid} .grid-card{} .metric-list{}
    </style></head><body>
      <div class="summary"><div class="kpi">Top</div></div>
      <div class="bottom">
        <div class="card grid-card"><div class="metric-list"><div class="metric">Short</div><div class="metric">Long wrapped explanation</div><div class="metric">Third</div></div></div>
        <div class="card grid-card"><div class="metric-list"><div class="metric">Short</div><div class="metric">Long wrapped explanation</div><div class="metric">Third</div></div></div>
      </div>
    </body></html>
    """
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
    )

    message, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "css": (
            ".metric-list{display:grid;"
            "grid-template-rows:repeat(3,minmax(0,1fr))}"
        ),
    }, state)

    assert changed is True
    assert "VARIABLE-DEMAND TRACK CHECK" in message
    assert ".metric-list contains repeated text-bearing children" in message
    assert "implementation feedback, not a rollback gate" in message


def test_terminal_support_guidance_allows_calibrating_a_viable_intermediate_state():
    """Simplified: check that prompt has general repair pattern guidance."""
    prompt_path = (
        Path(__file__).resolve().parents[1]
        / "app/prompts/codegen/slide_html_repair.system.md"
    )
    prompt = prompt_path.read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())

    # The simplified prompt should still teach CSS-first and preserve-topology
    assert "CSS-only first" in normalized_prompt
    assert "Preserve topology" in normalized_prompt
    assert "Terminal anchoring" in normalized_prompt


def test_dashboard_verify_cues_pending_coupled_support_compression():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState, PlanStep
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    original = """
    <!DOCTYPE html><html><body>
      <div class="summary"><div class="kpi">Top metric</div></div>
      <div class="bottom">
        <div class="card grid-card">
          <div class="score">8.4</div>
          <div class="metric-list"><div class="m-note">Long explanatory support copy wraps here.</div></div>
          <div class="findings">Terminal takeaway remains inside the card.</div>
        </div>
        <div class="card grid-card">
          <div class="score">8.9</div>
          <div class="metric-list"><div class="m-note">Another explanatory support sentence wraps here.</div></div>
          <div class="findings">A second terminal takeaway remains inside its card.</div>
        </div>
      </div>
    </body></html>
    """
    current = original.replace(
        '<div class="score">8.4</div>',
        '<div class="upper"><div class="score">8.4</div>'
    ).replace(
        '<div class="findings">Terminal takeaway remains inside the card.</div>',
        '</div><div class="findings">Terminal takeaway remains inside the card.</div>'
    ).replace(
        '<div class="score">8.9</div>',
        '<div class="upper"><div class="score">8.9</div>'
    ).replace(
        '<div class="findings">A second terminal takeaway remains inside its card.</div>',
        '</div><div class="findings">A second terminal takeaway remains inside its card.</div>'
    )
    state = AgentState(
        original_code=original,
        current_code=current,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
        plan_steps=[
            PlanStep("[dashboard-fit] create explicit upper/support allocation"),
            PlanStep("[compress_support_copy] shorten only the explanatory support copy"),
        ],
    )
    spatial = SlideState(
        slide_id=1,
        blocks=[ContentBlock(
            block_id="note_1",
            var_name="div",
            shape_type="textbox",
            css_selector=".m-note",
            css_classes=("m-note",),
            rendered_lines=3,
            is_clipped=True,
        )],
        clipped_blocks=["note_1"],
    )

    note = AgentRepair._dashboard_pending_coupled_compression_note(state, spatial)

    assert "COUPLED HYPOTHESIS IS PROVISIONAL" in note
    assert "current topology itself remains credible" in note
    assert "actual branch widths, wrapping, descendant extents" in note
    assert "revise or roll back that topology before compressing copy" in note
    assert "same hypothesis" in note

    state.plan_steps[1].status = "skipped"
    assert AgentRepair._dashboard_pending_coupled_compression_note(state, spatial) == ""


def test_support_copy_compression_cannot_remove_metric_role():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = (
        "<!DOCTYPE html><html><head><style>.metric{}</style></head><body>"
        "<div class='metric'>Operational Risk: Low</div>"
        "<div class='findings'>Takeaway</div></body></html>"
    )
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
    )

    message, changed = repair._tool_apply_edits({
        "edits": [{
            "search": (
                "<div class='metric'>Operational Risk: Low</div>"
                "<div class='findings'>Takeaway</div>"
            ),
            "replace": (
                "<div class='findings'>Operational Risk: Low. Takeaway</div>"
            ),
        }],
    }, state)

    assert changed is False
    assert "information-bearing structural role" in message
    assert "metric item count 1->0" in message
    assert state.current_code == code


def test_support_copy_compression_cannot_dissolve_terminal_takeaway_branch():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = (
        "<!DOCTYPE html><html><head><style>.metric{}</style></head><body>"
        "<div class='metric'><div class='m-note'>Metric explanation.</div></div>"
        "<div class='findings'><div class='head'>Investment Takeaway</div>"
        "<div>Distinct conclusion.</div></div></body></html>"
    )
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"density_imbalance"},
        allow_support_copy_compression=True,
    )

    message, changed = repair._tool_apply_edits({
        "edits": [{
            "search": (
                "<div class='metric'><div class='m-note'>Metric explanation.</div></div>"
                "<div class='findings'><div class='head'>Investment Takeaway</div>"
                "<div>Distinct conclusion.</div></div>"
            ),
            "replace": (
                "<div class='metric'><div class='m-note'>Metric explanation. "
                "Distinct conclusion.</div></div>"
            ),
        }],
    }, state)

    assert changed is False
    assert "terminal findings/takeaway branch count 1->0" in message
    assert "dissolve a findings/takeaway branch into metric notes" in message
    assert state.current_code == code


def test_support_copy_compression_allows_rewrapped_takeaway_branch():
    from app.modules.redeck.agent_repair import AgentRepair

    before = (
        "<div class='findings'><div class='head'>Takeaway</div>"
        "<div>Long conclusion.</div></div>"
    )
    after = (
        "<aside class='takeaway-card'><div class='head'>Takeaway</div>"
        "<div>Conclusion.</div></aside>"
    )

    regressions = AgentRepair._support_compression_role_regressions(before, after)

    assert regressions == []


def test_rollback_cluster_restores_state_before_all_coupled_batches():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = "<!DOCTYPE html><html><head><style>.a{height:10px}</style></head></html>"
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )

    _, changed = repair._tool_apply_css_patch({
        "cluster_complete": False,
        "css": ".a{height:20px}",
    }, state)
    assert changed is True
    _, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "css": ".b{height:30px}",
    }, state)
    assert changed is True
    assert state.current_code != code

    message, changed = repair._tool_rollback({"scope": "cluster"}, state)

    assert changed is True
    assert state.current_code == code
    assert "start of the last edit cluster" in message
    assert "Restored checkpoint: original" in message


def test_unstyled_layout_wrapper_keeps_dom_and_css_in_one_rollback_cluster():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = (
        "<!DOCTYPE html><html><head><style>"
        ".bottom{display:grid}.card{padding:12px}"
        "</style></head><body><div class='bottom'>"
        "<div class='card'>A</div><div class='card'>B</div>"
        "</div></body></html>"
    )
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )

    dom_message, changed = repair._tool_apply_edits({
        "cluster_complete": True,
        "edits": [{
            "search": "<div class='card'>A</div>",
            "replace": (
                "<div class='column-stack'><div class='card'>A</div>"
                "<div class='takeaway-card'>Note A</div></div>"
            ),
        }],
    }, state)

    assert changed is True
    assert state.pending_edit_cluster is True
    assert state.last_edit_scope == (
        ".card", ".column-stack", ".takeaway-card",
    )
    assert "STRUCTURAL EDIT CLUSTER KEPT OPEN" in dom_message
    assert ".column-stack" in dom_message

    _, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "css": (
            ".column-stack{display:grid;grid-template-rows:1fr auto}"
            ".takeaway-card{padding:8px}"
        ),
    }, state)

    assert changed is True
    assert state.pending_edit_cluster is False
    assert state.last_cluster_start_code == code

    message, changed = repair._tool_rollback({"scope": "cluster"}, state)

    assert changed is True
    assert state.current_code == code
    assert "start of the last edit cluster" in message


def test_rollback_one_step_still_keeps_prior_independent_edit():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    code = "<!DOCTYPE html><html><head><style>.a{color:red}</style></head></html>"
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    state = AgentState(
        original_code=code,
        current_code=code,
        checkpoints=[code],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )

    _, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "css": ".a{color:blue}",
    }, state)
    assert changed is True
    first_edit = state.current_code

    _, changed = repair._tool_apply_css_patch({
        "cluster_complete": True,
        "mode": "append",
        "css": ".b{color:green}",
    }, state)
    assert changed is True

    _, changed = repair._tool_rollback({"steps": 1}, state)

    assert changed is True
    assert state.current_code == first_edit


def test_dashboard_pressure_allows_first_region_local_edit():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [{"search": ".table-wrap{height:390px}", "replace": ".table-wrap{height:322px}"}]

    feedback = AgentRepair._dashboard_local_first_html_edit_message(
        edits,
        _dashboard_pressure_state(),
    )

    assert feedback is None


def test_dashboard_scaffold_cue_does_not_impose_fresh_verify_prerequisite():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [{"search": ".header{height:100px}", "replace": ".header{height:88px}"}]
    state = _dashboard_pressure_state(
        attempted_code_change=True,
        layout_revision=1,
        last_verify_revision=-1,
        last_verify_result=None,
        last_verify_stale_reason="apply_edits changed code",
    )

    feedback = AgentRepair._dashboard_local_first_html_edit_message(edits, state)

    assert feedback is not None
    assert "DASHBOARD STRATEGY CUE" in feedback
    assert "That is allowed" in feedback
    assert "no required local-first ordering" in feedback
    assert "apply_edits changed code" not in feedback


def test_dashboard_scaffold_cue_is_consistent_after_fresh_verify():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [{"search": ".content{height:610px}", "replace": ".content{height:500px}"}]
    state = _dashboard_pressure_state(
        attempted_code_change=True,
        layout_revision=1,
        last_verify_revision=1,
        last_verify_result={"t1_total": 30},
    )

    feedback = AgentRepair._dashboard_local_first_html_edit_message(edits, state)

    assert "DASHBOARD STRATEGY CUE" in feedback
    assert "That is allowed" in feedback
    assert "no required local-first ordering" in feedback


def test_spatial_regression_policy_is_not_rollback_first():
    from app.modules.redeck.agent_repair import AgentRepair

    feedback = AgentRepair._spatial_regression_policy_message(2)

    assert "require issue-level judgment before submit" in feedback
    assert "count alone does not make the checkpoint worse" in feedback
    assert "not an automatic rollback" in feedback
    assert "closure edit" in feedback
    assert "detector artifact" in feedback
    assert "Roll back" in feedback


def test_spatial_regression_policy_prioritizes_hard_quality_failure():
    from app.modules.redeck.agent_repair import AgentRepair

    feedback = AgentRepair._spatial_regression_policy_message(
        12,
        hard_quality_failure="visual compression: dominant font shrank",
    )

    assert "INVALID INTERMEDIATE CHECKPOINT" in feedback
    assert "Do not continue a same-cluster closure chain" in feedback
    assert "Restore a checkpoint" in feedback
    assert "not an automatic rollback" not in feedback


def test_spatial_regression_details_are_representative_not_exhaustive():
    from app.modules.redeck.agent_repair import AgentRepair

    regressions = {
        "interaction": [
            ("overlap", (f"a_{idx}", f"b_{idx}")) for idx in range(12)
        ],
        "content_fit": [
            ("text_overflow", f"text_{idx}") for idx in range(9)
        ],
    }

    shown, omitted = AgentRepair._representative_spatial_regressions(regressions)

    assert len(shown) == 12
    assert sum(omitted.values()) == 9
    assert omitted == {"interaction": 6, "content_fit": 3}


def test_shared_takeaway_band_plan_gets_whole_composition_warning():
    from app.modules.redeck.agent_repair import AgentRepair

    notes = AgentRepair._strategy_fit_notes_for_step_text(
        "[regional reflow] Move each card's Investment Takeaway into one "
        "shared takeaway band below the cards.",
        4,
    )

    assert any("consumes body height while shortening every peer card" in note for note in notes)
    assert any("peer-card-plus-support demand" in note for note in notes)


def test_dashboard_table_outer_frame_warning_without_cell_rhythm():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [{"search": ".table-wrap{height:390px}", "replace": ".table-wrap{height:322px}"}]

    feedback = AgentRepair._dashboard_table_outer_frame_warning_from_edits(
        edits,
        _dashboard_pressure_state(),
    )

    assert "DASHBOARD TABLE CAUSAL CHECK" in feedback
    assert "without changing its internal row/cell rhythm" in feedback
    assert "That may be correct" in feedback
    assert "do not assume either the frame or the rows must change" in feedback


def test_dashboard_table_outer_frame_warning_does_not_treat_text_transform_as_tr_selector():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {
            "search": (
                ".table-wrap{height:332px}"
                ".summary-box .head{text-transform:uppercase}"
            ),
            "replace": (
                ".table-wrap{height:388px}"
                ".summary-box .head{text-transform:uppercase}"
            ),
        }
    ]

    feedback = AgentRepair._dashboard_table_outer_frame_warning_from_edits(
        edits,
        _dashboard_pressure_state(),
    )

    assert "DASHBOARD TABLE CAUSAL CHECK" in feedback
    assert "That may be correct" in feedback


def test_dashboard_table_outer_frame_warning_silent_with_cell_rhythm():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {
            "search": ".table-wrap{height:390px}.table-wrap td{padding:16px;font-size:15px}",
            "replace": ".table-wrap{height:322px}.table-wrap td{padding:8px;font-size:11px}",
        }
    ]

    feedback = AgentRepair._dashboard_table_outer_frame_warning_from_edits(
        edits,
        _dashboard_pressure_state(),
    )

    assert feedback == ""


def test_dashboard_coupled_cluster_warns_on_table_only_edit():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {
            "search": "tbody td{font-size:16px;padding:15px}",
            "replace": "tbody td{font-size:10px;padding:5px;line-height:1.1}",
        }
    ]

    feedback = AgentRepair._dashboard_coupled_cluster_warning_from_edits(
        edits,
        _dashboard_pressure_state(),
    )

    assert "DASHBOARD SHARED-PRESSURE CHECK" in feedback
    assert "can be local" in feedback
    assert "one symptom of a shared body constraint" in feedback
    assert "Continue locally when the defect is isolated" in feedback


def test_dashboard_coupled_cluster_silent_on_coupled_edit():
    from app.modules.redeck.agent_repair import AgentRepair

    edits = [
        {
            "search": (
                "tbody td{font-size:16px;padding:15px}.notes{gap:14px}"
                ".summary-box .text{font-size:28px}"
            ),
            "replace": (
                "tbody td{font-size:10px;padding:5px}.notes{gap:10px}"
                ".summary-box .text{font-size:14px}"
            ),
        }
    ]

    feedback = AgentRepair._dashboard_coupled_cluster_warning_from_edits(
        edits,
        _dashboard_pressure_state(),
    )

    assert feedback == ""



def test_plan_warns_on_unjustified_continuation_table_strategy():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    state = SimpleNamespace(
        has_plan=False,
        checkpoints=["<html>original</html>"],
        slide_id=13,
    )

    feedback, ok = repair._tool_plan(
        {
            "plan": {
                "summary": "Try a stronger strategy after failed fit.",
                "steps": [
                    {
                        "action": (
                            "[regional reflow] split the table into "
                            "continuation table segments after the current "
                            "slot stayed short"
                        ),
                    },
                ],
            },
        },
        state,
    )

    assert ok is False
    assert "continuation/split-table strategy" in feedback
    assert "not a generic stronger layout strategy" in feedback


def test_plan_reflow_note_offers_calibration_as_an_option_not_a_prerequisite():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    state = SimpleNamespace(
        has_plan=False,
        checkpoints=["<html>original</html>"],
        slide_id=13,
    )

    feedback, ok = repair._tool_plan(
        {
            "plan": {
                "summary": "Repair table/dashboard pressure.",
                "steps": [
                    {
                        "action": (
                            "[regional reflow] rebuild the whole slide body grid "
                            "and footer around the table, ranking, and summary"
                        ),
                    },
                ],
            },
        },
        state,
    )

    assert ok is False
    assert "whole-slide/body-grid reflow" in feedback
    assert "role-aware calibration is one lower-cost option" in feedback
    assert "the proposed reflow may be appropriate" in feedback
    assert "does not impose a local-first ordering" in feedback


def test_plan_warns_dashboard_fit_table_only_should_name_cluster():
    from app.modules.redeck.agent_repair import AgentRepair

    repair = object.__new__(AgentRepair)
    state = SimpleNamespace(
        has_plan=False,
        checkpoints=["<html>original</html>"],
        slide_id=13,
    )

    feedback, ok = repair._tool_plan(
        {
            "plan": {
                "summary": "Repair dense dashboard table pressure.",
                "steps": [
                    {
                        "action": (
                            "[dashboard-fit] compact the table rows and table-wrap "
                            "until the clipped rows fit"
                        ),
                    },
                ],
            },
        },
        state,
    )

    assert ok is False
    assert "dashboard-fit as a table-only repair" in feedback
    assert "Check whether nearby notes/cards or a KPI/summary rail compete" in feedback
    assert "Keep the edit local when evidence shows an isolated table defect" in feedback
    assert "shared-pressure hypothesis" in feedback


def test_update_plan_warns_on_added_continuation_table_strategy():
    from app.modules.redeck.agent_repair import AgentRepair, PlanStep

    repair = object.__new__(AgentRepair)
    state = SimpleNamespace(
        plan_steps=[PlanStep(text="[local-fit] recalibrate table/card tracks")],
    )

    feedback, ok = repair._tool_update_plan(
        {
            "updates": [
                {
                    "add": (
                        "[body recompose] split table into continuation "
                        "segments because the slot is still short"
                    ),
                },
            ],
        },
        state,
    )

    assert ok is False
    assert "continuation/split-table strategy" in feedback
    assert "whole semantic units" in feedback


def test_normalize_correct_content_text_strips_editorial_directives():
    from app.modules.redeck.repair_utils import (
        extract_table_row_specs_from_correct_content,
        normalize_correct_content_text,
    )

    assert normalize_correct_content_text(
        'Add evidence bullet: "Graph-quality evidence: ROC-AUC improves."',
    ) == "Graph-quality evidence: ROC-AUC improves."
    normalized_rows = normalize_correct_content_text(
        'Add rows: "Gemini 2.5-Flash + Transformer G | 0.3931 | 0.0369" and "GPT-4.1 + Transformer G | 0.3778 | 0.0306".',
    )
    assert "Add rows" not in normalized_rows
    assert "Gemini 2.5-Flash + Transformer G" in normalized_rows
    assert "GPT-4.1 + Transformer G" in normalized_rows
    assert extract_table_row_specs_from_correct_content(
        'Add rows: "Gemini 2.5-Flash + Transformer G | 0.3931 | 0.0369" and "GPT-4.1 + Transformer G | 0.3778 | 0.0306".',
    ) == (
        "Gemini 2.5-Flash + Transformer G | 0.3931 | 0.0369",
        "GPT-4.1 + Transformer G | 0.3778 | 0.0306",
    )
    assert normalize_correct_content_text(
        'REMOVE — no source support. Replace with: "Source-backed claim"',
    ) == "Source-backed claim"
    assert normalize_correct_content_text("REMOVE — no source support") == ""


def test_composition_self_assessment_requires_issue_level_spatial_evidence():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(issue_type="density_imbalance", issue_id="B09_slide3")
    state = SimpleNamespace(repair_summary=None)

    assert not AgentRepair._summary_has_composition_closure(state, [issue])

    state.repair_summary = {
        "composition_closure": "looks clean; no hard defects",
    }
    assert not AgentRepair._summary_has_composition_closure(state, [issue])

    state.repair_summary = {
        "composition_closure": [
            {
                "issue_id": "B09_slide3",
                "original_failure": "lower-left void made the content weight uneven",
                "current_spatial_evidence": (
                    "LAYOUT ANCHOR and SPACE MAP show the chart block now "
                    "frames the lower-left region and balances the right column"
                ),
                "verdict": "pass",
            },
        ],
    }
    assert AgentRepair._summary_has_composition_closure(state, [issue])


def test_composition_self_assessment_allows_specific_unresolved_blank_space():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(issue_type="density_imbalance", issue_id="B09_slide3")
    state = SimpleNamespace(repair_summary={
        "composition_closure": [
            {
                "issue_id": "B09_slide3",
                "original_failure": "lower-left void made the slide look unfinished",
                "current_spatial_evidence": (
                    "LAYOUT ANCHOR shows rendered image content rect 836x316 and "
                    "SPACE MAP BL fill improved, but the lower-left area is not "
                    "fully filled and some blank space remains."
                ),
                "verdict": "pass",
            },
        ],
        "unresolved_concerns": [
            "The lower-left area is improved but not fully filled; some blank framing remains.",
        ],
    })

    assert AgentRepair._summary_has_composition_closure(state, [issue])
    assert not AgentRepair._summary_has_resolved_composition_closure(state, [issue])


def test_composition_self_assessment_allows_weak_or_uncertain_evidence_trace():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(issue_type="raw_figure", issue_id="B17_slide7")
    state = SimpleNamespace(repair_summary={
        "composition_closure": [
            {
                "issue_id": "B17_slide7",
                "original_failure": (
                    "The central decision-tree figure was too small, with "
                    "tiny branch labels and a lower gray void beneath it."
                ),
                "current_spatial_evidence": (
                    "LAYOUT ANCHOR shows rendered image content rect increased "
                    "from 494x201 to 528x215, the figure sits slightly lower, "
                    "and the remaining lower space is no longer an isolated void "
                    "because it is framed by implication cards and the footer below."
                ),
                "verdict": "uncertain",
            },
        ],
        "unresolved_concerns": [],
    })

    assert AgentRepair._summary_has_composition_closure(state, [issue])
    assert not AgentRepair._summary_has_resolved_composition_closure(state, [issue])


def test_composition_self_assessment_allows_task_based_raw_figure_pass():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(issue_type="raw_figure", issue_id="B17_slide7")
    state = SimpleNamespace(repair_summary={
        "composition_closure": [
            {
                "issue_id": "B17_slide7",
                "original_failure": (
                    "The decision-tree figure was not inspectable and the "
                    "lower-left body area had no structural role."
                ),
                "current_spatial_evidence": (
                    "LAYOUT ANCHOR reports the rendered image content rect and "
                    "image interior as a complete decision-tree asset. Render "
                    "inspection shows the branch labels needed by the slide's "
                    "decision task are readable, and the former lower-left void "
                    "now contains the reflowed implication row rather than a "
                    "caption, source note, or footer filler."
                ),
                "verdict": "pass",
            },
        ],
        "unresolved_concerns": [],
    })

    assert AgentRepair._summary_has_composition_closure(state, [issue])
    assert AgentRepair._summary_has_resolved_composition_closure(state, [issue])


def test_composition_completion_rejects_moderate_pass_with_concerns():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(issue_type="raw_figure", issue_id="B17_slide8")
    state = SimpleNamespace(repair_summary={
        "composition_closure": [
            {
                "issue_id": "B17_slide8",
                "original_failure": "The academic chart was too small to inspect.",
                "chosen_strategy": "crop",
                "current_spatial_evidence": (
                    "Render preview shows a slightly cleaner chart crop, but "
                    "the same dense two-panel figure remains in the same slot."
                ),
                "verdict": "pass",
            },
        ],
        "confidence": "medium",
        "unresolved_concerns": [
            "The improvement is moderate rather than dramatic because the "
            "source figure remains wide and dense.",
        ],
    })

    assert AgentRepair._summary_has_composition_closure(state, [issue])
    reasons = AgentRepair._composition_closure_unresolved_reasons(state, [issue])
    assert reasons
    assert any("unresolved_concerns" in reason for reason in reasons)
    assert not AgentRepair._summary_has_resolved_composition_closure(state, [issue])


def test_composition_completion_rejects_low_fidelity_chart_redraw():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(
        issue_type="raw_figure",
        issue_id="B17_slide8",
        sub_type="",
        evidence=SimpleNamespace(
            description="A training dynamics chart with axes, legend, and plotted curves."
        ),
        planned_fix="Replace the chart with a source-grounded SVG summary.",
        why_this_fails="The chart labels are small at slide scale.",
        fix_detail=SimpleNamespace(target_location="left chart", correct_content=""),
    )
    state = SimpleNamespace(repair_summary={
        "composition_closure": [
            {
                "issue_id": "B17_slide8",
                "original_failure": "The training dynamics chart labels were small.",
                "chosen_strategy": "redraw",
                "current_spatial_evidence": (
                    "Render preview shows a generated SVG summary with larger "
                    "labels and simplified curves."
                ),
                "verdict": "pass",
            },
        ],
        "self_assessment": (
            "The SVG summary preserves the key series relationships and is more "
            "readable than the original chart."
        ),
        "confidence": "high",
        "unresolved_concerns": [],
    })

    reasons = AgentRepair._composition_closure_unresolved_reasons(state, [issue])

    assert any("evidence-fidelity" in reason for reason in reasons)
    assert not AgentRepair._summary_has_resolved_composition_closure(state, [issue])


def test_composition_completion_allows_exact_data_chart_redraw():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(
        issue_type="raw_figure",
        issue_id="B17_slide8",
        sub_type="",
        evidence=SimpleNamespace(
            description="A training dynamics chart with axes, legend, and plotted curves."
        ),
        planned_fix="Regenerate the chart only from exact source data.",
        why_this_fails="The chart labels are small at slide scale.",
        fix_detail=SimpleNamespace(target_location="left chart", correct_content=""),
    )
    state = SimpleNamespace(repair_summary={
        "composition_closure": [
            {
                "issue_id": "B17_slide8",
                "original_failure": "The training dynamics chart labels were small.",
                "chosen_strategy": "redraw",
                "current_spatial_evidence": (
                    "The chart was regenerated via generate_chart from exact source data; "
                    "axes, legend, tick meanings, and curve relationships remain source-grounded."
                ),
                "verdict": "pass",
            },
        ],
        "self_assessment": "The exact source data redraw improves readability without approximating the chart.",
        "confidence": "high",
        "unresolved_concerns": [],
    })

    assert AgentRepair._summary_has_composition_closure(state, [issue])
    assert AgentRepair._summary_has_resolved_composition_closure(state, [issue])


def test_raw_figure_completion_rejects_outer_slot_evidence_only():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(
        issue_type="raw_figure",
        issue_id="B17_slide8",
        sub_type="",
        evidence=SimpleNamespace(description="A chart with small labels."),
        planned_fix="Make the chart more readable.",
        why_this_fails="The chart labels are small at full-slide scale.",
        fix_detail=SimpleNamespace(target_location="left chart", correct_content=""),
    )
    state = SimpleNamespace(repair_summary={
        "composition_closure": [
            {
                "issue_id": "B17_slide8",
                "original_failure": "The chart was too small to inspect.",
                "chosen_strategy": "reflow",
                "current_spatial_evidence": (
                    "The rendered chart slot is now 1200x300 with no hard defects, "
                    "and the lower band contains the existing observations."
                ),
                "verdict": "pass",
            },
        ],
        "self_assessment": "The larger slot gives the chart top-of-slide prominence.",
        "confidence": "high",
        "unresolved_concerns": [],
    })

    reasons = AgentRepair._composition_closure_unresolved_reasons(state, [issue])

    assert any("content-rect" in reason for reason in reasons)
    assert not AgentRepair._summary_has_resolved_composition_closure(state, [issue])


def test_composition_completion_rejects_self_disclaimed_alignment_pass():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(
        issue_type="alignment_inconsistency",
        issue_id="B13_slide5",
    )
    state = SimpleNamespace(repair_summary={
        "composition_closure": [
            {
                "issue_id": "B13_slide5",
                "original_failure": "The lower body void made peer columns uneven.",
                "chosen_strategy": "local",
                "current_spatial_evidence": (
                    "The right rail is slightly shorter, but SPACE MAP still "
                    "shows the same lower void and this is not a definitive "
                    "visual pass."
                ),
                "verdict": "pass",
            },
        ],
        "self_assessment": "I cannot claim a high-confidence composition pass.",
        "confidence": "medium",
        "unresolved_concerns": [],
    })

    assert AgentRepair._summary_has_composition_closure(state, [issue])
    reasons = AgentRepair._composition_closure_unresolved_reasons(state, [issue])
    assert reasons
    assert any("cannot claim" in reason or "disclaims" in reason for reason in reasons)
    assert not AgentRepair._summary_has_resolved_composition_closure(state, [issue])


def test_composition_guidance_discourages_mechanical_alignment_pass():
    from app.modules.redeck.agent_repair import AgentRepair

    issue = SimpleNamespace(
        rubric_id="B13",
        issue_type="alignment_inconsistency",
        issue_id="B13_slide5",
        evidence=SimpleNamespace(
            description="Bottom edges of peer blocks feel inconsistent.",
        ),
        why_this_fails="One column leaves a lower-corner void.",
        planned_fix="Align peer block bottoms.",
    )

    guidance = AgentRepair._build_composition_closure_guidance([issue])
    reminder = AgentRepair._build_composition_closure_verify_reminder([issue])

    assert "single proxy" in guidance
    assert "shared anchor is not the whole goal" in guidance
    assert "stretched rows/cards" in reminder
    assert "natural rhythm" in reminder
    assert "should not be labeled high confidence" in guidance
    assert "Do not infer unreadability from one reported pixel size" in guidance
    assert "do not force another topology" in guidance
    assert "Small-font and dense-content notices are informational" in reminder


def test_dispatcher_rejects_unsubmitted_composition_repair():
    from app.modules.redeck.dispatcher import ReDeckWorker

    issue = SimpleNamespace(issue_type="density_imbalance", issue_id="B09_slide3")
    repair = SimpleNamespace(
        last_repair_submitted=False,
        last_repair_has_valid_composition_closure=True,
    )

    accepted, reason = ReDeckWorker._agent_result_has_required_completion(
        repair, [issue],
    )

    assert not accepted
    assert "did not successfully submit" in reason


def test_dispatcher_rejects_missing_composition_self_assessment():
    from app.modules.redeck.dispatcher import ReDeckWorker

    issue = SimpleNamespace(issue_type="density_imbalance", issue_id="B09_slide3")
    repair = SimpleNamespace(
        last_repair_submitted=True,
        last_repair_has_valid_composition_closure=False,
    )

    accepted, reason = ReDeckWorker._agent_result_has_required_completion(
        repair, [issue],
    )

    assert not accepted
    assert "composition self-assessment" in reason


def test_dispatcher_rejects_unresolved_composition_completion():
    from app.modules.redeck.dispatcher import ReDeckWorker

    issue = SimpleNamespace(issue_type="density_imbalance", issue_id="B09_slide3")
    repair = SimpleNamespace(
        last_repair_submitted=True,
        last_repair_has_valid_composition_closure=True,
        last_repair_has_resolved_composition_closure=False,
    )

    accepted, reason = ReDeckWorker._agent_result_has_required_completion(
        repair, [issue],
    )

    assert not accepted
    assert "unresolved" in reason


def test_dispatcher_accepts_resolved_composition_completion():
    from app.modules.redeck.dispatcher import ReDeckWorker

    issue = SimpleNamespace(issue_type="density_imbalance", issue_id="B09_slide3")
    repair = SimpleNamespace(
        last_repair_submitted=True,
        last_repair_has_valid_composition_closure=True,
        last_repair_has_resolved_composition_closure=True,
    )

    accepted, reason = ReDeckWorker._agent_result_has_required_completion(
        repair, [issue],
    )

    assert accepted
    assert "resolved" in reason


def test_dispatcher_allows_noncomposition_without_submit_metadata():
    from app.modules.redeck.dispatcher import ReDeckWorker

    issue = SimpleNamespace(issue_type="text_overflow", issue_id="B04_slide3")
    repair = SimpleNamespace(
        last_repair_submitted=False,
        last_repair_has_valid_composition_closure=False,
    )

    accepted, reason = ReDeckWorker._agent_result_has_required_completion(
        repair, [issue],
    )

    assert accepted
    assert "no composition" in reason


def test_dispatcher_rejects_unsubmitted_noncomposition_with_target_residuals():
    from app.modules.redeck.dispatcher import ReDeckWorker

    issue = SimpleNamespace(issue_type="text_overflow", issue_id="B04_slide3")
    repair = SimpleNamespace(
        last_repair_submitted=False,
        last_repair_targeted_residual_total=2,
    )

    accepted, reason = ReDeckWorker._agent_result_has_required_completion(
        repair, [issue],
    )

    assert not accepted
    assert "2 targeted deterministic residual" in reason


def test_dispatcher_allows_clean_verified_timeout_fallback():
    from app.modules.redeck.dispatcher import ReDeckWorker

    issue = SimpleNamespace(issue_type="text_overflow", issue_id="B04_slide3")
    repair = SimpleNamespace(
        last_repair_submitted=False,
        last_repair_targeted_residual_total=0,
    )

    accepted, reason = ReDeckWorker._agent_result_has_required_completion(
        repair, [issue],
    )

    assert accepted
    assert "no composition" in reason


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


class TestContentModifiedTracking:
    """Only successful content edits should enter differential evaluation."""

    @staticmethod
    def _issue(*, correct_content=""):
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue

        return Issue(
            issue_id="D01_slide1_test",
            rubric_id="D1",
            issue_type="incorrect_claim",
            severity=Severity.MAJOR,
            affected_slides=[1],
            fix_detail=FixDetail(correct_content=correct_content),
        )

    def test_content_only_patch_is_tracked_without_layout_repair(self):
        from app.modules.redeck.dispatcher import ReDeckWorker

        worker = ReDeckWorker(MagicMock())
        compiler = SimpleNamespace(slide_codes={1: "old"})
        worker._apply_content_patches = MagicMock(return_value="new")

        repaired = worker.repair_slides(
            codegen_compiler=compiler,
            issues=[self._issue(correct_content="correct")],
            blueprint_slides=[SimpleNamespace(slide_id=1)],
            evidence=MagicMock(),
            case_dir=".",
            turn_index=1,
        )

        assert repaired == []
        assert compiler.slide_codes[1] == "new"
        assert worker.content_modified_slides == {1}

    def test_content_patch_receives_normalized_correct_content(self):
        from app.modules.redeck.dispatcher import ReDeckWorker

        llm = MagicMock()
        llm.call_text.return_value = '{"edits": []}'
        worker = ReDeckWorker(llm)
        issue = self._issue(
            correct_content='Add evidence bullet: "Graph-quality evidence: ROC-AUC improves."',
        )

        worker._apply_content_patches(
            1,
            "<html><body><p>Existing point</p></body></html>",
            [issue],
            SimpleNamespace(),
            ".",
        )

        user_content = llm.call_text.call_args.kwargs["user_content"]
        assert "Correct content (from source paper): Graph-quality evidence: ROC-AUC improves." in user_content
        assert "Add evidence bullet" not in user_content

    def test_failed_content_agent_is_not_reported_as_modified(self):
        from app.modules.redeck.dispatcher import ReDeckWorker

        worker = ReDeckWorker(MagicMock())
        compiler = SimpleNamespace(slide_codes={1: "old"})
        worker._repair_one_slide = MagicMock(return_value=False)

        repaired = worker.repair_slides(
            codegen_compiler=compiler,
            issues=[self._issue()],
            blueprint_slides=[SimpleNamespace(slide_id=1)],
            evidence=MagicMock(),
            case_dir=".",
            turn_index=1,
        )

        assert repaired == []
        assert worker.content_modified_slides == set()

    def test_issue_default_action_does_not_force_regeneration(self):
        from app.schemas.common import RepairAction

        assert self._issue().recommended_action == RepairAction.PATCH

    def test_add_data_row_prompt_uses_table_cells_not_editorial_sentence(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue, IssueEvidence

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        issue = Issue(
            issue_id="C04_slide8_rows",
            rubric_id="C04",
            issue_type="missing_entity",
            severity=Severity.MAJOR,
            affected_slides=[8],
            evidence=IssueEvidence(description="Table 2 omits two source rows."),
            planned_fix="Add the two omitted model rows to the Table 2 block.",
            fix_detail=FixDetail(
                correct_content='Add rows: "Gemini 2.5-Flash + Transformer G | 0.3931 | 0.0369" and "GPT-4.1 + Transformer G | 0.3778 | 0.0306".',
                target_location="Slide 8, Table 2 model list",
                action_type="add_data_row",
            ),
        )

        must_contain, must_not = repair._extract_content_requirements(
            "<html><body><table><tbody></tbody></table></body></html>",
            [issue],
        )
        checklist = repair._build_content_checklist([issue])
        message = repair._build_initial_message(
            code="<html><body><table><tbody></tbody></table></body></html>",
            all_issues=[issue],
            spatial_info="",
            evidence_text="",
            must_contain=must_contain,
            must_not=must_not,
            content_checklist=checklist,
            bp_slide=None,
            viz_data=None,
            adjacent_context="",
        )

        assert "Add rows:" not in message
        assert "MANDATORY TABLE ROW INSERT" in message
        assert "Table row with cells" in message
        assert "REQUIRED TABLE ROW" in message
        assert "Gemini 2.5-Flash + Transformer G | 0.3931 | 0.0369" in message
        assert "Do NOT add a <p>" in message

    def test_missing_content_prompt_allows_same_topic_merge(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue, IssueEvidence

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        issue = Issue(
            issue_id="C03_slide8_context",
            rubric_id="C03",
            issue_type="missing_evidence",
            severity=Severity.MAJOR,
            affected_slides=[8],
            evidence=IssueEvidence(description="The benchmark note lacks the source-backed qualifier."),
            planned_fix="Add the source-backed benchmark qualifier.",
            fix_detail=FixDetail(
                correct_content="Benchmark metrics: Graph Sparsity and JSD compare structural consistency.",
                target_location="benchmark metrics paragraph",
                action_type="add_bullet",
            ),
        )
        must_contain, must_not = repair._extract_content_requirements(
            "<html><body><p>Benchmark metrics paragraph.</p></body></html>",
            [issue],
        )
        message = repair._build_initial_message(
            code="<html><body><p>Benchmark metrics paragraph.</p></body></html>",
            all_issues=[issue],
            spatial_info="",
            evidence_text="",
            must_contain=must_contain,
            must_not=must_not,
            content_checklist=repair._build_content_checklist([issue]),
            bp_slide=None,
            viz_data=None,
            adjacent_context="",
        )

        assert "MANDATORY INCLUDE" in message
        assert "Prefer replacing/merging" in message
        assert "Append with insert_after only when there is clear space" in message
        assert "Fixed-format budget" in message
        assert "full-width bottom bar" in message
        assert "Do NOT replace or remove ANY existing text" not in message

    def test_long_d04_correct_content_is_semantic_target_not_verbatim_paste(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue, IssueEvidence

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        correct = (
            "Figure 2: Node feature importance distributions show seizure onset "
            "in frontal regions and propagation toward temporal regions from t+1 "
            "to t+6. Figure 4: In a four-window case study, refined EEG graphs "
            "progress from frontal to temporal, central, and finally "
            "parietal-occipital regions."
        )
        issue = Issue(
            issue_id="D04_slide9_fig_scope",
            rubric_id="D04",
            issue_type="chart_misinterpretation",
            severity=Severity.MAJOR,
            affected_slides=[9],
            evidence=IssueEvidence(
                description='Slide wrongly says "Figure 2 shows all four stages".',
            ),
            planned_fix="Separate the Figure 2 and Figure 4 takeaways into distinct bullets.",
            fix_detail=FixDetail(
                correct_content=correct,
                target_location="body text under Physiological plausibility",
                action_type="rewrite_claim",
            ),
        )

        must_contain, must_not = repair._extract_content_requirements(
            '<html><body><li>Figure 2 shows all four stages.</li></body></html>',
            [issue],
        )
        message = repair._build_initial_message(
            code='<html><body><li>Figure 2 shows all four stages.</li></body></html>',
            all_issues=[issue],
            spatial_info="",
            evidence_text="",
            must_contain=must_contain,
            must_not=must_not,
            content_checklist=repair._build_content_checklist([issue]),
            bp_slide=None,
            viz_data=None,
            adjacent_context="",
        )

        assert "MANDATORY REPLACE" in message
        assert "Source-backed semantic target" in message
        assert "paraphrase or split" in message
        assert "STRUCTURE REQUIREMENT" in message
        assert "two <li> items" in message
        assert "Must cover" in message
        assert "Must contain text close to" not in message
        assert "Replace with:" not in message

    def test_b_family_issue_is_never_sent_to_content_patch_phase(self):
        from app.modules.redeck.dispatcher import ReDeckWorker
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue

        worker = ReDeckWorker(MagicMock())
        worker._apply_content_patches = MagicMock(return_value=None)
        worker._repair_one_slide = MagicMock(return_value=False)
        compiler = SimpleNamespace(slide_codes={1: "<html><body>Figure</body></html>"})
        issue = Issue(
            issue_id="B17_slide1",
            rubric_id="B17",
            issue_type="raw_figure",
            severity=Severity.MAJOR,
            affected_slides=[1],
            fix_detail=FixDetail(correct_content="Crop the existing figure"),
        )

        worker.repair_slides(
            codegen_compiler=compiler,
            issues=[issue],
            blueprint_slides=[SimpleNamespace(slide_id=1)],
            evidence=MagicMock(),
            case_dir=".",
            turn_index=1,
        )

        worker._apply_content_patches.assert_not_called()


class TestRenderedTextPreservation:
    """B-family guards must use rendered visibility, not only HTML strings."""

    BASE = """
    <html><head><style>
      body { margin: 0; width: 1280px; height: 720px; }
      .detail { position: absolute; left: 100px; top: 160px; }
    </style></head><body>
      <h1>Operating model</h1>
      <section class="detail"><span>Efficiency compounds at scale</span></section>
    </body></html>
    """

    @staticmethod
    def _render(html):
        from app.modules.redeck.html_spatial_state import extract_html_slide_state
        return extract_html_slide_state(1, html)

    @pytest.mark.parametrize(
        "hiding_css",
        ["display: none;", "opacity: 0;"],
    )
    def test_rendered_guard_rejects_css_hidden_text(self, hiding_css):
        from app.modules.redeck.repair_utils import (
            validate_rendered_text_preservation,
            validate_visual_repair_scope,
        )

        candidate = self.BASE.replace(
            "position: absolute;", f"position: absolute; {hiding_css}",
        )
        source_ok, source_reason = validate_visual_repair_scope(self.BASE, candidate)
        assert not source_ok
        assert "hidden" in source_reason

        rendered_ok, reason = validate_rendered_text_preservation(
            self._render(self.BASE), self._render(candidate),
        )
        assert not rendered_ok
        assert "Efficiency" in reason

    def test_rendered_guard_allows_style_only_relayout(self):
        from app.modules.redeck.repair_utils import (
            validate_rendered_text_preservation,
        )

        candidate = self.BASE.replace("left: 100px", "left: 420px")
        before = self._render(self.BASE)
        after = self._render(candidate)
        assert before.visible_text_runs == [
            "Operating model", "Efficiency compounds at scale",
        ]
        assert after.visible_text_runs == before.visible_text_runs
        assert validate_rendered_text_preservation(before, after)[0]

    def test_rendered_guard_allows_clipped_source_text_to_become_visible(self):
        from app.modules.redeck.repair_utils import (
            validate_rendered_text_preservation,
        )

        before = SimpleNamespace(visible_text_runs=["Title", "Visible point"])
        after = SimpleNamespace(
            visible_text_runs=["Title", "Visible point", "Clipped detail"],
        )

        assert validate_rendered_text_preservation(
            before, after, allow_revealed_text=True,
        )[0]
        assert not validate_rendered_text_preservation(before, after)[0]

    def test_rendered_guard_rejects_reordered_visible_text(self):
        from app.modules.redeck.repair_utils import (
            validate_rendered_text_preservation,
        )

        before = SimpleNamespace(visible_text_runs=["Title", "First", "Second"])
        after = SimpleNamespace(visible_text_runs=["Title", "Second", "First"])

        ok, reason = validate_rendered_text_preservation(
            before, after, allow_revealed_text=True,
        )
        assert not ok
        assert "reordered" in reason

    def test_source_scope_allows_reordered_semantic_units(self):
        from app.modules.redeck.repair_utils import validate_visual_repair_scope

        before = (
            "<html><body><section><h2>Interpretation</h2>"
            "<p>The chart shows a widening spread.</p></section>"
            "<aside><p>Supporting note</p></aside></body></html>"
        )
        after = (
            "<html><body><aside><p>Supporting note</p></aside>"
            "<section><h2>Interpretation</h2>"
            "<p>The chart shows a widening spread.</p></section></body></html>"
        )

        ok, reason = validate_visual_repair_scope(before, after)

        assert ok, reason

    @pytest.mark.parametrize(
        "after",
        [
            "<html><body><p>Existing claim</p></body></html>",
            "<html><body><p>Existing claim and invented qualifier</p>"
            "<p>Supporting note</p></body></html>",
        ],
    )
    def test_source_scope_still_rejects_text_deletion_or_addition(self, after):
        from app.modules.redeck.repair_utils import validate_visual_repair_scope

        before = (
            "<html><body><p>Existing claim</p>"
            "<p>Supporting note</p></body></html>"
        )

        ok, reason = validate_visual_repair_scope(before, after)

        assert not ok
        assert "source-visible text content changed" in reason

    def test_formatting_guard_allows_editorial_prefix_removal_only(self):
        from app.modules.redeck.repair_utils import (
            validate_rendered_text_preservation,
            validate_visual_repair_scope,
        )

        before_html = (
            '<html><body><p>Add evidence bullet: '
            '"Graph-quality evidence: ROC-AUC improves 94.75%."</p></body></html>'
        )
        after_html = (
            '<html><body><p>Graph-quality evidence: '
            'ROC-AUC improves 94.75%.</p></body></html>'
        )
        ok, reason = validate_visual_repair_scope(
            before_html,
            after_html,
            allow_text_formatting_change=True,
        )
        assert ok, reason

        before_state = SimpleNamespace(
            visible_text_runs=[
                'Add evidence bullet: "Graph-quality evidence: '
                'ROC-AUC improves 94.75%."',
            ],
        )
        after_state = SimpleNamespace(
            visible_text_runs=[
                "Graph-quality evidence: ROC-AUC improves 94.75%.",
            ],
        )
        ok, reason = validate_rendered_text_preservation(
            before_state,
            after_state,
            allow_text_formatting_change=True,
        )
        assert ok, reason

        changed_number = after_html.replace("94.75", "90.00")
        ok, reason = validate_visual_repair_scope(
            before_html,
            changed_number,
            allow_text_formatting_change=True,
        )
        assert not ok
        assert "visible text" in reason

    def test_form_redundancy_contract_allows_duplicate_text_rewrite(self):
        from app.modules.redeck.repair_utils import (
            issues_allow_dominant_element_removal,
            issues_allow_visible_text_change,
            validate_repair_not_visual_compression,
            validate_rendered_text_preservation,
            validate_visual_repair_scope,
        )
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue, IssueEvidence

        issue = Issue(
            issue_id="B14_slide9",
            rubric_id="B14",
            issue_type="form_redundancy",
            severity=Severity.MAJOR,
            affected_slides=[9],
            evidence=IssueEvidence(description="Figure 2 statement is duplicated."),
            planned_fix="Remove the duplicate Figure 2 bullet and rewrite the remaining sentence.",
            fix_detail=FixDetail(
                correct_content="Retain one Figure 2 summary only.",
                target_location="duplicate bullet under physiological plausibility",
                action_type="remove_element",
            ),
        )
        before_html = (
            "<html><body><p>Fp to T summary</p>"
            "<li>Figure 2 repeats frontal-to-temporal propagation.</li>"
            "<li>Figure 2 repeats frontal-to-temporal propagation.</li></body></html>"
        )
        after_html = (
            "<html><body><p>Fp to T summary</p>"
            "<li>Activation progresses from frontal to temporal channels.</li></body></html>"
        )

        assert issues_allow_visible_text_change([issue])
        issue.fix_detail.action_type = "restructure_layout"
        assert issues_allow_visible_text_change([issue])
        issue.fix_detail.action_type = "remove_element"
        ok, reason = validate_visual_repair_scope(before_html, after_html)
        assert not ok
        assert "visible text" in reason

        ok, reason = validate_visual_repair_scope(
            before_html,
            after_html,
            allow_text_content_change=issues_allow_visible_text_change([issue]),
        )
        assert ok, reason

        ok, reason = validate_rendered_text_preservation(
            SimpleNamespace(visible_text_runs=[
                "Fp to T summary",
                "Figure 2 repeats frontal-to-temporal propagation.",
                "Figure 2 repeats frontal-to-temporal propagation.",
            ]),
            SimpleNamespace(visible_text_runs=[
                "Fp to T summary",
                "Activation progresses from frontal to temporal channels.",
            ]),
            allow_text_content_change=issues_allow_visible_text_change([issue]),
        )
        assert ok, reason

        issue.planned_fix = "Remove the redundant left best-model hero callout block."
        assert issues_allow_dominant_element_removal([issue])

        common_fonts = "".join(f".t{i}{{font-size:14px}}" for i in range(20))
        before_compressed = (
            f"<style>.hero{{font-size:68px}}.title{{font-size:31px}}{common_fonts}</style>"
            "<body><div class='hero'>GPT-5</div><p>Table remains</p></body>"
        )
        after_compressed = (
            f"<style>.title{{font-size:31px}}{common_fonts}</style>"
            "<body><p>Table remains</p></body>"
        )
        ok, reason = validate_repair_not_visual_compression(
            before_compressed,
            after_compressed,
        )
        assert not ok
        assert "dominant font" in reason

        ok, reason = validate_repair_not_visual_compression(
            before_compressed,
            after_compressed,
            allow_dominant_element_removal=issues_allow_dominant_element_removal([issue]),
        )
        assert ok, reason

    def test_dispatcher_visual_gates_wire_form_redundancy_text_contract(self):
        dispatcher = Path("app/modules/redeck/dispatcher.py").read_text()

        assert "may_change_text_content = issues_allow_visible_text_change" in dispatcher
        assert dispatcher.count("allow_text_content_change=may_change_text_content") >= 2
        assert 'i.issue_type != "chart_misinterpretation"' in dispatcher
        assert "allow_dominant_element_removal" in dispatcher

    def test_explicit_support_copy_compression_contract_allows_targeted_rewrite(self):
        from app.modules.redeck.repair_utils import (
            issues_allow_support_copy_compression,
            issues_allow_visible_text_change,
        )
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue, IssueEvidence

        issue = Issue(
            issue_id="B09_dense_cards",
            rubric_id="B09",
            issue_type="density_imbalance",
            severity=Severity.MAJOR,
            affected_slides=[1],
            evidence=IssueEvidence(
                description="Long support notes make repeated cards unreadable.",
            ),
            planned_fix=(
                "Preserve all factual distinctions; concise meaning-preserving "
                "support copy is allowed when geometry alone cannot fit."
            ),
            fix_detail=FixDetail(action_type="compress_support_copy"),
        )

        assert issues_allow_support_copy_compression([issue])
        assert issues_allow_visible_text_change([issue])

        issue.fix_detail.action_type = ""
        assert not issues_allow_support_copy_compression([issue])
        assert not issues_allow_visible_text_change([issue])

    def test_support_copy_compression_is_explained_as_a_narrow_exception(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue, IssueEvidence

        repair = AgentRepair(MagicMock())
        issue = Issue(
            issue_id="B09_dense_cards",
            rubric_id="B09",
            issue_type="density_imbalance",
            severity=Severity.MAJOR,
            affected_slides=[1],
            evidence=IssueEvidence(description="Dense repeated support notes."),
            planned_fix="Shorten support copy only when geometry is insufficient.",
            fix_detail=FixDetail(action_type="compress_support_copy"),
        )
        message = repair._build_initial_message(
            code="<html><body><div class='card'>Dense note</div></body></html>",
            all_issues=[issue],
            spatial_info="",
            evidence_text="",
            must_contain=[],
            must_not=[],
            content_checklist="",
            bp_slide=None,
            viz_data=None,
            adjacent_context="",
        )

        assert "AUTHORIZED SUPPORT-COPY COMPRESSION" in message
        assert "preserving every factual distinction" in message
        assert "LAYOUT ONLY" not in message

    def test_dispatcher_rejects_new_overlap_and_clipping_regressions(self):
        dispatcher = Path("app/modules/redeck/dispatcher.py").read_text()

        assert "clipping regression" in dispatcher
        assert "new significant overlap" in dispatcher
        assert "accepting %d new significant overlap" not in dispatcher
        assert "tolerating %d new significant overlaps" not in dispatcher

    def test_agent_submit_gate_blocks_unsourced_new_text_for_text_exceptions(self):
        agent_repair = Path("app/modules/redeck/agent_repair.py").read_text()

        assert "significant new text without source search" in agent_repair
        assert "state.allow_visible_text_change" in agent_repair
        assert "Do not introduce limitation/scope/causal wording" in agent_repair

    def test_repair_prompt_routes_whitespace_to_strategy_choice(self):
        prompt = Path("app/prompts/codegen/slide_html_repair.system.md").read_text()
        assert "reflow" in prompt.lower()

    def test_formatting_contract_allows_raw_latex_normalization(self):
        from app.modules.redeck.repair_utils import (
            issues_allow_visible_text_change,
            validate_rendered_text_preservation,
            validate_visual_repair_scope,
        )
        from app.schemas.common import Severity
        from app.schemas.issue import Issue, IssueEvidence

        issue = Issue(
            issue_id="B12_slide4",
            rubric_id="B12",
            issue_type="formatting_error",
            severity=Severity.MAJOR,
            affected_slides=[4],
            evidence=IssueEvidence(
                description="Raw LaTeX/code artifacts such as \\mathbf{E}_{\\tau} and \\mathcal{Q} are visible."
            ),
            planned_fix="Replace raw LaTeX-like strings with readable inline notation.",
        )
        before_html = (
            "<html><body><p>Initialize \\mathbf{E}_{\\tau}^* \\leftarrow "
            "\\mathbf{E}_{\\tau}^{ini}; submit \\mathcal{Q}_{\\tau}^{ij}.</p></body></html>"
        )
        after_html = (
            "<html><body><p>Initialize E_tau* <- E_tau(init); "
            "submit Q_tau(i,j).</p></body></html>"
        )

        assert issues_allow_visible_text_change([issue])
        ok, reason = validate_visual_repair_scope(before_html, after_html)
        assert not ok
        assert "visible text" in reason

        ok, reason = validate_visual_repair_scope(
            before_html,
            after_html,
            allow_text_content_change=issues_allow_visible_text_change([issue]),
        )
        assert ok, reason

        ok, reason = validate_rendered_text_preservation(
            SimpleNamespace(visible_text_runs=[
                r"Initialize \mathbf{E}_{\tau}^* \leftarrow \mathbf{E}_{\tau}^{ini}; submit \mathcal{Q}_{\tau}^{ij}.",
            ]),
            SimpleNamespace(visible_text_runs=[
                "Initialize E_tau* <- E_tau(init); submit Q_tau(i,j).",
            ]),
            allow_text_content_change=issues_allow_visible_text_change([issue]),
        )
        assert ok, reason

    @pytest.mark.parametrize(
        "hidden_markup",
        [
            '<span style="display:none">Efficiency compounds at scale</span>',
            '<span class="sr-only">Efficiency compounds at scale</span>',
            '<span style="position:absolute;left:-9999px">Efficiency compounds at scale</span>',
        ],
    )
    def test_source_guard_rejects_hidden_duplicate_text(self, hidden_markup):
        from app.modules.redeck.repair_utils import validate_visual_repair_scope

        base = self.BASE.replace(
            "</style>", ".sr-only{position:absolute;left:-9999px}</style>",
        )
        candidate = base.replace("</body>", f"{hidden_markup}</body>")

        ok, reason = validate_visual_repair_scope(base, candidate)

        assert not ok
        assert "hidden" in reason

    def test_b09_and_submit_gate_do_not_use_coverage_as_verdict(self):
        repo = Path(__file__).resolve().parents[1]
        probe = (repo / "app/prompts/probes/B09_density_imbalance.md").read_text()
        repair_prompt = (
            repo / "app/prompts/codegen/slide_html_repair.system.md"
        ).read_text()
        agent_source = (repo / "app/modules/redeck/agent_repair.py").read_text()

        assert "none is a pass/fail rule" in probe
        assert "Never prescribe new bullets" in probe
        assert "Choose the scale of intervention" in probe
        assert "Do not use captions, source notes, citations, or footer text" in probe
        # Removed: overly specific prompt content assertions from old d178-focused iterations
        assert "STRATEGY CHOICE" in agent_source
        assert "larger reflow of existing elements" in agent_source
        assert "current render" in agent_source
        assert "_cov_low_bounced" not in agent_source
        assert "visual_repair_may_add_content" not in agent_source

    def test_composition_prompt_uses_directional_not_fixed_structure_guidance(self):
        repo = Path(__file__).resolve().parents[1]
        repair_prompt = (
            repo / "app/prompts/codegen/slide_html_repair.system.md"
        ).read_text()
        agent_source = (repo / "app/modules/redeck/agent_repair.py").read_text()

        assert "DOM order is not frozen" in repair_prompt
        assert "diagnosed causal cluster" in repair_prompt
        assert "preserve every visible string and its reading order exactly" not in repair_prompt
        assert "geometry is not frozen" in agent_source
        assert "recoverable same-region intermediate state" in agent_source


class TestFixedFormatTextBudgetGuard:
    def test_flags_new_long_title_and_footer(self):
        from app.modules.redeck.agent_repair import (
            _fixed_format_text_budget_warnings,
        )

        before = """
        <html><body>
          <div class="title">Graph-level reasoning characteristics</div>
          <div class="bottom-bar">GPT-5 leads on graph sparsity and JSD.</div>
        </body></html>
        """
        after = """
        <html><body>
          <div class="title">Overall, the benchmark reveals distinct reasoning behaviors and scaling trends among the evaluated EEG LLMs. Smaller models tend to show higher diversity.</div>
          <div class="bottom-bar">Overall, the benchmark reveals distinct reasoning behaviors and scaling trends among the evaluated LLMs. Smaller models tend to show higher diversity and lower stability, whereas larger models yield more clinically plausible and consistent graph structures, with GPT-5 achieving the highest F1 score, edge agreement rate, and lowest divergence in the benchmark.</div>
        </body></html>
        """

        warnings = _fixed_format_text_budget_warnings(
            after, baseline_html=before,
        )

        assert any("title/header is over budget" in item for item in warnings)
        assert any("bottom/footer bar is over budget" in item for item in warnings)

    def test_ignores_preexisting_fixed_format_budget_violation(self):
        from app.modules.redeck.agent_repair import (
            _fixed_format_text_budget_warnings,
        )

        before = """
        <html><body>
          <div class="bottom-bar">This already long footer sentence exists in the baseline and should not block an unrelated local repair even though it is too verbose for a bottom region with limited space and fixed height.</div>
        </body></html>
        """
        after = before.replace("<body>", "<body><p>Small local body edit.</p>")

        assert _fixed_format_text_budget_warnings(after, baseline_html=before) == []


class TestVisualDowngradeGuard:
    """Repairs should not look fixed because content structure vanished."""

    def test_rejects_table_removed_even_when_text_is_preserved(self):
        from app.modules.redeck.repair_utils import (
            validate_repair_not_visual_downgrade,
        )

        before = """
        <html><body>
          <h1>Evaluation</h1>
          <table>
            <tr><th>Method</th><th>Score</th></tr>
            <tr><td>Baseline</td><td>72%</td></tr>
            <tr><td>ReDeck</td><td>89%</td></tr>
          </table>
        </body></html>
        """
        after = """
        <html><body>
          <h1>Evaluation</h1>
          <div>Method Score Baseline 72% ReDeck 89%</div>
        </body></html>
        """

        ok, reason = validate_repair_not_visual_downgrade(before, after)

        assert not ok
        assert "table" in reason

    def test_rejects_large_list_item_collapse(self):
        from app.modules.redeck.repair_utils import (
            validate_repair_not_visual_downgrade,
        )

        before = """
        <html><body><ul>
          <li>Collect source table rows</li>
          <li>Extract method names</li>
          <li>Preserve numeric scores</li>
          <li>Repair spatial overlap</li>
        </ul></body></html>
        """
        after = """
        <html><body><ul>
          <li>Collect source table rows</li>
          <li>Repair spatial overlap</li>
        </ul></body></html>
        """

        ok, reason = validate_repair_not_visual_downgrade(before, after)

        assert not ok
        assert "list item" in reason

    def test_allows_style_only_relayout_with_preserved_media(self):
        from app.modules.redeck.repair_utils import (
            validate_repair_not_visual_downgrade,
        )

        before = """
        <html><body>
          <style>.chart{left:80px;top:120px}</style>
          <img src="chart.png" alt="Chart">
          <p>Zipf exponent beta 0.56 and R2 0.80</p>
        </body></html>
        """
        after = before.replace("left:80px", "left:180px")

        ok, reason = validate_repair_not_visual_downgrade(before, after)

        assert ok, reason

    def test_rejects_dominant_hero_font_collapse(self):
        from app.modules.redeck.repair_utils import (
            validate_repair_not_visual_compression,
        )

        before = """
        <style>
          .hero { font-size: 76px; margin: 0 0 8px 0; }
          .body { font-size: 17px; padding: 18px; }
        </style>
        """
        after = """
        <style>
          .hero { font-size: 52px; margin: 0 0 5px 0; }
          .body { font-size: 14px; padding: 14px; }
        </style>
        """

        ok, reason = validate_repair_not_visual_compression(before, after)

        assert not ok
        assert "dominant font" in reason

    def test_allows_modest_local_font_adjustment(self):
        from app.modules.redeck.repair_utils import (
            validate_repair_not_visual_compression,
        )

        before = """
        <style>
          .hero { font-size: 76px; margin: 0 0 8px 0; }
          .body { font-size: 17px; padding: 18px; }
        </style>
        """
        after = """
        <style>
          .hero { font-size: 64px; margin: 0 0 7px 0; }
          .body { font-size: 16px; padding: 17px; }
        </style>
        """

        ok, reason = validate_repair_not_visual_compression(before, after)

        assert ok, reason

    def test_allows_repeated_peer_score_calibration(self):
        from app.modules.redeck.repair_utils import (
            validate_repair_not_visual_compression,
        )

        before = """
        <style>
          .title { font-size: 34px; }
          .score .num { font-size: 72px; }
          .body { font-size: 16px; padding: 14px; }
        </style>
        <div class="score"><span class="num">8.4</span></div>
        <div class="score"><span class="num">8.9</span></div>
        <div class="score"><span class="num">7.6</span></div>
        <div class="score"><span class="num">6.8</span></div>
        """
        after = before.replace("font-size: 72px", "font-size: 48px")

        ok, reason = validate_repair_not_visual_compression(before, after)

        assert ok, reason

    def test_repeated_peer_exemption_does_not_hide_global_compression(self):
        from app.modules.redeck.repair_utils import (
            validate_repair_not_visual_compression,
        )

        before = """
        <style>
          .score .num { font-size: 72px; }
          .body { font-size: 20px; padding: 18px; }
          .note { font-size: 16px; }
        </style>
        <div class="score"><span class="num">8.4</span></div>
        <div class="score"><span class="num">8.9</span></div>
        <p class="body">Body</p><p class="note">Note</p>
        """
        after = before.replace("font-size: 72px", "font-size: 44px")
        after = after.replace("font-size: 20px", "font-size: 10px")
        after = after.replace("font-size: 16px", "font-size: 8px")

        ok, reason = validate_repair_not_visual_compression(before, after)

        assert not ok
        assert "average font size" in reason

    def test_allows_oversized_display_scale_calibration(self):
        from app.modules.redeck.repair_utils import (
            validate_repair_not_visual_compression,
        )

        before = """
        <style>
          .title { font-size: 38px; margin: 0 0 8px 0; }
          .hero { font-size: 92px; padding: 18px 20px; }
          .subtitle { font-size: 18px; margin: 0; }
          .card-title { font-size: 22px; margin: 0 0 12px 0; }
          .table td { font-size: 16px; padding: 15px 14px; }
          .table th { font-size: 15px; padding: 14px 14px; }
          .note { font-size: 14px; padding: 14px 16px; }
          .summary { font-size: 28px; padding: 18px; }
        </style>
        """
        after = """
        <style>
          .title { font-size: 34px; margin: 0 0 6px 0; }
          .hero { font-size: 58px; padding: 14px 18px; }
          .subtitle { font-size: 16px; margin: 0; }
          .card-title { font-size: 20px; margin: 0 0 6px 0; }
          .table td { font-size: 12px; padding: 7px 8px; }
          .table th { font-size: 12px; padding: 7px 8px; }
          .note { font-size: 12px; padding: 8px 10px; }
          .summary { font-size: 20px; padding: 12px; }
        </style>
        """

        ok, reason = validate_repair_not_visual_compression(before, after)

        assert ok, reason

    def test_raw_image_replacement_preserves_media_slot_semantics(self):
        from app.modules.redeck.repair_utils import validate_visual_repair_scope

        before = """
        <html><body>
          <figure aria-label="Figure slot">
            <img src="raw-chart.png" alt="Growth chart" role="img">
          </figure>
          <p>Growth accelerates after rollout</p>
        </body></html>
        """
        changed_src = before.replace("raw-chart.png", "cropped-chart.png")
        ok, reason = validate_visual_repair_scope(
            before,
            changed_src,
            allow_image_replacement=True,
        )
        assert ok, reason

        changed_alt = changed_src.replace("Growth chart", "Decorative chart")
        ok, reason = validate_visual_repair_scope(
            before,
            changed_alt,
            allow_image_replacement=True,
        )
        assert not ok
        assert "media references" in reason or "accessibility" in reason

    def test_raw_image_replacement_rejects_media_order_change(self):
        from app.modules.redeck.repair_utils import validate_visual_repair_scope

        before = """
        <html><body>
          <img src="raw-chart.png" alt="Main chart">
          <img src="logo.png" alt="Partner logo">
          <p>Growth accelerates after rollout</p>
        </body></html>
        """
        after = """
        <html><body>
          <img src="logo.png" alt="Partner logo">
          <img src="cropped-chart.png" alt="Main chart">
          <p>Growth accelerates after rollout</p>
        </body></html>
        """

        ok, reason = validate_visual_repair_scope(
            before,
            after,
            allow_image_replacement=True,
        )

        assert not ok
        assert "media references" in reason

    def test_svg_scope_rejects_connector_deletion(self):
        from app.modules.redeck.repair_utils import validate_svg_repair_scope

        before = """
        <html><body><h1>Diagram</h1>
          <svg aria-label="flow" width="500" height="200">
            <rect x="20" y="60" width="120" height="60"/>
            <line x1="140" y1="90" x2="300" y2="90"/>
            <rect x="300" y="60" width="120" height="60"/>
            <text x="50" y="95">Source</text>
            <text x="330" y="95">Target</text>
          </svg>
        </body></html>
        """
        after = before.replace(
            '<line x1="140" y1="90" x2="300" y2="90"/>',
            "",
        )

        ok, reason = validate_svg_repair_scope(before, after)

        assert not ok
        assert "connector" in reason


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


class TestRegenAcceptanceGuards:
    """Regression tests for layout-only regen content preservation."""

    def _repair(self):
        from app.modules.redeck.agent_repair import AgentRepair
        repair = AgentRepair.__new__(AgentRepair)
        repair._current_issues = [
            SimpleNamespace(issue_type="overlap", status=SimpleNamespace(value="open"))
        ]
        return repair

    def test_layout_only_regen_rejects_new_numbers(self):
        repair = self._repair()
        old_code = "<html><body><div>Zipf exponent beta 0.56 and R2 0.80</div></body></html>"
        new_code = "<html><body><div>Zipf exponent beta 0.56 and R2 0.92</div></body></html>"

        accepted, reason = repair._regen_acceptance_check(
            old_code,
            new_code,
            SimpleNamespace(),
            {"total_issues": 5},
            {"total_issues": 2},
            False,
            [],
        )

        assert not accepted
        assert "numeric claims" in reason

    def test_layout_only_regen_rejects_low_text_retention(self):
        repair = self._repair()
        old_code = "<html><body><div>ingredient vocabulary sublinear scaling recipe complexity statistical law corpus evidence</div></body></html>"
        new_code = "<html><body><div>model migration throughput partition scheduling server acceleration communication workload</div></body></html>"

        accepted, reason = repair._regen_acceptance_check(
            old_code,
            new_code,
            SimpleNamespace(),
            {"total_issues": 5},
            {"total_issues": 2},
            False,
            [],
        )

        assert not accepted
        assert "rewrote too much text" in reason

    def test_layout_only_regen_rejects_table_structure_drop(self):
        repair = self._repair()
        old_code = """
        <html><body>
          <table>
            <tr><th>Method</th><th>Score</th></tr>
            <tr><td>Baseline</td><td>72%</td></tr>
            <tr><td>ReDeck</td><td>89%</td></tr>
          </table>
        </body></html>
        """
        new_code = """
        <html><body>
          <div class="columns">
            <div>Method Score</div>
            <div>Baseline 72%</div>
            <div>ReDeck 89%</div>
          </div>
        </body></html>
        """

        accepted, reason = repair._regen_acceptance_check(
            old_code,
            new_code,
            SimpleNamespace(),
            {"total_issues": 5},
            {"total_issues": 0},
            False,
            [],
        )

        assert not accepted
        assert "visual downgrade" in reason
        assert "table" in reason

    def test_layout_only_regen_allows_css_only_relayout(self):
        repair = self._repair()
        old_code = """
        <html><body>
          <style>.panel{left:80px;top:120px}</style>
          <img src="chart.png" alt="Chart">
          <p>Zipf exponent beta 0.56 and R2 0.80</p>
        </body></html>
        """
        new_code = old_code.replace("left:80px", "left:180px")

        accepted, reason = repair._regen_acceptance_check(
            old_code,
            new_code,
            SimpleNamespace(),
            {"total_issues": 5},
            {"total_issues": 0},
            False,
            [],
        )

        assert accepted, reason


class TestIssueClusterBrief:
    """Clustered issue context should be visible to the repair agent."""

    @staticmethod
    def _issue(issue_type, description, target_location=""):
        return SimpleNamespace(
            issue_type=issue_type,
            rubric_id="B4",
            evidence=SimpleNamespace(description=description),
            why_this_fails="",
            planned_fix="",
            fix_detail=SimpleNamespace(
                target_location=target_location,
                correct_content="",
            ),
        )

    def test_clusters_footer_findings(self):
        from app.modules.redeck.agent_repair import AgentRepair

        brief = AgentRepair._build_issue_cluster_brief([
            self._issue("text_overflow", "Footer source note overflows bottom edge"),
            self._issue("low_contrast", "Bottom citation text is too faint"),
            self._issue("overlap", "Right column cards overlap each other"),
        ])

        assert "Issue Cluster Brief" in brief
        assert "footer/bottom region" in brief
        assert "right column/panel" in brief
        assert "text_overflow" in brief

    def test_right_edge_clipping_is_not_misclassified_as_svg(self):
        from app.modules.redeck.agent_repair import AgentRepair

        issue = self._issue(
            "text_overflow",
            "Body text clips at the right edge of the card",
            ".summary-card",
        )

        assert AgentRepair._issue_cluster_label(issue) == "shared layout conflict"

    def test_low_contrast_scope_includes_current_deterministic_targets(self):
        from app.modules.redeck.agent_repair import AgentRepair

        compact = """
SLIDE 8 — 69 elements | canvas 1280×720 px

DETERMINISTIC FINDINGS (2):
❌ LOW CONTRAST: "GPT-5"
   ratio: 2.6:1 (WCAG AA min: 3.0:1 for 76px text)
   fg: rgb(236, 125, 112) | bg: rgb(244,250,247)
❌ OVERLAP: "Unrelated" ↔ "Other"
   intersection: 20×10 px

📐 LAYOUT ANCHOR (1 elements):
  div .metric: (36,119) 250×72px font:76px  "GPT-5"
""".strip()
        issue = self._issue(
            "low_contrast",
            "Old judge text says section labels are too pale",
        )

        scoped = AgentRepair._scope_spatial_context(compact, [issue])

        assert "DETERMINISTIC LOW-CONTRAST TARGETS" in scoped
        assert "LOW CONTRAST" in scoped
        assert "GPT-5" in scoped
        assert "2.6:1" in scoped
        assert "OVERLAP" not in scoped


class TestRepairFailureMemory:
    def test_loads_actual_trace_failure_strings(self, tmp_path):
        from app.modules.redeck.agent_repair import AgentRepair

        log_dir = tmp_path / "turn_01" / "repair_logs"
        log_dir.mkdir(parents=True)
        (log_dir / "slide_03_attempt_0.json").write_text(json.dumps([
            {"role": "user", "content": "RENDERED TEXT REGRESSION: title disappeared"},
            {"role": "user", "content": "Regen REJECTED: spatial regression 2 -> 5"},
            {"role": "user", "content": "SUBMIT BLOCKED - overlap remains"},
        ]))

        context = AgentRepair._load_previous_repair_failures(
            str(tmp_path), turn_index=2, slide_id=3,
        )

        assert "RENDERED TEXT REGRESSION" in context
        assert "Regen REJECTED" in context
        assert "SUBMIT BLOCKED" in context

    def test_multimodal_initial_message_accepts_previous_failure_context(self):
        from app.modules.redeck.agent_repair import AgentRepair

        llm = MagicMock()
        llm.call_multiturn.return_value = json.dumps({"tool": "submit"})
        repair = AgentRepair(
            llm,
            repair_config={"enable_macro_planning": False},
        )
        issue = SimpleNamespace(
            issue_type="low_contrast",
            rubric_id="B5",
            status=SimpleNamespace(value="open"),
        )
        initial = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            {"type": "text", "text": "Current slide"},
        ]

        repair._run_single_repair(
            slide_id=1,
            code="<html><body><p>Text</p></body></html>",
            all_issues=[issue],
            must_not=[],
            must_contain=[],
            initial_msg=initial,
            state_template={
                "codegen_compiler": MagicMock(),
                "case_dir": ".",
                "evidence": None,
                "bp_slide": None,
            },
            prev_failures_ctx="Previous failure: clipping remained",
        )

        first_messages = llm.call_multiturn.call_args.kwargs["messages"]
        user_content = first_messages[1]["content"]
        assert isinstance(user_content, list)
        assert "Previous failure" in user_content[-1]["text"]


class TestVisualPreviewRouting:
    def test_raw_figure_issue_enables_render_preview(self):
        from app.modules.redeck.dispatcher import ReDeckWorker
        from app.schemas.common import Severity
        from app.schemas.issue import Issue

        worker = ReDeckWorker(MagicMock())
        issue = Issue(
            issue_id="B17_slide1",
            rubric_id="B17",
            issue_type="raw_figure",
            severity=Severity.MAJOR,
            affected_slides=[1],
        )
        compiler = SimpleNamespace(slide_codes={1: "<html><body>Figure</body></html>"})

        with patch("app.modules.redeck.dispatcher.AgentRepair") as repair_cls:
            repair_cls.return_value.repair.return_value = None
            worker._repair_one_slide(
                1,
                compiler.slide_codes[1],
                [issue],
                None,
                MagicMock(),
                compiler,
                ".",
            )

        repair_config = repair_cls.call_args.kwargs["repair_config"]
        assert repair_config["enable_render_preview"] is True


class TestEditMatchSafety:
    def test_ambiguous_global_replacement_is_rejected(self):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState

        code = "<style>.card{color:red}.note{color:red}</style>"
        repair = AgentRepair(MagicMock())
        repair._test_compile = MagicMock(return_value=True)
        state = AgentState(
            original_code=code,
            current_code=code,
            checkpoints=[code],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        message, changed = repair._tool_apply_edits({
            "edits": [{"search": "color:red", "replace": "color:blue"}],
        }, state)

        assert not changed
        assert "matches 2 times" in message
        assert state.current_code == code

    def test_explicit_expected_matches_allows_verified_replacement(self):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState

        code = "<style>.card{color:red}.note{color:red}</style>"
        repair = AgentRepair(MagicMock())
        repair._test_compile = MagicMock(return_value=True)
        state = AgentState(
            original_code=code,
            current_code=code,
            checkpoints=[code],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        _, changed = repair._tool_apply_edits({
            "edits": [{
                "search": "color:red",
                "replace": "color:blue",
                "expected_matches": 2,
            }],
        }, state)

        assert changed
        assert state.current_code.count("color:blue") == 2

    def test_occurrence_feedback_reports_single_targeted_match(self):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState

        code = "<ul><li>A</li></ul><ul><li>B</li></ul>"
        repair = AgentRepair(MagicMock())
        repair._test_compile = MagicMock(return_value=True)
        state = AgentState(
            original_code=code,
            current_code=code,
            checkpoints=[code],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        message, changed = repair._tool_apply_edits({
            "edits": [{
                "search": "</ul>",
                "replace": "<li>C</li></ul>",
                "occurrence": 1,
            }],
        }, state)

        assert changed
        assert "replaced occurrence 1 of 2 matches" in message
        assert "replaced 2 occurrences" not in message
        assert state.current_code == "<ul><li>A</li><li>C</li></ul><ul><li>B</li></ul>"

    def test_multi_tool_response_executes_first_and_discards_speculative_actions(self):
        from app.modules.redeck.agent_repair import AgentRepair

        repair = AgentRepair(MagicMock())
        response = "\n".join([
            json.dumps({"tool": "apply_edits", "edits": []}),
            json.dumps({"tool": "verify_layout"}),
            json.dumps({"tool": "submit"}),
        ])

        action = repair._parse_action(response)

        assert action == {"tool": "apply_edits", "edits": []}
        assert repair._pending_actions == []
        assert repair._multi_action_ignored_count == 2
        assert repair._last_parse_error_message == ""


class TestVerifiedCheckpointValidity:
    def test_rendered_text_signal_is_advisory_not_checkpoint_blocker(self, monkeypatch):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue

        original = """
        <html><head><style>
        body{width:1280px;height:720px;margin:0;overflow:hidden;background:#fff}
        .slide{position:relative;width:1280px;height:720px}
        .title{position:absolute;left:80px;top:80px;width:520px;height:60px;color:#111;font-size:36px}
        </style></head>
        <body><div class="slide"><div class="title">Important visible claim</div></div></body></html>
        """
        current = original.replace("color:#111", "color:#222")

        def fake_rendered_text_preservation(*_args, **_kwargs):
            return False, "simulated brittle rendered-token mismatch"

        monkeypatch.setattr(
            "app.modules.redeck.repair_utils.validate_rendered_text_preservation",
            fake_rendered_text_preservation,
        )
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="B5_slide1",
            rubric_id="B5",
            issue_type="low_contrast",
            severity=Severity.MAJOR,
            affected_slides=[1],
        )]
        state = AgentState(
            original_code=original,
            current_code=current,
            checkpoints=[original],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        result, _ = repair._tool_verify_layout(state)

        assert "VISIBLE TEXT CHANGE SIGNAL (advisory)" in str(result)
        assert state._last_verify_text_signal is True
        assert state.best_verified_code is None
        assert state.last_verified_code == current

    def test_new_interaction_is_not_saved_as_verified_checkpoint(self, monkeypatch):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue

        original = """
        <html><head><style>
        body{width:1280px;height:720px;margin:0;overflow:hidden;background:#fff}
        .slide{position:relative;width:1280px;height:720px}
        .title{position:absolute;left:80px;top:80px;width:520px;height:60px;color:#111;font-size:36px}
        </style></head>
        <body><div class="slide"><div class="title">Important visible claim</div></div></body></html>
        """
        current = original.replace("left:80px", "left:90px")

        monkeypatch.setattr(
            "app.modules.redeck.html_spatial_state.significant_issue_regressions",
            lambda *_args, **_kwargs: {
                "interaction": [("overlap", ("block_a", "block_b"))],
            },
        )
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="B3_slide1",
            rubric_id="B3",
            issue_type="overlap",
            severity=Severity.MAJOR,
            affected_slides=[1],
        )]
        state = AgentState(
            original_code=original,
            current_code=current,
            checkpoints=[original],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        result, _ = repair._tool_verify_layout(state)

        assert "NEW OVERLAP" in str(result)
        assert "not an automatic rollback instruction" in str(result)
        assert state.best_verified_code is None
        assert state.last_verified_code is None
        assert state.latest_safe_verified_code == current
        assert state.latest_safe_verified_revision == state.layout_revision

    def test_verify_layout_optionally_returns_same_revision_render(self, monkeypatch):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue

        original = """
        <html><head><style>
        body{width:1280px;height:720px;margin:0;overflow:hidden;background:#fff}
        .title{position:absolute;left:80px;top:80px;width:520px;height:60px;color:#111;font-size:36px}
        </style></head><body><div class="title">Visible title</div></body></html>
        """
        current = original.replace("color:#111", "color:#222")
        repair = AgentRepair(
            MagicMock(),
            repair_config={"enable_render_preview": True},
        )
        repair._current_issues = [Issue(
            issue_id="B5_slide1",
            rubric_id="B5",
            issue_type="low_contrast",
            severity=Severity.MAJOR,
            affected_slides=[1],
        )]
        monkeypatch.setattr(
            repair,
            "_render_slide_to_base64",
            lambda *_args, **_kwargs: "encoded-current-revision",
        )
        state = AgentState(
            original_code=original,
            current_code=current,
            checkpoints=[original],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        result, _ = repair._tool_verify_layout(state)

        assert isinstance(result, list)
        assert result[0]["type"] == "image_url"
        assert "encoded-current-revision" in result[0]["image_url"]["url"]
        assert "exact revision measured" in result[1]["text"]
        assert state.latest_visual_checkpoint_code == current
        assert state.latest_visual_checkpoint_hard_valid is True

    def test_baseline_small_fonts_are_context_not_repair_instruction(self):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue

        original = """
        <html><head><style>
        body{width:1280px;height:720px}.note{font-size:12px;position:absolute;left:20px}
        </style></head><body><p class="note">Baseline source note remains readable</p></body></html>
        """
        current = original.replace("left:20px", "left:30px")
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="B5_slide1",
            rubric_id="B5",
            issue_type="low_contrast",
            severity=Severity.MINOR,
            affected_slides=[1],
        )]
        state = AgentState(
            original_code=original,
            current_code=current,
            checkpoints=[original],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        result, _ = repair._tool_verify_layout(state)
        text = str(result)

        assert "Baseline contains" in text
        assert "Increase font or remove content" not in text

    def test_content_repair_compression_is_reported_and_not_checkpointed(self):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue

        original = """
        <html><head><style>
        body{width:1280px;height:720px}.hero{font-size:76px}.copy{font-size:17px}
        </style></head><body>
        <div class="hero">Fp to T</div><p class="copy">Existing source-backed claim</p>
        </body></html>
        """
        current = original.replace(
            ".hero{font-size:76px}",
            ".hero{font-size:52px}",
        ).replace(
            "</body>",
            "<p>Required missing entity text</p></body>",
        )
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="C04_slide1",
            rubric_id="C04",
            issue_type="missing_entity",
            severity=Severity.MINOR,
            affected_slides=[1],
        )]
        state = AgentState(
            original_code=original,
            current_code=current,
            checkpoints=[original],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        result, _ = repair._tool_verify_layout(state)

        assert "SHIPMENT GATE FAILED — VISUAL COMPRESSION" in str(result)
        assert state.best_verified_code is None
        assert state.last_verified_code is None
        assert state.latest_safe_verified_code is None


class TestTargetedResidualTracking:
    def test_target_residual_keeps_safe_intermediate_but_remains_unsubmittable(self):
        from app.modules.redeck.agent_repair import AgentRepair, AgentState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue, IssueEvidence

        original = """
        <html><head><style>
        body{width:1280px;height:720px;margin:0;overflow:hidden}
        .target{position:absolute;left:40px;top:100px;width:220px;height:24px;
          overflow:hidden;font-size:20px;line-height:28px}
        </style></head><body>
        <div class="target">Named target remains visibly clipped across two lines</div>
        </body></html>
        """
        current = original.replace("left:40px", "left:44px")
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="B04_slide1",
            rubric_id="B04",
            issue_type="text_overflow",
            severity=Severity.MAJOR,
            affected_slides=[1],
            evidence=IssueEvidence(
                object_refs=[".target"],
                description="The named target is clipped.",
            ),
        )]
        state = AgentState(
            original_code=original,
            current_code=current,
            checkpoints=[original],
            slide_id=1,
            codegen_compiler=MagicMock(),
            case_dir=".",
        )

        repair._tool_verify_layout(state)

        assert state._last_verify_targeted_residual_total > 0
        assert state.latest_safe_verified_code == current
        assert state.latest_safe_verified_revision == state.layout_revision
        assert state.best_verified_code is None

    def test_density_issue_tracks_named_card_visibility_not_unrelated_footer(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.modules.redeck.spatial_state import ContentBlock, SlideState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue, IssueEvidence

        card_note = ContentBlock(
            block_id="blk_card_note",
            var_name="div",
            shape_type="textbox",
            css_selector=".m-note",
            css_classes=("m-note",),
            dom_path="html/body/div.grid-card/div.m-note",
            text_chars=42,
            text_lines=["Named card support copy remains hidden"],
            is_clipped=True,
            clipped_bottom_px=24,
            bbox_px=(60, 620, 240, 54),
        )
        footer = ContentBlock(
            block_id="blk_footer",
            var_name="footer",
            shape_type="textbox",
            css_selector=".footer",
            css_classes=("footer",),
            dom_path="html/body/footer",
            text_chars=32,
            text_lines=["Unrelated baseline footer warning"],
            is_clipped=True,
            clipped_bottom_px=12,
            bbox_px=(40, 690, 1200, 24),
        )
        baseline = SlideState(
            slide_id=1,
            blocks=[card_note, footer],
            clipped_blocks=["blk_card_note", "blk_footer"],
        )
        current = SlideState(
            slide_id=1,
            blocks=[card_note, footer],
            clipped_blocks=["blk_card_note", "blk_footer"],
        )
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="B09_slide1",
            rubric_id="B09",
            issue_type="density_imbalance",
            severity=Severity.MAJOR,
            affected_slides=[1],
            evidence=IssueEvidence(
                object_refs=[".grid-card", ".m-note", ".bottom"],
                description="The lower repeated card grid is too dense.",
            ),
        )]

        residuals = repair._targeted_significant_issues(baseline, current)

        assert "clipped" in repair._targeted_residual_categories()
        assert residuals["clipped"] == ["blk_card_note"]

    def test_named_selector_survives_text_change_that_breaks_stable_identity(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.modules.redeck.spatial_state import ContentBlock, SlideState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue, IssueEvidence

        before_card = ContentBlock(
            block_id="before_card",
            var_name="div",
            shape_type="textbox",
            css_selector=".card",
            css_classes=("card", "grid-card"),
            dom_path="html/body/div.grid-card",
            text_chars=70,
            text_lines=["Long original support copy inside the named comparison card"],
            is_clipped=True,
            clipped_bottom_px=40,
            bbox_px=(40, 320, 280, 430),
        )
        after_card = ContentBlock(
            block_id="after_card",
            var_name="div",
            shape_type="textbox",
            css_selector=".card",
            css_classes=("card", "grid-card"),
            dom_path="html/body/div.grid-card",
            text_chars=42,
            text_lines=["Compressed support copy in the same card"],
            is_clipped=True,
            clipped_bottom_px=22,
            bbox_px=(40, 300, 280, 430),
        )
        baseline = SlideState(
            slide_id=1,
            blocks=[before_card],
            clipped_blocks=["before_card"],
        )
        current = SlideState(
            slide_id=1,
            blocks=[after_card],
            clipped_blocks=["after_card"],
        )
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="B09_slide1",
            rubric_id="B09",
            issue_type="density_imbalance",
            severity=Severity.MAJOR,
            affected_slides=[1],
            evidence=IssueEvidence(
                object_refs=[".grid-card"],
                description="The named comparison cards are too dense.",
            ),
        )]

        residuals = repair._targeted_significant_issues(baseline, current)

        assert residuals["clipped"] == ["after_card"]

    def test_overflow_residuals_are_scoped_to_named_baseline_object(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.modules.redeck.spatial_state import ContentBlock, SlideState
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue

        target = ContentBlock(
            block_id="blk_target",
            var_name="p",
            shape_type="textbox",
            css_selector=".target",
            text_chars=30,
            text_lines=["Target sentence remains clipped"],
            overflow_bottom_px=20,
            bbox_px=(20, 20, 200, 40),
        )
        unrelated = ContentBlock(
            block_id="blk_other",
            var_name="p",
            shape_type="textbox",
            css_selector=".other",
            text_chars=30,
            text_lines=["Unrelated baseline footer warning"],
            overflow_bottom_px=20,
            bbox_px=(20, 600, 200, 40),
        )
        baseline = SlideState(
            slide_id=1,
            blocks=[target, unrelated],
            overflow_blocks=["blk_target", "blk_other"],
        )
        current = SlideState(
            slide_id=1,
            blocks=[target, unrelated],
            overflow_blocks=["blk_target", "blk_other"],
        )
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="B4_slide1",
            rubric_id="B4",
            issue_type="text_overflow",
            severity=Severity.MAJOR,
            affected_slides=[1],
            fix_detail=FixDetail(
                target_location='the block containing "Target sentence remains clipped"',
            ),
        )]

        residuals = repair._targeted_significant_issues(baseline, current)

        assert residuals["text_overflow"] == ["blk_target"]

    def test_descendant_object_ref_scopes_residual_to_leaf_selector(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.modules.redeck.spatial_state import ContentBlock, SlideState
        from app.schemas.common import Severity
        from app.schemas.issue import Issue, IssueEvidence

        hero_metric = ContentBlock(
            block_id="blk_metric",
            var_name="div",
            shape_type="textbox",
            css_selector=".big",
            css_classes=["big"],
            text_chars=3,
            text_lines=["31%"],
            overflow_bottom_px=12,
            bbox_px=(960, 60, 270, 90),
        )
        body_copy = ContentBlock(
            block_id="blk_body",
            var_name="p",
            shape_type="textbox",
            css_selector="p",
            text_chars=40,
            text_lines=["Unrelated baseline body copy remains clipped"],
            overflow_bottom_px=24,
            bbox_px=(40, 680, 500, 80),
        )
        baseline = SlideState(
            slide_id=1,
            blocks=[hero_metric, body_copy],
            overflow_blocks=["blk_metric", "blk_body"],
        )
        current = SlideState(
            slide_id=1,
            blocks=[hero_metric, body_copy],
            overflow_blocks=["blk_metric", "blk_body"],
        )
        repair = AgentRepair(MagicMock())
        repair._current_issues = [Issue(
            issue_id="B4_slide1",
            rubric_id="B4",
            issue_type="text_overflow",
            severity=Severity.MAJOR,
            affected_slides=[1],
            evidence=IssueEvidence(
                object_refs=[".hero .big"],
                description="The hero metric is clipped.",
            ),
        )]

        residuals = repair._targeted_significant_issues(baseline, current)

        assert residuals["text_overflow"] == ["blk_metric"]


class TestContentReflowRouting:
    def test_missing_point_reaches_agent_repair(self):
        from app.modules.redeck.agent_repair import AgentRepair
        from app.schemas.common import Severity
        from app.schemas.issue import FixDetail, Issue

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        repair._run_single_repair = MagicMock(return_value="changed")
        issue = Issue(
            issue_id="C_missing_point_slide1",
            rubric_id="C3",
            issue_type="missing_point",
            severity=Severity.MAJOR,
            affected_slides=[1],
            fix_detail=FixDetail(correct_content="Add the missing source-backed point"),
        )
        code = "<html><body><p>Existing point</p></body></html>"

        result = repair.repair(
            slide_id=1,
            code=code,
            all_issues=[issue],
            bp_slide=None,
            evidence=MagicMock(),
            codegen_compiler=SimpleNamespace(
                _task_brief="",
                slide_codes={1: code},
            ),
            case_dir=".",
        )

        assert result == "changed"
        passed_issues = repair._run_single_repair.call_args.kwargs["all_issues"]
        assert [item.issue_type for item in passed_issues] == ["missing_point"]


class TestBatchRepairSubmission:
    """Batch edits must be judged by evidence, not tool-call count."""

    def test_one_batch_can_address_multiple_issues_without_submit_bounce(self):
        from app.modules.redeck.agent_repair import AgentRepair

        llm = MagicMock()
        llm.call_multiturn.side_effect = [
            json.dumps({
                "tool": "apply_edits",
                "edits": [
                    {"search": "red", "replace": "crimson"},
                    {"search": "blue", "replace": "navy"},
                    {"search": "green", "replace": "teal"},
                ],
            }),
            json.dumps({"tool": "verify_layout"}),
            json.dumps({"tool": "submit"}),
        ]
        repair = AgentRepair(
            llm=llm,
            repair_config={"enable_macro_planning": False},
        )
        original = "\n".join([
            'palette = "red blue green"',
            *[f"# unchanged {index}" for index in range(10)],
        ])
        issues = [
            SimpleNamespace(issue_type="visual_quality", rubric_id=f"B{index:02d}")
            for index in range(1, 4)
        ]

        def execute(action, state):
            if action["tool"] == "apply_edits":
                state.current_code = state.current_code.replace(
                    '"red blue green"', '"crimson navy teal"',
                )
                return "Applied 3 edits successfully.", True
            if action["tool"] == "verify_layout":
                state.last_verify_result = {"delta_total": 0}
                state.last_verified_code = state.current_code
                return "No regression.", False
            raise AssertionError(action)

        repair._execute_tool = execute
        repair._check_content_retention = MagicMock(return_value=True)

        result = repair._run_single_repair(
            slide_id=1,
            code=original,
            all_issues=issues,
            must_not=[],
            must_contain=[],
            initial_msg="Fix all three visual issues.",
            state_template={
                "codegen_compiler": MagicMock(),
                "case_dir": ".",
                "evidence": None,
                "bp_slide": None,
            },
        )

        assert result is not None
        assert '"crimson navy teal"' in result
        assert llm.call_multiturn.call_count == 3
        all_feedback = "\n".join(
            str(message.get("content", ""))
            for call in llm.call_multiturn.call_args_list
            for message in call.kwargs["messages"]
            if message["role"] == "user"
        )
        assert "but you only made" not in all_feedback

    def test_visual_submit_restores_text_but_keeps_style_fix(self):
        from app.modules.redeck.agent_repair import AgentRepair

        llm = MagicMock()
        llm.call_multiturn.side_effect = [
            json.dumps({
                "tool": "apply_edits",
                "edits": [{
                    "search": 'color:red">Exact claim',
                    "replace": 'color:blue">Short claim',
                }],
            }),
            json.dumps({"tool": "verify_layout"}),
            json.dumps({"tool": "submit"}),
            json.dumps({
                "tool": "apply_edits",
                "edits": [{"search": "Short claim", "replace": "Exact claim"}],
            }),
            json.dumps({"tool": "verify_layout"}),
            json.dumps({"tool": "submit"}),
        ]
        repair = AgentRepair(
            llm=llm,
            repair_config={"enable_macro_planning": False},
        )
        original = "\n".join([
            "<html>",
            "<body>",
            '<p style="color:red">Exact claim</p>',
            "<div>Unchanged support</div>",
            "</body>",
            "</html>",
        ])
        issues = [SimpleNamespace(
            issue_type="low_contrast", rubric_id="B5", sub_type="",
        )]

        def execute(action, state):
            if action["tool"] == "apply_edits":
                for edit in action["edits"]:
                    state.current_code = state.current_code.replace(
                        edit["search"], edit["replace"],
                    )
                return "Applied edits.", True
            if action["tool"] == "verify_layout":
                state.last_verify_result = {"delta_total": 0}
                state.last_verified_code = state.current_code
                return "No regression.", False
            raise AssertionError(action)

        repair._execute_tool = execute
        repair._check_content_retention = MagicMock(return_value=True)

        result = repair._run_single_repair(
            slide_id=1,
            code=original,
            all_issues=issues,
            must_not=[],
            must_contain=[],
            initial_msg="Fix contrast without changing text.",
            state_template={
                "codegen_compiler": MagicMock(),
                "case_dir": ".",
                "evidence": None,
                "bp_slide": None,
            },
        )

        assert result == original.replace("color:red", "color:blue")
        assert llm.call_multiturn.call_count == 6
        all_feedback = "\n".join(
            str(message.get("content", ""))
            for call in llm.call_multiturn.call_args_list
            for message in call.kwargs["messages"]
            if message["role"] == "user"
        )
        assert "visual-only repair" in all_feedback

    def test_timeout_verifies_final_edit_before_checkpoint_fallback(self):
        from app.modules.redeck.agent_repair import AgentRepair

        llm = MagicMock()
        llm.call_multiturn.return_value = json.dumps({
            "tool": "apply_edits",
            "edits": [{"search": "color:red", "replace": "color:blue"}],
        })
        repair = AgentRepair(
            llm=llm,
            repair_config={"enable_macro_planning": False},
        )
        repair.MAX_TOOL_CALLS_CAP = 1
        original = "\n".join([
            "<html>",
            "<head><style>body{width:1280px;height:720px}</style></head>",
            "<body>",
            '<p style="color:red">Exact claim</p>',
            "<p>Supporting context remains unchanged.</p>",
            "<p>Source-backed detail remains unchanged.</p>",
            "</body>",
            "</html>",
        ])
        issue = SimpleNamespace(
            issue_type="low_contrast", rubric_id="B5", sub_type="",
        )

        def execute(action, state):
            assert action["tool"] == "apply_edits"
            state.current_code = state.current_code.replace("color:red", "color:blue")
            repair._invalidate_verify_after_code_change(state, "test edit")
            return "Applied edit.", True

        def verify(state):
            state.last_verify_result = {"delta_total": 0}
            state.last_verify_revision = state.layout_revision
            state.last_verified_code = state.current_code
            return "No regression.", False

        repair._execute_tool = execute
        repair._tool_verify_layout = MagicMock(side_effect=verify)
        repair._check_content_retention = MagicMock(return_value=True)

        result = repair._run_single_repair(
            slide_id=1,
            code=original,
            all_issues=[issue],
            must_not=[],
            must_contain=[],
            initial_msg="Fix contrast.",
            state_template={
                "codegen_compiler": MagicMock(),
                "case_dir": ".",
                "evidence": None,
                "bp_slide": None,
            },
        )

        assert result == original.replace("color:red", "color:blue")
        repair._tool_verify_layout.assert_called_once()

    def test_timeout_keeps_latest_hard_valid_state_over_detector_minimum(self):
        from app.modules.redeck.agent_repair import AgentRepair

        llm = MagicMock()
        llm.call_multiturn.return_value = json.dumps({
            "tool": "apply_edits",
            "edits": [{"search": "color:red", "replace": "color:blue"}],
        })
        repair = AgentRepair(
            llm=llm,
            repair_config={"enable_macro_planning": False},
        )
        repair.MAX_TOOL_CALLS_CAP = 1
        original = "\n".join([
            "<html>",
            "<head><style>body{width:1280px;height:720px}</style></head>",
            "<body>",
            '<p style="color:red">Exact claim</p>',
            "<p>Supporting context remains unchanged.</p>",
            "<p>Source-backed detail remains unchanged.</p>",
            "<p>Another support line remains unchanged.</p>",
            "<p>Additional evidence remains unchanged.</p>",
            "</body>",
            "</html>",
        ])
        changed = original.replace("color:red", "color:blue")
        issue = SimpleNamespace(
            issue_type="low_contrast", rubric_id="B5", sub_type="",
        )

        def execute(action, state):
            assert action["tool"] == "apply_edits"
            state.current_code = changed
            repair._invalidate_verify_after_code_change(state, "test edit")
            return "Applied edit.", True

        def verify(state):
            state.last_verify_result = {"delta_total": 1}
            state.last_verify_revision = state.layout_revision
            state.best_verified_code = original
            state.best_verified_issues = 0
            state.latest_safe_verified_code = state.current_code
            state.latest_safe_verified_revision = state.layout_revision
            return "One detector advisory remains.", False

        repair._execute_tool = execute
        repair._tool_verify_layout = MagicMock(side_effect=verify)
        repair._check_content_retention = MagicMock(return_value=True)

        result = repair._run_single_repair(
            slide_id=1,
            code=original,
            all_issues=[issue],
            must_not=[],
            must_contain=[],
            initial_msg="Fix contrast.",
            state_template={
                "codegen_compiler": MagicMock(),
                "case_dir": ".",
                "evidence": None,
                "bp_slide": None,
            },
        )

        assert result == changed
        repair._tool_verify_layout.assert_called_once()


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

    def test_svg_repairs_require_visual_feedback_and_graph_invariants(self):
        assert "### render_preview" in self.prompt
        assert "do not claim visual success from DOM measurements alone" in self.prompt

    def test_prompt_bans_hidden_text_and_separates_repair_families(self):
        assert "hidden or off-canvas text" in self.prompt
        assert "Keeping an old sentence hidden" in self.prompt
        assert "Separate repair families strictly" in self.prompt
        assert "preserve the media slot semantics" in self.prompt
        assert "compose_image_grid" in self.prompt
        assert "create_svg_asset" in self.prompt
        assert "do not add new DOM-visible slide text" in self.prompt
        assert "source-grounded SVG summary asset" in self.prompt
        assert "presentation-scale labels" in self.prompt
        assert "do not steal space from adjacent text" in self.prompt
        assert "choose a different repair family" in self.prompt

    def test_b17_probe_preserves_quantitative_chart_fidelity(self):
        repo = Path(__file__).resolve().parents[1]
        probe = (repo / "app/prompts/probes/B17_raw_figure.md").read_text()

        assert "high-fidelity evidence" in probe
        assert "approximate hand-drawn summary" in probe
        assert "exact source data" in probe
        assert "Without that evidence, do not recommend a redraw" in probe

    def test_prompt_has_content_fit_and_source_attribution_guards(self):
        assert "prefer replacing or merging the closest same-topic" in self.prompt
        assert "Do not use a source attribution as movable spare content" in self.prompt
        assert "Fixed-format text regions have hard space budgets" in self.prompt
        assert "Do not put long source" in self.prompt
        assert "semantic target, not as a mandatory verbatim" in self.prompt
        assert "separate `<li>` items or distinct captions" in self.prompt

    def test_prompt_requires_structural_layout_strategy_choice(self):
        assert "`layout_inappropriate`" in self.prompt
        assert "Choose a repair family from the issue evidence" in self.prompt

    def test_prompt_discourages_mechanical_composition_repairs(self):
        assert "container" in self.prompt
        assert "natural reading path" in self.prompt

    def test_prompt_supports_text_only_spatial_verification(self):
        assert "This tool may be disabled for a run" in self.prompt
        assert "Detector totals and baseline deltas are evidence" in self.prompt
        assert "coupled same-topology calibration is valid" in self.prompt
        assert "which support role actually owns the wrapping pressure" in self.prompt

    def test_prompt_does_not_require_source_search_for_authorized_compression(self):
        assert "existing visible sentence is sufficient semantic grounding" in self.prompt
        assert "Do not call `search_source` merely because" in self.prompt
        assert "not required for explicitly authorized meaning-preserving compression" in self.prompt

    def test_prompt_distinguishes_calibration_from_orientation_reflow(self):
        assert "Use `same topology` narrowly" in self.prompt
        assert "A vertical stack changed into side-by-side columns" in self.prompt
        assert "Repeated residual identities do not by themselves" in self.prompt
        assert "intervening edits actually changed the residual-owning region" in self.prompt

    def test_agent_prompt_handles_wide_shallow_whitespace_fix_plans(self):
        agent_repair = Path("app/modules/redeck/agent_repair.py").read_text()

        assert "RESIZE OR REFLOW THE FOCAL ELEMENT" in agent_repair
        assert "complete wide/shallow" in agent_repair
        assert "body reflow" in agent_repair
        assert "moves existing interpretation/callout content" in agent_repair

    def test_prompt_requires_svg_internal_visual_assessment(self):
        assert "SVG" in self.prompt
        assert "create_svg_asset" in self.prompt

    def test_content_patch_prompt_has_fixed_region_budget(self):
        prompt_path = Path(__file__).parent.parent / "app/prompts/codegen/content_patch.system.md"
        prompt = prompt_path.read_text()

        assert "Respect fixed-format regions" in prompt
        assert "Do NOT paste a long" in prompt
        assert "Do NOT add missing content to a title" in prompt
        assert "unsupported superlative label" in prompt


def test_dense_raw_figure_guard_blocks_media_slot_expansion():
    from app.modules.redeck.agent_repair import AgentRepair, AgentState

    dense_text = " ".join(f"word{i}" for i in range(260))
    state = AgentState(
        original_code=f"<html><body><div>{dense_text}</div></body></html>",
        current_code=f"<html><body><div>{dense_text}</div></body></html>",
        checkpoints=[],
        slide_id=1,
        codegen_compiler=object(),
        case_dir=".",
        issue_types={"raw_figure"},
    )

    blocked = AgentRepair._raw_figure_dense_slot_edit_warning(
        state,
        ".left { width: 570px; } .left { width: 700px; }",
    )
    allowed = AgentRepair._raw_figure_dense_slot_edit_warning(
        state,
        '<img src="old.svg"><img src="../generated_assets/new.svg">',
    )

    assert blocked is not None
    assert "EDIT BLOCKED" in blocked
    assert allowed is None


class TestSvgAssetTool:
    def test_create_svg_asset_writes_sanitized_asset(self, tmp_path):
        from app.modules.redeck.agent_repair import AgentRepair

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        state = SimpleNamespace(_run_dir=None, case_dir=str(tmp_path), _turn_index=0)

        result, changed = repair._tool_create_svg_asset(
            {
                "svg": "<svg viewBox='0 0 100 50'><text x='5' y='20'>Fp -> T</text></svg>",
                "output_name": "progression.svg",
            },
            state,
        )

        out = tmp_path / "repair_assets" / "progression.svg"
        assert "create_svg_asset ok" in result
        assert changed is False
        assert out.exists()
        assert "xmlns=\"http://www.w3.org/2000/svg\"" in out.read_text()

    def test_create_svg_asset_reports_turn_local_ref_when_run_dir_exists(self, tmp_path):
        from app.modules.redeck.agent_repair import AgentRepair

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        state = SimpleNamespace(_run_dir=str(tmp_path / "run"), case_dir=str(tmp_path), _turn_index=2)

        result, changed = repair._tool_create_svg_asset(
            {
                "svg": "<svg viewBox='0 0 100 50'><text x='5' y='20'>Fp -> T</text></svg>",
                "output_name": "progression.svg",
            },
            state,
        )

        assert changed is False
        assert "Use `../generated_assets/progression.svg`" in result
        assert (tmp_path / "run" / "turn_02" / "generated_assets" / "progression.svg").exists()

    def test_create_svg_asset_rejects_script(self, tmp_path):
        from app.modules.redeck.agent_repair import AgentRepair

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        state = SimpleNamespace(_run_dir=None, case_dir=str(tmp_path), _turn_index=0)

        result, changed = repair._tool_create_svg_asset(
            {"svg": "<svg><script>alert(1)</script></svg>"},
            state,
        )

        assert "failed" in result
        assert changed is False

    def test_create_svg_asset_rejects_text_overflow_inside_rect(self, tmp_path):
        from app.modules.redeck.agent_repair import AgentRepair

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        state = SimpleNamespace(_run_dir=None, case_dir=str(tmp_path), _turn_index=0)

        result, changed = repair._tool_create_svg_asset(
            {
                "svg": """
                    <svg viewBox='0 0 120 80'>
                      <g>
                        <rect x='10' y='20' width='100' height='34'/>
                        <text x='60' y='42' text-anchor='middle' font-size='15'>Parietal–occipital</text>
                      </g>
                    </svg>
                """,
                "output_name": "overflow.svg",
            },
            state,
        )

        assert "create_svg_asset failed" in result
        assert "likely overflows" in result
        assert changed is False
        assert not (tmp_path / "repair_assets" / "overflow.svg").exists()

    def test_create_svg_asset_allows_wrapped_tspan_label(self, tmp_path):
        from app.modules.redeck.agent_repair import AgentRepair

        repair = AgentRepair(MagicMock(), repair_config={"enable_macro_planning": False})
        state = SimpleNamespace(_run_dir=None, case_dir=str(tmp_path), _turn_index=0)

        result, changed = repair._tool_create_svg_asset(
            {
                "svg": """
                    <svg viewBox='0 0 120 80'>
                      <g>
                        <rect x='10' y='20' width='100' height='42'/>
                        <text text-anchor='middle' font-size='13' font-weight='700'>
                          <tspan x='60' y='38'>Parietal–</tspan>
                          <tspan x='60' y='53'>occipital</tspan>
                        </text>
                      </g>
                    </svg>
                """,
                "output_name": "wrapped.svg",
            },
            state,
        )

        assert "create_svg_asset ok" in result
        assert changed is False
        assert (tmp_path / "repair_assets" / "wrapped.svg").exists()


class TestRawFigureAssetReplacement:
    def test_detects_generated_svg_replacement_only_for_raw_figure_issue(self):
        from app.modules.redeck.repair_utils import is_raw_figure_asset_replacement

        raw_issue = SimpleNamespace(issue_type="raw_figure")
        layout_issue = SimpleNamespace(issue_type="text_overflow")
        before = '<html><body><img src="cases/c/source_pack/figures/fig4.png"></body></html>'
        after = '<html><body><img src="runs/x/turn_01/generated_assets/fig4_summary.svg"></body></html>'

        assert is_raw_figure_asset_replacement([raw_issue], before, after)
        assert not is_raw_figure_asset_replacement([layout_issue], before, after)

    def test_rejects_removed_image_as_asset_replacement(self):
        from app.modules.redeck.repair_utils import is_raw_figure_asset_replacement

        raw_issue = SimpleNamespace(issue_type="raw_figure")
        before = '<html><body><img src="a.png"><img src="b.png"></body></html>'
        after = '<html><body><img src="runs/x/generated_assets/a.svg"></body></html>'

        assert not is_raw_figure_asset_replacement([raw_issue], before, after)


if __name__ == "__main__":
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(exit_code)
