import json
from pathlib import Path

import pytest

from redeck_style.content_repair import apply_proposal
from redeck_style.evaluation import coordinator, probes
from scripts import content_repair, repair
from scripts.repair_session import run_repair_jobs, verify_report
from test_content_repair import HTML, PASS, context, fake_capture, issue, proposal, review_content, setup_session


REVISE = {"verdict": "revise", "valid": True, "issues": [
    {"kind": "clearance", "selector": "p", "description": "Needs more space", "suggestion": "Move the text"}]}


def test_existing_style_advisories_remain_visible_after_spatial_completion(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: {"gradient_violation_count": 2,
                                              "text_collision_count": int("margin-top:40px" not in html)})
    monkeypatch.setattr(repair, "call_repair", move_current)
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: PASS)
    monkeypatch.setattr(repair, "visual_change_audit", lambda *args: {"changed_pixel_ratio": .01})
    row = run_repair_jobs(jobs, output, "fixture", 1, {**options, "mode": "off"}, client_factory=lambda: None)[0]
    assert row["changed"] and row["spatial_status"] == "ready_for_human_review"
    assert row["final_hard_issues"] == 2
    assert row["final_issue_counts"]["repair_blocking"] == 0
    assert row["final_issue_counts"]["style_advisory"] == 2
    assert row["status"] == "needs_evaluation"
    assert any(issue["remediation"] == "style_review" for issue in row["probe_evaluation"]["issues"])


def install_measure(monkeypatch, diagnostic):
    def measure(source, png):
        fake_capture(source, png)
        validity = diagnostic(Path(source).read_text())
        state_path = Path(png).with_suffix(".state.json")
        state = json.loads(state_path.read_text())
        state["validity"] = validity
        state_path.write_text(json.dumps(state))
        return validity

    monkeypatch.setattr(repair, "render_and_measure", measure)


def move_current(client, model, prompt, png):
    return prompt.split("Current complete HTML:\n", 1)[1].strip().replace("color:#111", "color:#111;margin-top:40px")


def test_joint_candidate_can_fix_content_and_layout_in_one_attempt(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: {"text_collision_count": int("margin-top:40px" not in html)})

    def joint(client, model, current, png, validity, issues, catalog, feedback, prefix, layout):
        action = proposal()
        action["css_edits"] = [{"search": "color:#111", "replace": "color:#111;margin-top:40px"}]
        return {**apply_proposal(current, action, issues, catalog, layout), "calls": []}

    monkeypatch.setattr(content_repair, "propose", joint)
    row = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)[0]
    assert row["status"] == "ready_for_human_review" and row["content_edit"]["applied"]
    assert [attempt["phase"] for attempt in row["attempts"]] == ["joint"]
    assert row["attempt_budget"]["used"] == 1


@pytest.mark.parametrize("current_verdict", ["confirm", "dismiss", "error"])
def test_new_candidate_problem_requires_current_recheck_before_authorization(tmp_path, context, monkeypatch, current_verdict):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    source = Path(jobs[0]["source"])
    footer = "Source: typed evidence architecture."
    source.write_text(HTML.replace("</body>", f"<p>{footer}</p></body>"))
    tasks, rechecks = [], []

    def content(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        stage = destination.parent.name
        if stage == "t0" or ("_current_" in stage and current_verdict == "dismiss"):
            for record in result["probes"]:
                if record["probe_id"] == "D02":
                    record.update(status="passed", issues=[])
        if "_current_" in stage:
            rechecks.append(stage)
            assert footer in Path(pages[0]["source"]).read_text()
            if current_verdict == "error":
                result["probes"][0].update(status="error", issues=[])
        return result

    def propose_edits(client, model, current, png, validity, issues, catalog, feedback, prefix, layout):
        tasks.append([finding["issue_id"] for finding in issues])
        edits = []
        for finding in issues:
            if finding["issue_type"] == "numeric_error":
                edits.extend(proposal()["edits"])
            elif finding["issue_type"] == "implementation_language":
                edits.append({"issue_id": finding["issue_id"], "search": footer, "replace": ""})
        return {**apply_proposal(current, {"tool": "apply_edits", "edits": edits}, issues, catalog, layout), "calls": []}

    monkeypatch.setattr(coordinator, "review_pages", content)
    monkeypatch.setattr(content_repair, "propose", propose_edits)
    row = run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: None)[0]
    assert len(rechecks) == 1 and row["attempt_budget"]["used"] == 2
    assert "wrong_1" not in tasks[0]
    assert ("wrong_1" in tasks[1]) is (current_verdict == "confirm")
    assert row["content_edit"]["applied"] is (current_verdict == "confirm")
    assert ("48%" in (output / "1/slide_code/slide_01.html").read_text()) is (current_verdict == "confirm")
    assert "current_recheck" in row["attempts"][0]


def test_different_fact_of_same_type_also_rechecks_current(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    rechecks = []

    def content(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        stage = destination.parent.name
        if stage.endswith("candidate_01"):
            changed = {**issue(), "issue_id": "different_fact", "evidence": {"description": "A different numeric claim"}}
            for record in result["probes"]:
                if record["probe_id"] == "D02":
                    record.update(status="failed", issues=[changed])
        if "_current_" in stage:
            rechecks.append(stage)
            assert "50%" in Path(pages[0]["source"]).read_text()
        return result

    monkeypatch.setattr(coordinator, "review_pages", content)
    row = run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: None)[0]
    assert len(rechecks) == 1
    assert "current_recheck" in row["attempts"][0]
    assert "different_fact" not in row["attempts"][0]["current_recheck"]["issue_ids"]
    assert row["content_edit"]["applied"]


@pytest.mark.parametrize("affected,retained", [([2], True), ([1], False), ([1, 2], False), ([], False)])
@pytest.mark.parametrize("workers", [1, 2])
def test_candidate_findings_only_block_affected_pages(tmp_path, context, monkeypatch, affected, retained, workers):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch, page_count=2)

    def content_with_new_finding(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        if "48%" in next(Path(page["source"]).read_text() for page in pages if page["slide_id"] == 1):
            finding = {**issue(2), "issue_id": "new_context", "issue_type": "missing_context", "affected_slides": affected}
            result["probes"][0].update(status="failed", issues=[finding])
        return result

    monkeypatch.setattr(coordinator, "review_pages", content_with_new_finding)
    rows = run_repair_jobs(jobs, output, "fixture", 1, options, workers=workers, client_factory=lambda: None)
    assert rows[0]["attempts"][0]["accepted"] is retained
    assert rows[0]["content_edit"]["applied"] is retained
    assert ("48%" in (output / "1/slide_code/slide_01.html").read_text()) is retained
    assert all(row["attempt_budget"]["used"] == 1 for row in rows)
    if retained:
        assert rows[0]["spatial_status"] == "ready_for_human_review"
        assert rows[1]["content_edit"]["rolled_back"]
        assert rows[1]["status"] == "needs_content_revision"
        reports = [json.loads(path.read_text()) for path in output.glob("probe_evaluation/*/t1*/report.json")]
        assert all(any(finding["issue_id"] == "new_context" for finding in report["routes"]["content"]["issues"])
                   for report in reports)


@pytest.mark.parametrize("budget,applied", [(1, False), (2, True)])
def test_verified_content_draft_waits_for_layout_before_publication(tmp_path, context, monkeypatch, budget, applied):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: {"text_collision_count": int("48%" in html and "margin-top:40px" not in html)})
    monkeypatch.setattr(repair, "call_repair", move_current)
    row = run_repair_jobs(jobs, output, "fixture", budget, options, client_factory=lambda: None)[0]
    assert row["attempts"][0]["provisional"] and not row["attempts"][0]["accepted"]
    assert row["content_edit"]["applied"] is applied
    selected = (output / "1/slide_code/slide_01.html").read_text()
    assert ("48%" in selected) is applied
    if applied:
        assert [attempt["phase"] for attempt in row["attempts"]] == ["content", "spatial"]
        assert row["attempts"][1]["parent_attempt"] == 1
        assert row["attempts"][1]["content_candidate_report"]
    else:
        assert selected == HTML


@pytest.mark.parametrize("rejected", [False, True])
def test_candidate_cache_advances_without_changing_acceptance_baseline(tmp_path, context, monkeypatch, rejected):
    from redeck_style import content_repair as contracts

    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: {"text_collision_count": int("48%" in html and "margin-top:40px" not in html)})
    monkeypatch.setattr(repair, "call_repair", move_current)
    evaluate, compare = probes.evaluate_pages, contracts.new_content_findings
    cache_baselines, acceptance_baselines = [], []

    def capture_evaluation(pages, destination, *args):
        if "candidate" in destination.name:
            cache_baselines.append(Path(args[-1]["report_path"]).parent.name)
        return evaluate(pages, destination, *args)

    def capture_comparison(baseline, report, slide_id=None):
        acceptance_baselines.append(Path(baseline["report_path"]).parent.name)
        return compare(baseline, report, slide_id)

    if rejected:
        def fail_content(pages, destination, options, baseline=None):
            result = review_content(pages, destination, options, baseline)
            result["probes"][0].update(status="failed", issues=[issue(1)])
            return result
        monkeypatch.setattr(coordinator, "review_pages", fail_content)
    monkeypatch.setattr(probes, "evaluate_pages", capture_evaluation)
    monkeypatch.setattr(contracts, "new_content_findings", capture_comparison)
    row = run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: None)[0]
    assert cache_baselines == ["t0", "slide_01_candidate_01"]
    assert set(acceptance_baselines) == {"t0"}
    assert row["content_edit"]["applied"] is not rejected


@pytest.mark.parametrize("diagnostic", [
    {"source_asset_issue_count": 1}, {"gradient_violation_count": 1}, {"low_contrast_count": 1},
    {"text_geometry": [{"selector": "p", "font_px": 24, "font_scale": {"x": .7, "y": 1}}]},
])
def test_provisional_drafts_cannot_bypass_protected_invariants(tmp_path, context, monkeypatch, diagnostic):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: diagnostic if "48%" in html else {
        "text_geometry": [{"selector": "p", "font_px": 24, "font_scale": {"x": 1, "y": 1}}]})
    row = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)[0]
    assert not row["changed"] and not row["content_edit"]["applied"]
    assert not row["attempts"][0]["advanced_working_draft"]


def test_explicit_content_defer_does_not_starve_spatial_repair(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: {"text_collision_count": int("margin-top:40px" not in html)})
    calls = []

    def defer(*args):
        calls.append(1)
        raise content_repair.ContentRepairDeferred("unsupported carrier")

    monkeypatch.setattr(content_repair, "propose", defer)
    monkeypatch.setattr(repair, "call_repair", move_current)
    row = run_repair_jobs(jobs, output, "fixture", 6, options, client_factory=lambda: None)[0]
    assert len(calls) == 1
    assert row["changed"] and row["final_hard_issues"] == 0 and not row["content_edit"]["applied"]
    assert row["attempt_budget"]["used"] == 2 and row["attempt_budget"]["remaining"] == 4


def test_content_only_mode_cannot_stage_new_layout_defects(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: {"text_collision_count": int("48%" in html)})
    row = run_repair_jobs(jobs, output, "fixture", 1, {**options, "routes": ["content"]}, client_factory=lambda: None)[0]
    assert not row["changed"] and not row["content_edit"]["applied"]


def test_final_spatial_feedback_reenters_same_budget_and_freezes_reports(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    evaluate = probes.evaluate_pages

    def final_feedback(pages, destination, *args):
        result = evaluate(pages, destination, *args)
        if destination.name == "t1":
            result["routes"]["spatial"]["pages"]["1"]["review"] = REVISE
            Path(result["report_path"]).write_text(json.dumps(result))
        return result

    monkeypatch.setattr(probes, "evaluate_pages", final_feedback)
    monkeypatch.setattr(repair, "call_repair", move_current)
    row = run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: None)[0]
    assert row["content_edit"]["applied"] and row["spatial_status"] == "ready_for_human_review"
    assert row["attempt_budget"]["used"] == 2
    assert [attempt["phase"] for attempt in row["attempts"]] == ["content", "spatial"]
    assert row["finalization"][0]["action"] == "reenter"
    saved = json.loads((output / "probe_session_result.json").read_text())
    assert any("t1_round_01" in path for path in saved["reports"])
    for filename in saved["reports"]:
        verify_report(json.loads(Path(filename).read_text()))
    assert run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: pytest.fail("No replay calls")) == json.loads(json.dumps([row]))


def test_final_new_content_finding_becomes_source_bound_task(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)

    def late_finding(pages, destination, options, baseline=None):
        if destination.parent.name == "t0":
            result = review_content(pages, destination, options, baseline)
            result["issues"] = []
            for record in result["probes"]:
                record.update(status="passed", issues=[])
            return result
        return review_content(pages, destination, options, baseline)

    monkeypatch.setattr(coordinator, "review_pages", late_finding)
    row = run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: None)[0]
    assert row["content_edit"]["applied"] and row["content_edit"]["issue_ids"] == ["wrong_1"]
    assert row["attempt_budget"]["used"] == 1
    assert row["finalization"][0]["action"] == "reenter"


def test_final_feedback_cannot_reset_exhausted_budget(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    evaluate = probes.evaluate_pages

    def final_feedback(pages, destination, *args):
        result = evaluate(pages, destination, *args)
        if destination.name.startswith("t1"):
            result["routes"]["spatial"]["pages"]["1"]["review"] = REVISE
            Path(result["report_path"]).write_text(json.dumps(result))
        return result

    monkeypatch.setattr(probes, "evaluate_pages", final_feedback)
    monkeypatch.setattr(repair, "call_repair", lambda *args: pytest.fail("Budget exhausted"))
    row = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)[0]
    assert row["attempt_budget"]["used"] == 1 and row["content_edit"]["rolled_back"]
    assert not row["content_edit"]["applied"] and not row["changed"]


def test_rollback_review_can_spend_remaining_budget_on_layout(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch, page_count=2)
    evaluate = probes.evaluate_pages

    def joint(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        if all("48%" in Path(page["source"]).read_text() for page in pages):
            finding = {**issue(), "issue_type": "missing_context", "affected_slides": [1, 2]}
            result["probes"][0].update(status="failed", issues=[finding])
        return result

    def rollback_feedback(pages, destination, *args):
        result = evaluate(pages, destination, *args)
        if destination.name == "t1_round_01":
            result["routes"]["spatial"]["pages"]["1"]["review"] = REVISE
            Path(result["report_path"]).write_text(json.dumps(result))
        return result

    monkeypatch.setattr(coordinator, "review_pages", joint)
    monkeypatch.setattr(probes, "evaluate_pages", rollback_feedback)
    monkeypatch.setattr(repair, "call_repair", move_current)
    rows = run_repair_jobs(jobs, output, "fixture", 3, options, workers=2, client_factory=lambda: None)
    assert all(row["content_edit"]["rolled_back"] and not row["content_edit"]["applied"] for row in rows)
    assert rows[0]["changed"] and rows[0]["attempt_budget"]["used"] == 2
    assert rows[1]["attempt_budget"]["used"] == 1
    assert [attempt["phase"] for attempt in rows[0]["attempts"]] == ["content", "spatial"]
    assert rows[0]["spatial_status"] == "ready_for_human_review"
    saved = json.loads((output / "probe_session_result.json").read_text())
    for filename in saved["reports"]:
        verify_report(json.loads(Path(filename).read_text()))


def test_real_render_keeps_corrected_content_while_repairing_new_clipping(tmp_path, context, monkeypatch):
    renderer = repair.render_and_measure
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    source = Path(jobs[0]["source"])
    source.write_text(HTML.replace("color:#111", "color:#111;width:220px;height:30px;overflow:hidden"))
    monkeypatch.setattr(repair, "render_and_measure", renderer)

    def correct(client, model, current, png, validity, issues, catalog, feedback, prefix, layout):
        action = proposal()
        action["edits"][0]["replace"] = "The measured accuracy is 48% on the held-out evaluation."
        return {**apply_proposal(current, action, issues, catalog, layout), "calls": []}

    def reflow(client, model, prompt, png):
        current = prompt.split("Current complete HTML:\n", 1)[1].strip()
        assert "48%" in current and "50%" not in current
        return current.replace("width:220px;height:30px", "width:800px;height:auto")

    monkeypatch.setattr(content_repair, "propose", correct)
    monkeypatch.setattr(repair, "call_repair", reflow)
    row = run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: None)[0]
    assert row["initial_hard_issues"] == 0
    assert row["attempts"][0]["provisional"] and row["attempts"][0]["validity"]["text_clip_count"] > 0
    assert row["final_hard_issues"] == 0 and row["content_edit"]["applied"]
    assert row["status"] == "ready_for_human_review"


def test_controller_cannot_change_page_or_reset_budget(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    source, destination = Path(jobs[0]["source"]), Path(jobs[0]["output"])
    prepared = repair.prepare_repair(source, destination)
    controller = {}
    repair.repair_slide(None, "fixture", source, destination, 2, prepared=prepared,
                        initial_spatial={"review": PASS}, controller=controller)
    with pytest.raises(ValueError, match="reset the shared repair budget"):
        repair.repair_slide(None, "fixture", source, destination, 3, prepared=prepared, controller=controller)
    other = source.with_name("slide_02.html")
    other.write_text(source.read_text())
    with pytest.raises(ValueError, match="another page or output"):
        repair.repair_slide(None, "fixture", other, destination, 2, prepared=prepared, controller=controller)


def test_checkpoint_tampering_is_not_silently_overwritten(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    source, destination = Path(jobs[0]["source"]), Path(jobs[0]["output"])
    prepared = repair.prepare_repair(source, destination)
    controller = {}
    row = repair.repair_slide(None, "fixture", source, destination, 2, prepared=prepared,
                              initial_spatial={"review": PASS}, controller=controller)
    Path(row["layout_checkpoint"]["source"]).write_text("tampered")
    with pytest.raises(ValueError, match="Immutable layout checkpoint changed"):
        repair.repair_slide(None, "fixture", source, destination, 2, prepared=prepared, controller=controller)


@pytest.mark.parametrize("budget,complete,applied", [(3, True, True), (2, True, False), (2, False, False)])
def test_layout_review_new_content_finding_updates_next_action(tmp_path, context, monkeypatch, budget, complete, applied):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    install_measure(monkeypatch, lambda html: {"text_clip_count": int("48%" in html and "margin-top:40px" not in html)})
    monkeypatch.setattr(repair, "call_repair", move_current)

    def content_feedback(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        html = Path(pages[0]["source"]).read_text()
        if "Accuracy: 48%" in html and "margin-top:40px" in html:
            finding = {**issue(), "issue_id": "missing_qualifier", "issue_type": "missing_context"}
            result["probes"][0].update(status="failed" if complete else "unavailable", issues=[finding])
        return result

    def correct(client, model, current, png, validity, issues, catalog, feedback, prefix, layout):
        action = proposal()
        if "48%" in current:
            assert [finding["issue_id"] for finding in issues] == ["missing_qualifier"]
            action["edits"][0].update(issue_id="missing_qualifier", search="Accuracy: 48%",
                                      replace="The measured accuracy is 48% on the held-out evaluation.")
        return {**apply_proposal(current, action, issues, catalog, layout), "calls": []}

    monkeypatch.setattr(coordinator, "review_pages", content_feedback)
    monkeypatch.setattr(content_repair, "propose", correct)
    row = run_repair_jobs(jobs, output, "fixture", budget, options, client_factory=lambda: None)[0]
    assert row["content_edit"]["applied"] is applied
    assert row["attempts"][1]["advanced_working_draft"] is complete
    assert not row["attempts"][1]["accepted"]
    assert not row["attempts"][1]["content_verified"]
    if applied:
        assert [attempt["phase"] for attempt in row["attempts"]] == ["content", "spatial", "content"]
        assert row["attempts"][2]["parent_attempt"] == 2
        assert "missing_qualifier" in row["content_edit"]["issue_ids"]
        assert row["status"] == "ready_for_human_review"
    else:
        assert (output / "1/slide_code/slide_01.html").read_text() == HTML


@pytest.mark.parametrize("temporary,allowed", [
    ({"text_collision_count": 1}, True),
    ({"text_collision_count": 3}, False),
    ({"source_asset_issue_count": 1}, False),
    ({"low_contrast_count": 1}, False),
    ({"gradient_violation_count": 1}, False),
])
def test_unpublished_draft_can_trade_bounded_layout_defects(tmp_path, context, monkeypatch, temporary, allowed):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)

    def measure(html):
        if "50%" in html:
            return {"text_collision_count": 2}
        return temporary if "margin-top:40px" in html else {}

    def visual(client, model, original, current, validity):
        html = Path(json.loads(current.with_suffix(".state.json").read_text())["source"]).read_text()
        return REVISE if "48%" in html and "margin-top" not in html else PASS

    def reflow(client, model, prompt, png):
        current = prompt.split("Current complete HTML:\n", 1)[1].strip()
        if "margin-top:40px" in current:
            return current.replace("margin-top:40px", "margin-top:80px")
        return current.replace("color:#111", "color:#111;margin-top:40px")

    install_measure(monkeypatch, measure)
    monkeypatch.setattr(repair, "call_visual_review", visual)
    monkeypatch.setattr(repair, "call_repair", reflow)
    row = run_repair_jobs(jobs, output, "fixture", 3, options, client_factory=lambda: None)[0]
    assert row["attempts"][0]["provisional"]
    assert row["attempts"][1]["exploring_layout"] is allowed
    assert not row["attempts"][1]["accepted"]
    assert row["content_edit"]["applied"] is allowed
    if allowed:
        assert row["attempts"][2]["parent_attempt"] == 2
        assert row["final_hard_issues"] == 0
        assert row["attempt_budget"]["used"] == 3
