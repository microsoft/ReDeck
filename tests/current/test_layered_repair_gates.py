import json
from pathlib import Path

import pytest

from redeck_style.content_repair import apply_proposal
from redeck_style.evaluation import coordinator, probes
from redeck_style.repair import parse_visual_review, typography_constraints, typography_policy_prompt, validate_repair, visual_review_system_prompt
from scripts import content_repair, repair
from scripts.repair_session import run_repair_jobs
from test_content_repair import HTML, PASS, context, issue, review_content, setup_session
from test_joint_repair import REVISE, install_measure, move_current


SCOPE = {"verdict": "preserved", "reason": "Sidebar and its coupled tracks reflow; hierarchy and visual identity remain."}


def test_spatial_reviewer_does_not_override_source_bound_content_edits():
    prompt = visual_review_system_prompt()
    assert "Do NOT request restoration of old" in prompt
    assert "Content truth and authorization belong to the content probes" in prompt


def test_type_contract_exposes_the_actual_selector_floor():
    original = HTML.replace("font-size:24px", "font-size:58px")
    contract = typography_constraints({"text_geometry": [{"selector": "p", "font_px": 58, "typography": {"role": "body"}}]})
    assert contract[0]["minimum_effective_px"] == 16
    assert "local font-size reduction is allowed" in typography_policy_prompt()
    assert validate_repair(original, original.replace("58px", "51.04px")).accepted
    assert validate_repair(original, original.replace("58px", "28px")).accepted
    assert typography_policy_prompt() in repair.repair_system_prompt()
    assert typography_policy_prompt() in content_repair.SYSTEM


@pytest.mark.parametrize("scope", [None, {}, {"verdict": "preserved"}, {"verdict": "preserved", "reason": ""},
                                  {"verdict": "changed", "reason": "New layout"}, {"verdict": "uncertain", "reason": "Cannot compare"}])
def test_live_visual_pass_requires_valid_continuity(scope):
    raw = json.dumps({"verdict": "pass", "issues": [], **({"scope": scope} if scope is not None else {})})
    assert not parse_visual_review(raw, {"p"}, require_scope=True)["valid"]


def test_local_defects_can_coexist_with_preserved_continuity():
    result = parse_visual_review(json.dumps({**REVISE, "scope": SCOPE}), {"p"}, require_scope=True)
    assert result["valid"] and result["verdict"] == "revise" and result["scope"] == SCOPE


@pytest.mark.parametrize("budget,applied", [(2, False), (3, True)])
def test_expanded_reflow_is_reviewed_staged_and_finished(tmp_path, context, monkeypatch, budget, applied):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)

    def diagnostic(html):
        return {"text_collision_count": 2 if "50%" in html or "margin-top:40px" in html else 0}

    def visual(client, model, original, current, validity):
        html = Path(json.loads(current.with_suffix(".state.json").read_text())["source"]).read_text()
        return {**(PASS if "margin-top:80px" in html else REVISE), "scope": SCOPE}

    def reflow(client, model, prompt, png):
        current = prompt.split("Current complete HTML:\n", 1)[1].strip()
        return (current.replace("margin-top:40px", "margin-top:80px") if "margin-top:40px" in current
                else current.replace("color:#111", "color:#111;margin-top:40px"))

    install_measure(monkeypatch, diagnostic)
    monkeypatch.setattr(repair, "call_visual_review", visual)
    monkeypatch.setattr(repair, "call_repair", reflow)
    monkeypatch.setattr(repair, "visual_change_audit", lambda *args: {"changed_pixel_ratio": .28})
    row = run_repair_jobs(jobs, output, "fixture", budget, options, client_factory=lambda: None)[0]
    middle = row["attempts"][1]
    assert middle["advanced_working_draft"] and middle["provisional"] and not middle["accepted"]
    assert middle["gates"]["safety_passed"] and middle["gates"]["scope_required"]
    assert middle["gates"]["scope_review"] == SCOPE and not middle["gates"]["publishable"]
    assert row["content_edit"]["applied"] is applied
    if applied:
        assert row["attempts"][2]["parent_attempt"] == 2
        assert row["status"] == "ready_for_human_review" and row["final_hard_issues"] == 0
    else:
        assert (output / "1/slide_code/slide_01.html").read_text() == HTML


@pytest.mark.parametrize("scope", [None, {"verdict": "changed", "reason": "Unrelated redesign"},
                                  {"verdict": "uncertain", "reason": "Cannot verify continuity"}])
def test_expanded_scope_without_approval_never_advances(tmp_path, context, monkeypatch, scope):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    calls = []

    def visual(*args):
        calls.append(1)
        return {**REVISE, **({"scope": scope} if scope else {})}

    monkeypatch.setattr(repair, "call_visual_review", visual)
    monkeypatch.setattr(repair, "visual_change_audit", lambda *args: {"changed_pixel_ratio": .3})
    row = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)[0]
    assert len(calls) >= 2
    assert not row["changed"] and not row["attempts"][0]["advanced_working_draft"]
    assert any("design-continuity" in reason for reason in row["attempts"][0]["review_reasons"])


@pytest.mark.parametrize("diagnostic", [{"source_asset_issue_count": 1}, {"low_contrast_count": 1},
                                        {"gradient_violation_count": 1},
                                        {"text_geometry": [{"selector": "p", "font_px": 24, "font_scale": {"x": .7, "y": 1}}]}])
def test_expanded_scope_cannot_bypass_safety(tmp_path, context, monkeypatch, diagnostic):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: diagnostic if "48%" in html else {
        "text_geometry": [{"selector": "p", "font_px": 24, "font_scale": {"x": 1, "y": 1}}]})
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: {**PASS, "scope": SCOPE})
    monkeypatch.setattr(repair, "visual_change_audit", lambda *args: {"changed_pixel_ratio": .3})
    row = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)[0]
    assert not row["changed"] and not row["attempts"][0]["gates"]["safety_passed"]


def test_large_spatial_only_reflow_also_requires_complete_layout(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: {"text_collision_count": int("margin-top:40px" not in html)})
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: {**PASS, "scope": SCOPE})
    monkeypatch.setattr(repair, "call_repair", move_current)
    monkeypatch.setattr(repair, "visual_change_audit", lambda *args: {"changed_pixel_ratio": .3})
    row = run_repair_jobs(jobs, output, "fixture", 1, {**options, "mode": "off"}, client_factory=lambda: None)[0]
    assert row["changed"] and row["final_hard_issues"] == 0
    assert row["attempts"][0]["gates"]["scope_required"]
    assert not row["content_edit"]["applied"]


def test_rejection_memory_survives_alternating_failure_types():
    trace = [{"attempt": 2, "guard_reasons": ("title minimum=51.04px",)},
             {"attempt": 3, "review_reasons": ["scope continuity uncertain"]},
             {"attempt": 4, "guard_reasons": ["title minimum=51.04px"]}]
    feedback = repair.rejection_memory(trace)
    assert "title minimum=51.04px" in feedback and "scope continuity uncertain" in feedback
    assert feedback.count("title minimum=51.04px") == 1
    assert '"last_attempt": 4' in feedback


@pytest.mark.parametrize("finding_persists", [False, True])
def test_terminal_review_tracks_written_version_with_mixed_budgets(tmp_path, context, monkeypatch, finding_persists):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch, page_count=2)
    propose = content_repair.propose
    evaluate = probes.evaluate_pages

    def retry_once(client, model, current, png, validity, issues, catalog, feedback, prefix, layout):
        if prefix.name == "slide_01_attempt_01":
            raise ValueError("Fixture proposal needs one retry")
        return propose(client, model, current, png, validity, issues, catalog, feedback, prefix, layout)

    def late_content(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        if destination.parent.name == "t1" or (finding_persists and destination.parent.name.startswith("t1_")):
            finding = {**issue(1), "issue_id": "late_context", "issue_type": "missing_context"}
            result["probes"][0].update(status="failed", issues=[finding])
        return result

    def late_layout(pages, destination, *args):
        result = evaluate(pages, destination, *args)
        if destination.name == "t1":
            result["routes"]["spatial"]["pages"]["2"]["review"] = REVISE
            Path(result["report_path"]).write_text(json.dumps(result))
        return result

    monkeypatch.setattr(content_repair, "propose", retry_once)
    monkeypatch.setattr(coordinator, "review_pages", late_content)
    monkeypatch.setattr(probes, "evaluate_pages", late_layout)
    monkeypatch.setattr(repair, "call_repair", move_current)
    rows = run_repair_jobs(jobs, output, "fixture", 2, options, workers=2, client_factory=lambda: None)
    assert all(row["attempt_budget"]["used"] == 2 for row in rows)
    assert rows[0]["content_edit"]["applied"] is not finding_persists
    assert rows[1]["content_edit"]["applied"]
    assert ("48%" in (output / "1/slide_code/slide_01.html").read_text()) is not finding_persists
    assert (output / "probe_session_result.json").exists()


@pytest.mark.parametrize("affected,first_retained", [([2], True), ([1, 2], False), ([], False)])
def test_final_rollback_is_scoped_to_affected_pages(tmp_path, context, monkeypatch, affected, first_retained):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch, page_count=2)

    def final_issue(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        if destination.parent.name.startswith("t1") and "48%" in Path(pages[1]["source"]).read_text():
            finding = {**issue(2), "issue_id": "late_omission", "issue_type": "missing_context", "affected_slides": affected}
            result["probes"][0].update(status="failed", issues=[finding])
        return result

    monkeypatch.setattr(coordinator, "review_pages", final_issue)
    rows = run_repair_jobs(jobs, output, "fixture", 1, options, workers=2, client_factory=lambda: None)
    assert rows[0]["content_edit"]["applied"] is first_retained
    assert not rows[1]["content_edit"]["applied"] and rows[1]["content_edit"]["rolled_back"]
    assert all(row["attempt_budget"]["used"] == 1 for row in rows)
    assert rows[1]["status"] == "needs_content_revision"
    assert ("48%" in (output / "1/slide_code/slide_01.html").read_text()) is first_retained
