import json
from pathlib import Path

import pytest
from PIL import Image

from redeck_style.content_repair import (
    SourceCatalog, actionable_issues, apply_proposal, content_gate, rendered_edit_matches,
)
from redeck_style.evaluation import coordinator, probes
from redeck_style.evaluation.editorial import editorial_probe
from redeck_style.evaluation.snapshot import SNAPSHOT_SCHEMA, file_hash
from redeck_style.repair import semantic_signature
from scripts import content_repair, repair
from scripts.repair_session import run_repair_jobs


QUOTE = "The measured accuracy is 48% on the held-out evaluation."
HTML = '<html><head><style>p{font-size:24px;color:#111}</style></head><body><p>Accuracy: 50%</p></body></html>'
PASS = {"verdict": "pass", "valid": True, "issues": []}


def issue(slide_id=1):
    return {"issue_id": f"wrong_{slide_id}", "issue_type": "numeric_error", "rubric_id": "D02",
            "affected_slides": [slide_id], "severity": "major", "evidence": {"description": "Accuracy is 48%, not 50%"}}


def proposal(slide_id=1):
    return {"tool": "apply_edits", "edits": [{"issue_id": f"wrong_{slide_id}", "search": "Accuracy: 50%",
            "replace": "Accuracy: 48%", "source_ref": "paper_full.md", "source_quote": QUOTE}]}


@pytest.fixture
def context(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "paper_full.md").write_text(QUOTE)
    return {"source_dir": str(source), "source_hashes": {"paper_full.md": file_hash(source / "paper_full.md")},
            "blueprint": {"slides": [{"slide_id": 1}]}}


def test_source_bound_replacement_and_original_guard_remain_distinct(context):
    result = apply_proposal(HTML, proposal(), [issue()], SourceCatalog(context))
    assert "48%" in result["html"] and result["guard"].accepted
    assert not repair.validate_repair(HTML, result["html"]).accepted
    assert rendered_edit_matches({"objects": [{"text_content": "Accuracy: 50%"}]},
                                 {"objects": [{"text_content": "Accuracy: 48%"}]}, result)
    assert not rendered_edit_matches({"objects": [{"text_content": "Accuracy: 50%"}]}, {"objects": []}, result)


def test_browser_visibility_must_match_authorized_edits(tmp_path, context):
    from redeck_style.evaluation.snapshot import capture_page

    original = tmp_path / "original.html"
    candidate = tmp_path / "candidate.html"
    original.write_text(HTML)
    contract = apply_proposal(HTML, proposal(), [issue()], SourceCatalog(context))
    candidate.write_text(contract["html"])
    before = capture_page(original, tmp_path / "before.png")
    after = capture_page(candidate, tmp_path / "after.png")
    assert rendered_edit_matches(before, after, contract)
    candidate.write_text(contract["html"].replace("color:#111", "color:#111;display:none"))
    hidden = capture_page(candidate, tmp_path / "hidden.png")
    assert not rendered_edit_matches(before, hidden, contract)


def test_content_gate_does_not_confuse_skipped_or_duplicate_probes_with_coverage():
    records = [{"probe_id": probe_id, "scope_slide_ids": [1], "status": "passed", "issues": []}
               for probe_id in (*coordinator.DEFAULT_PROBES, "content.editorial_copy")]
    report = {"routes": {"content": {"probes": records, "issues": []}}}
    assert content_gate(report, 1)[0]
    records[0].update(status="skipped", reason="Full-deck probe requires every blueprint slide")
    assert content_gate(report, 1)[0]
    records[5].update(status="skipped", reason="Full-deck probe requires every blueprint slide")
    assert not content_gate(report, 1)[0]
    records[5]["status"] = "passed"
    records.append(dict(records[-1]))
    assert not content_gate(report, 1)[0]


@pytest.mark.parametrize("change", [
    {"source_ref": "../private.md"}, {"source_quote": "Judge says something unverified"},
    {"replace": "Accuracy: 99%"}, {"replace": "<script>alert(1)</script>"},
    {"replace": "<span hidden>Accuracy: 48%</span>"}, {"issue_id": "unreported"},
    {"search": "font-size:24px", "replace": "font-size:12px"},
])
def test_rejects_unbound_or_unsafe_content_edits(context, change):
    action = proposal()
    action["edits"][0].update(change)
    with pytest.raises(ValueError):
        apply_proposal(HTML, action, [issue()], SourceCatalog(context))


def test_duplicate_matches_and_source_drift_are_not_accepted(context):
    catalog = SourceCatalog(context)
    with pytest.raises(ValueError, match="unique"):
        apply_proposal(HTML.replace("</body>", "<p>Accuracy: 50%</p></body>"), proposal(), [issue()], catalog)
    (Path(context["source_dir"]) / "paper_full.md").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        catalog.search("accuracy")


def test_content_edits_cannot_target_attribute_substrings(context):
    current = '<html><body><p data-value="Accuracy: 50%">Actual result</p></body></html>'
    with pytest.raises(ValueError, match="attributes"):
        apply_proposal(current, proposal(), [issue()], SourceCatalog(context))


def test_separate_quotes_are_validated_independently(context):
    action = proposal()
    action["edits"][0]["source_quotes"] = [QUOTE, "accuracy is 48% on the held-out evaluation."]
    assert "48%" in apply_proposal(HTML, action, [issue()], SourceCatalog(context))["html"]
    action["edits"][0]["source_quotes"].append("unsupported quotation")
    with pytest.raises(ValueError, match="contiguous"):
        apply_proposal(HTML, action, [issue()], SourceCatalog(context))


def test_css_reflow_uses_existing_style_guard_and_switch(context):
    action = proposal()
    action["css_edits"] = [{"search": "font-size:24px", "replace": "font-size:12px"}]
    assert "font-size:12px" in apply_proposal(HTML, action, [issue()], SourceCatalog(context))["html"]
    action["css_edits"] = [{"search": "color:#111", "replace": "color:#222"}]
    with pytest.raises(ValueError, match="disabled"):
        apply_proposal(HTML, action, [issue()], SourceCatalog(context), allow_layout=False)
    assert "color:#222" in apply_proposal(HTML, action, [issue()], SourceCatalog(context))["html"]


def test_missing_table_row_is_source_bound_semantic_insertion(context):
    current = '<html><body><table><tr><td>Baseline</td><td>50%</td></tr></table></body></html>'
    missing = {**issue(), "issue_type": "missing_evidence"}
    action = {"tool": "apply_edits", "edits": [{"issue_id": "wrong_1", "operation": "insert_after",
              "search": "<tr><td>Baseline</td><td>50%</td></tr>", "replace": "<tr><td>Evaluation</td><td>48%</td></tr>",
              "source_ref": "paper_full.md", "source_quote": QUOTE}]}
    result = apply_proposal(current, action, [missing], SourceCatalog(context))
    assert result["html"].count("<tr>") == 2
    action["edits"][0]["replace"] = "<tr><td>48%</td></tr></body>"
    with pytest.raises(ValueError, match="balanced"):
        apply_proposal(current, action, [missing], SourceCatalog(context))


@pytest.mark.parametrize("text,replacement", [
    ("SOURCE-GROUNDED DETAILS USED HERE", "Evidence"),
    ("Source: Slide 10 typed evidence architecture.", ""),
    ("Source: supplied paper evidence architecture and excerpts for slide 3.", ""),
])
def test_editorial_cleanup_is_targeted_and_cannot_rewrite_facts(context, text, replacement):
    finding = editorial_probe([{"slide_id": 1, "objects": [{"object_id": "label", "text_content": text}]}])["issues"][0]
    current = HTML.replace("Accuracy: 50%", text)
    action = {"tool": "apply_edits", "edits": [{"issue_id": finding["issue_id"], "search": text, "replace": replacement}]}
    assert text not in apply_proposal(current, action, [finding], SourceCatalog(context))["html"]
    action["edits"][0]["replace"] = "Accuracy improved to 99%"
    with pytest.raises(ValueError):
        apply_proposal(current, action, [finding], SourceCatalog(context))


def test_legitimate_source_terminology_and_cross_slide_findings_are_deferred(context):
    text = "typed evidence architecture"
    path = Path(context["source_dir"]) / "paper_full.md"
    path.write_text("The method is called typed evidence architecture.")
    context["source_hashes"]["paper_full.md"] = file_hash(path)
    finding = editorial_probe([{"slide_id": 1, "objects": [{"text_content": text}]}])["issues"][0]
    action = {"tool": "apply_edits", "edits": [{"issue_id": finding["issue_id"], "search": text, "replace": ""}]}
    with pytest.raises(ValueError, match="legitimate"):
        apply_proposal(HTML.replace("Accuracy: 50%", text), action, [finding], SourceCatalog(context))
    assert actionable_issues([{**issue(), "affected_slides": [1, 2]}], 1) == []


def test_mixed_source_context_attribution_cannot_be_deleted(context):
    text = "Source: supplied paper evidence architecture and excerpts for slide 3; accuracy is 48%."
    finding = editorial_probe([{"slide_id": 1, "objects": [{"text_content": text}]}])["issues"][0]
    action = {"tool": "apply_edits", "edits": [{"issue_id": finding["issue_id"], "search": text, "replace": ""}]}
    with pytest.raises(ValueError, match="synthetic attribution"):
        apply_proposal(HTML.replace("Accuracy: 50%", text), action, [finding], SourceCatalog(context))


def fake_capture(source, png):
    source, png = Path(source), Path(png)
    png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), "white").save(png)
    objects = [{"text_content": text, "object_id": f"text-{index}"}
               for index, text in enumerate(semantic_signature(source.read_text())["visible_text"])]
    state = {"schema_version": SNAPSHOT_SCHEMA, "source": str(source), "png": str(png),
             "html_sha256": file_hash(source), "png_sha256": file_hash(png), "title": "Example",
             "validity": {}, "objects": objects}
    png.with_suffix(".state.json").write_text(json.dumps(state))
    return {}


def review_content(pages, output, options, baseline=None):
    findings = [issue(page["slide_id"]) for page in pages if "50%" in Path(page["source"]).read_text()]
    records = [{"probe_id": probe_id, "scope_slide_ids": [page["slide_id"] for page in pages],
                "status": "failed" if findings and probe_id == "D02" else "passed",
                "issues": findings if probe_id == "D02" else []} for probe_id in coordinator.DEFAULT_PROBES]
    records.append(editorial_probe(pages))
    return {"probes": records, "issues": findings, "coverage_complete": True, "status": "failed" if findings else "passed"}


def setup_session(tmp_path, context, monkeypatch, page_count=1):
    sources = tmp_path / "input"
    sources.mkdir()
    output = tmp_path / "output"
    jobs = []
    for slide_id in range(1, page_count + 1):
        source = sources / f"slide_{slide_id:02d}.html"
        source.write_text(HTML)
        jobs.append({"source": str(source), "output": str(output / str(slide_id))})
    monkeypatch.setattr(repair, "render_and_measure", fake_capture)
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: PASS)
    monkeypatch.setattr(coordinator, "review_pages", review_content)
    monkeypatch.setattr("scripts.repair_session.source_context", lambda *args: context)

    def propose(client, model, current, png, validity, issues, catalog, feedback, prefix, layout):
        return {**apply_proposal(current, proposal(issues[0]["affected_slides"][0]), issues, catalog, layout), "calls": []}

    monkeypatch.setattr(content_repair, "propose", propose)
    return jobs, output, {"source_run": str(sources)}


def add_spatial_defect(monkeypatch):
    def capture(source, png):
        fake_capture(source, png)
        validity = {"text_collision_count": 0 if "margin-top:40px" in Path(source).read_text() else 1}
        state_path = Path(png).with_suffix(".state.json")
        state = json.loads(state_path.read_text())
        state["validity"] = validity
        state_path.write_text(json.dumps(state))
        return validity

    monkeypatch.setattr(repair, "render_and_measure", capture)
    monkeypatch.setattr(repair, "call_repair", lambda client, model, prompt, png:
        HTML.replace("color:#111", "color:#111;margin-top:40px"))


def test_spatial_budget_and_checkpoint_survive_failed_content(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    add_spatial_defect(monkeypatch)

    def reject(*args):
        raise ValueError("unsupported content carrier")

    monkeypatch.setattr(content_repair, "propose", reject)
    row = run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: None)[0]
    assert row["changed"] and row["final_hard_issues"] == 0
    assert row["status"] == "needs_content_revision" and not row["content_edit"]["applied"]
    assert [attempt["phase"] for attempt in row["attempts"]] == ["joint", "spatial"]
    assert row["attempt_budget"] == {"total": 2, "used": 2, "remaining": 0,
                                      "actions": {"joint": 1, "spatial": 1, "content": 0}}
    assert "50%" in (output / "1/slide_code/slide_01.html").read_text()


def test_joint_content_rollback_preserves_accepted_layout(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch, page_count=2)
    add_spatial_defect(monkeypatch)
    original_propose = content_repair.propose

    def proposal_after_layout(client, model, current, *args):
        if "margin-top:40px" not in current:
            raise ValueError("reflow before this local edit")
        return original_propose(client, model, current, *args)

    monkeypatch.setattr(content_repair, "propose", proposal_after_layout)

    def joint(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        if all("48%" in Path(page["source"]).read_text() for page in pages):
            finding = {**issue(), "issue_type": "missing_context", "affected_slides": [1, 2]}
            result["probes"][0].update(status="failed", issues=[finding])
        return result

    monkeypatch.setattr(coordinator, "review_pages", joint)
    rows = run_repair_jobs(jobs, output, "fixture", 3, options, workers=2, client_factory=lambda: None)
    assert all(row["changed"] and row["content_edit"].get("rolled_back") for row in rows)
    assert all(row["final_hard_issues"] == 0 and row["selected_attempt"] == 2 for row in rows)
    for path in output.glob("*/slide_code/*.html"):
        assert "50%" in path.read_text() and "margin-top:40px" in path.read_text()


def test_identical_invalid_content_proposals_stop_early(tmp_path, context, monkeypatch):
    image = tmp_path / "slide.png"
    Image.new("RGB", (32, 18), "white").save(image)
    invalid = proposal()
    invalid["edits"][0]["search"] = "missing exact text"
    calls = []

    def respond(*args):
        calls.append(args)
        return json.dumps(invalid), 1, 1, 0

    monkeypatch.setattr(content_repair, "call_llm", respond)
    with pytest.raises(ValueError, match="Repeated invalid content proposal"):
        content_repair.propose(None, "fixture", HTML, image, {}, [issue()], SourceCatalog(context), "", tmp_path / "attempt", True)
    assert len(calls) == 2


def test_default_session_repairs_content_even_without_spatial_defects(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    final_baselines = []

    def content(pages, destination, options, baseline=None):
        if destination.parent.name == "t1":
            final_baselines.append(baseline)
        return review_content(pages, destination, options, baseline)

    monkeypatch.setattr(coordinator, "review_pages", content)
    rows = run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: None)
    row = rows[0]
    assert row["changed"] and row["content_edit"]["applied"] and row["guard"]["accepted"]
    assert row["status"] == "ready_for_human_review"
    assert row["content_review"]["remediation"]["status"] == "applied"
    assert len(final_baselines) == 1 and final_baselines[0]["issues"] == []
    assert row["selected_content_report"]
    assert "50%" in Path(jobs[0]["source"]).read_text()
    assert "48%" in (Path(jobs[0]["output"]) / "slide_code/slide_01.html").read_text()
    assert run_repair_jobs(jobs, output, "fixture", 2, options, client_factory=lambda: pytest.fail("No replay calls")) == json.loads(json.dumps(rows))
    (Path(jobs[0]["output"]) / "slide_code/slide_01.html").write_text("changed")
    with pytest.raises(ValueError, match="output changed"):
        run_repair_jobs(jobs, output, "fixture", 2, options)


def test_content_only_mode_edits_copy_without_spatial_calls(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: pytest.fail("Spatial route disabled"))
    rows = run_repair_jobs(jobs, output, "fixture", 1, {**options, "routes": ["content"]}, client_factory=lambda: None)
    assert rows[0]["content_edit"]["applied"] and rows[0]["status"] == "needs_evaluation"


def test_content_edit_switch_preserves_detection(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    monkeypatch.setattr(content_repair, "propose", lambda *args: pytest.fail("Content editing disabled"))
    rows = run_repair_jobs(jobs, output, "fixture", 1, {**options, "content_repair": "off"}, client_factory=lambda: None)
    assert not rows[0]["changed"] and rows[0]["status"] == "needs_content_revision"
    assert rows[0]["content_review"]["remediation"]["status"] == "disabled"


def test_missing_source_does_not_authorize_content_editing(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    monkeypatch.setattr("scripts.repair_session.source_context", lambda *args: (_ for _ in ()).throw(ValueError("missing source")))
    monkeypatch.setattr(content_repair, "propose", lambda *args: pytest.fail("Missing source"))
    rows = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)
    assert not rows[0]["changed"] and rows[0]["content_review"]["remediation"]["status"] == "blocked_source"


def test_candidate_probe_failure_is_not_an_empty_pass(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)

    def incomplete(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        if "candidate_" in str(destination):
            result["probes"][5]["status"] = "error"
        return result

    monkeypatch.setattr(coordinator, "review_pages", incomplete)
    rows = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)
    assert not rows[0]["changed"] and rows[0]["content_review"]["remediation"]["status"] == "deferred"


def test_joint_deck_regression_rolls_back_content_without_erasing_candidates(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch, page_count=2)

    def joint(pages, destination, options, baseline=None):
        result = review_content(pages, destination, options, baseline)
        if all("48%" in Path(page["source"]).read_text() for page in pages):
            finding = {**issue(), "issue_type": "missing_context", "affected_slides": [1, 2]}
            result["probes"][0].update(status="failed", issues=[finding])
        return result

    monkeypatch.setattr(coordinator, "review_pages", joint)
    rows = run_repair_jobs(jobs, output, "fixture", 1, options, workers=2, client_factory=lambda: None)
    assert all(not row["changed"] and row["content_edit"].get("rolled_back") for row in rows)
    assert all(row["content_review"]["remediation"]["status"] == "deferred" for row in rows)
    assert all("48%" in path.read_text() for path in output.glob("*/candidates/*attempt_01.html"))
    assert run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None) == json.loads(json.dumps(rows))


def test_render_failure_cannot_accept_content_patch(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)

    def capture(source, png):
        if "candidates" in str(source):
            raise RuntimeError("render unavailable")
        return fake_capture(source, png)

    monkeypatch.setattr(repair, "render_and_measure", capture)
    rows = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)
    assert not rows[0]["changed"] and "rendering failed" in rows[0]["attempts"][0]["reason"]


def test_source_tools_share_frozen_catalog_and_budget(tmp_path, context, monkeypatch):
    source = tmp_path / "slide.png"
    Image.new("RGB", (32, 18), "white").save(source)
    responses = iter([{"tool": "search_source", "query": "accuracy"}, proposal()])
    monkeypatch.setattr(content_repair, "call_llm", lambda *args: (json.dumps(next(responses)), 10, 10, .1))
    result = content_repair.propose(None, "fixture", HTML, source, {}, [issue()], SourceCatalog(context), "", tmp_path / "attempt", True)
    assert len(result["calls"]) == 2 and "48%" in result["html"]


def test_invalid_proposal_returns_contract_feedback_within_tool_budget(tmp_path, context, monkeypatch):
    image = tmp_path / "slide.png"
    Image.new("RGB", (32, 18), "white").save(image)
    invalid = proposal()
    invalid["edits"][0]["source_quote"] = "not in the source document"
    responses = iter([invalid, proposal()])
    requests = []

    def call(client, model, system, content):
        requests.append(content[0]["text"])
        return json.dumps(next(responses)), 10, 10, .1

    monkeypatch.setattr(content_repair, "call_llm", call)
    result = content_repair.propose(None, "fixture", HTML, image, {}, [issue()], SourceCatalog(context), "", tmp_path / "attempt", True)
    assert len(result["calls"]) == 2 and "NOT applied" in requests[-1]
