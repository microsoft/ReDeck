import argparse
import copy
import json
import threading
from pathlib import Path

import pytest
from PIL import Image

from redeck_style.evaluation import coordinator, probes
from redeck_style.evaluation.contracts import probe_input_hash
from redeck_style.evaluation.snapshot import SNAPSHOT_SCHEMA, file_hash
from scripts import repair
from scripts.repair_session import run_repair_jobs


PASS = {"verdict": "pass", "issues": [], "valid": True}
REVISE = {"verdict": "revise", "valid": True, "issues": [
    {"kind": "clearance", "selector": "h1", "description": "Label touches rule", "suggestion": "Move rule"}]}


def fake_capture(source, png, validity=None):
    source, png = Path(source), Path(png)
    png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 18), "white" if "left:0px" in source.read_text() else "gray").save(png)
    state = {"schema_version": SNAPSHOT_SCHEMA, "source": str(source), "png": str(png),
             "html_sha256": file_hash(source), "png_sha256": file_hash(png), "title": "Result",
             "validity": validity or {}, "objects": [{"text_content": "50%", "has_image": False, "image_path": ""}]}
    png.with_suffix(".state.json").write_text(json.dumps(state))
    return state["validity"]


def page_fixture(tmp_path, slide_id=1, html=None, validity=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / f"slide_{slide_id:02d}.html"
    source.write_text(html or '<html><style>h1{left:0px}</style><body><h1>50%</h1></body></html>')
    png = source.with_suffix(".png")
    fake_capture(source, png, validity)
    return {"slide_id": slide_id, "source": str(source), "png": str(png)}


def content_report(pages, output, options, baseline=None, issues=None):
    records = []
    previous = {record["probe_id"]: record for record in (baseline or {}).get("probes", [])}
    for probe_id in coordinator.DEFAULT_PROBES:
        input_hash = probe_input_hash(probe_id, pages, "fixture source context")
        old = previous.get(probe_id)
        findings = copy.deepcopy(issues or []) if probe_id == "D02" else []
        reused = old and old.get("input_sha256") == input_hash
        if reused:
            findings = copy.deepcopy(old["issues"])
        records.append({"probe_id": probe_id, "scope_slide_ids": [page["slide_id"] for page in pages],
                        "status": "failed" if findings else "passed", "execution": "reused" if reused else "executed",
                        "input_sha256": input_hash, "issues": findings})
    return {**coordinator.summarize_review(records, coordinator.DEFAULT_PROBES), "report_path": str(output / "report.json")}


def test_probe_defaults_route_switches_and_legacy_alias():
    parser = argparse.ArgumentParser()
    coordinator.add_judge_arguments(parser)
    probes.add_probe_arguments(parser)
    options = coordinator.judge_options(parser.parse_args([]))
    assert probes.probe_config(options) == {"routes": ["spatial", "content"], "execution": "parallel"}
    assert probes.probe_config({"mode": "off"})["routes"] == ["spatial"]
    options = coordinator.judge_options(parser.parse_args(["--probe-routes", "content", "--probe-execution", "serial"]))
    assert probes.probe_config(options) == {"routes": ["content"], "execution": "serial"}
    for invalid in ({"routes": []}, {"routes": ["spatial", "spatial"]}, {"routes": ["unknown"]},
                    {"execution": "unknown"}, {"mode": "off", "routes": ["content"]}):
        with pytest.raises(ValueError):
            probes.probe_config(invalid)


def test_parallel_probes_overlap_and_share_exact_snapshot(tmp_path, monkeypatch):
    page = page_fixture(tmp_path / "input", validity={"text_collision_count": 1})
    barrier = threading.Barrier(2)
    observed = {}

    def visual(snapshot):
        observed["spatial"] = (snapshot["html_sha256"], snapshot["png_sha256"], threading.get_ident())
        barrier.wait(timeout=5)
        return REVISE

    def content(pages, output, options, baseline=None):
        observed["content"] = (pages[0]["html_sha256"], pages[0]["png_sha256"], threading.get_ident())
        barrier.wait(timeout=5)
        return content_report(pages, output, options, issues=[{"affected_slides": [1], "evidence": "Source is 48%", "source_refs": ["paper:1"]}])

    monkeypatch.setattr(coordinator, "review_pages", content)
    report = probes.evaluate_pages([page], tmp_path / "review", {}, visual, "fixture")
    assert report["coverage_complete"] and report["status"] == "failed"
    assert observed["spatial"][:2] == observed["content"][:2]
    assert observed["spatial"][2] != observed["content"][2]
    assert len(report["probes"]) == len(probes.SPATIAL_PROBES) + 15
    assert {issue["remediation"] for issue in report["issues"]} == {"spatial_repair", "content_revision"}
    assert next(issue for issue in report["issues"] if issue["route"] == "content")["source_refs"] == ["paper:1"]


def test_serial_and_parallel_have_same_probe_semantics(tmp_path, monkeypatch):
    page = page_fixture(tmp_path / "input")
    order = []

    def content(*args, **kwargs):
        order.append("content")
        return content_report(*args, **kwargs)

    monkeypatch.setattr(coordinator, "review_pages", content)
    serial = probes.evaluate_pages([page], tmp_path / "serial", {"execution": "serial"},
                                   lambda snapshot: order.append("spatial") or PASS, "fixture")
    assert order == ["spatial", "content"]
    parallel = probes.evaluate_pages([page], tmp_path / "parallel", {}, lambda snapshot: PASS, "fixture")
    assert serial["probes"] == parallel["probes"]
    assert serial["status"] == parallel["status"] == "passed"


@pytest.mark.parametrize("enabled", ["spatial", "content"])
def test_disabled_route_makes_no_requests_and_is_not_a_pass(tmp_path, monkeypatch, enabled):
    page = page_fixture(tmp_path / "input")

    def content(*args, **kwargs):
        assert enabled == "content"
        return content_report(*args, **kwargs)

    def visual(snapshot):
        assert enabled == "spatial"
        return PASS

    monkeypatch.setattr(coordinator, "review_pages", content)
    report = probes.evaluate_pages([page], tmp_path / "review", {"routes": [enabled]}, visual, "fixture")
    disabled = "content" if enabled == "spatial" else "spatial"
    assert all(record["status"] == "not_run" for record in report["routes"][disabled]["probes"])
    assert report["status"] == "incomplete" and not report["coverage_complete"]
    row = {"status": "ready_for_human_review"}
    probes.apply_evaluation(row, 1, report, report)
    assert row["status"] == "needs_evaluation"


@pytest.mark.parametrize("failed_route", ["spatial", "content"])
def test_failure_keeps_other_route_results_and_never_passes(tmp_path, monkeypatch, failed_route):
    page = page_fixture(tmp_path / "input")

    def content(*args, **kwargs):
        if failed_route == "content":
            raise RuntimeError("fixture content failure")
        return content_report(*args, **kwargs)

    def visual(snapshot):
        if failed_route == "spatial":
            raise RuntimeError("fixture visual failure")
        return PASS

    monkeypatch.setattr(coordinator, "review_pages", content)
    report = probes.evaluate_pages([page], tmp_path / "review", {}, visual, "fixture")
    assert not report["coverage_complete"] and report["status"] == "incomplete"
    assert any(record["status"] == "error" for record in report["routes"][failed_route]["probes"])
    other = "content" if failed_route == "spatial" else "spatial"
    assert report["routes"][other]["status"] == "passed"


def test_cache_reuses_failures_but_rechecks_changed_chart_and_visual(tmp_path, monkeypatch):
    first = page_fixture(tmp_path / "first")
    calls = []

    def content(*args, **kwargs):
        return content_report(*args, **kwargs, issues=[{"affected_slides": [1], "issue_type": "numeric_error"}])

    monkeypatch.setattr(coordinator, "review_pages", content)
    reviewer = lambda snapshot: calls.append(snapshot["html_sha256"]) or REVISE
    initial = probes.evaluate_pages([first], tmp_path / "t0", {}, reviewer, "fixture")
    unchanged = probes.evaluate_pages([first], tmp_path / "unchanged", {}, reviewer, "fixture", initial)
    assert len(calls) == 1
    assert all(record["execution"] == "reused" for record in unchanged["probes"])
    assert unchanged["issues"] == initial["issues"]
    changed = page_fixture(tmp_path / "changed", html=Path(first["source"]).read_text().replace("left:0px", "left:4px"))
    changed["original_png"] = first["png"]
    final = probes.evaluate_pages([changed], tmp_path / "t1", {}, reviewer, "fixture", initial)
    records = {record["probe_id"]: record for record in final["probes"]}
    assert len(calls) == 2
    assert records["D04"]["execution"] == records["spatial.visual"]["execution"] == "executed"
    assert records["D02"]["execution"] == "reused" and records["D02"]["status"] == "failed"


def test_mutating_shared_html_fails_closed(tmp_path, monkeypatch):
    page = page_fixture(tmp_path / "input")
    monkeypatch.setattr(coordinator, "review_pages", content_report)

    def visual(snapshot):
        Path(snapshot["source"]).write_text("Changed during evaluation")
        return PASS

    report = probes.evaluate_pages([page], tmp_path / "review", {}, visual, "fixture")
    assert all(record["status"] == "error" for record in report["probes"])
    assert Path(report["report_path"]).is_file()


def test_final_spatial_findings_override_earlier_spatial_pass(tmp_path, monkeypatch):
    page = page_fixture(tmp_path / "input")
    monkeypatch.setattr(coordinator, "review_pages", content_report)
    report = probes.evaluate_pages([page], tmp_path / "review", {}, lambda snapshot: REVISE, "fixture")
    row = {"status": "ready_for_human_review", "spatial_status": "ready_for_human_review"}
    probes.apply_evaluation(row, 1, report, report)
    assert row["status"] == row["spatial_status"] == "needs_repair"


def test_repair_session_batches_deck_reuses_t0_and_preserves_inputs(tmp_path, monkeypatch):
    pages = [page_fixture(tmp_path / "input", slide_id) for slide_id in [1, 2]]
    original_hashes = [file_hash(page["source"]) for page in pages]
    renders, visual_calls, content_calls = [], [], []

    def capture(source, png):
        renders.append(str(png))
        return fake_capture(source, png)

    def content(pages, output, options, baseline=None):
        content_calls.append(([page["slide_id"] for page in pages], baseline))
        return content_report(pages, output, options, baseline)

    monkeypatch.setattr(repair, "render_and_measure", capture)
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: visual_calls.append(args) or PASS)
    monkeypatch.setattr(repair, "call_repair", lambda *args: pytest.fail("Unchanged slides need no repair"))
    monkeypatch.setattr(coordinator, "review_pages", content)
    jobs = [{"source": page["source"], "output": str(tmp_path / "output" / str(page["slide_id"]))} for page in pages]
    options = {"source_run": tmp_path / "input"}
    rows = run_repair_jobs(jobs, tmp_path / "output", "fixture", 1, options, workers=2, client_factory=lambda: None)
    assert len(visual_calls) == 2 and len(renders) == 4
    assert len(content_calls) == 2 and content_calls[0][0] == content_calls[1][0] == [1, 2]
    assert content_calls[1][1] is not None
    assert all(row["status"] == "ready_for_human_review" and not row["changed"] for row in rows)
    assert [file_hash(page["source"]) for page in pages] == original_hashes
    resumed = run_repair_jobs(jobs, tmp_path / "output", "fixture", 1, options, client_factory=lambda: pytest.fail("No resume calls"))
    assert resumed == json.loads(json.dumps(rows)) and len(content_calls) == 2
    with pytest.raises(ValueError, match="configuration"):
        run_repair_jobs(jobs, tmp_path / "output", "fixture", 1, {**options, "execution": "serial"})
    Path(jobs[0]["output"], "t0_png", "slide_01.png").write_bytes(b"corrupted frozen PNG")
    with pytest.raises(ValueError, match="snapshot changed"):
        run_repair_jobs(jobs, tmp_path / "output", "fixture", 1, options)


def test_content_only_session_never_calls_spatial_model_or_editor(tmp_path, monkeypatch):
    page = page_fixture(tmp_path / "input")
    monkeypatch.setattr(repair, "render_and_measure", fake_capture)
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: pytest.fail("Spatial route disabled"))
    monkeypatch.setattr(repair, "call_repair", lambda *args: pytest.fail("Spatial route disabled"))
    monkeypatch.setattr(coordinator, "review_pages", content_report)
    rows = run_repair_jobs([{"source": page["source"], "output": str(tmp_path / "output")}], tmp_path / "output",
                           "fixture", 3, {"routes": ["content"]}, client_factory=lambda: pytest.fail("No spatial client"))
    assert not rows[0]["changed"] and rows[0]["attempts"] == []
    assert rows[0]["status"] == "needs_evaluation"
    assert rows[0]["initial_visual_review"]["verdict"] == "not_run"


@pytest.mark.parametrize("final_drift", [False, True])
def test_repaired_candidate_reuses_review_only_if_final_snapshot_matches(tmp_path, monkeypatch, final_drift):
    page = page_fixture(tmp_path / "input")
    visual_calls = []

    def capture(source, png):
        count = 1 if "left:0px" in Path(source).read_text() or final_drift and png.parent.name == "t1_png" else 0
        return fake_capture(source, png, {"text_collision_count": count})

    def visual(client, model, original, current, validity):
        visual_calls.append(str(current))
        return REVISE if validity["text_collision_count"] else PASS

    monkeypatch.setattr(repair, "render_and_measure", capture)
    monkeypatch.setattr(repair, "call_visual_review", visual)
    monkeypatch.setattr(repair, "call_repair", lambda *args: Path(page["source"]).read_text().replace("left:0px", "left:4px"))
    monkeypatch.setattr(repair, "visual_change_audit", lambda *args: {"changed_pixel_ratio": .01})
    monkeypatch.setattr(coordinator, "review_pages", content_report)
    row = run_repair_jobs([{"source": page["source"], "output": str(tmp_path / "output")}], tmp_path / "output",
                          "fixture", 1, {}, client_factory=lambda: None)[0]
    assert row["changed"] and row["selected_attempt"] == 1
    assert row["guard"]["accepted"]
    records = {record["probe_id"]: record for record in row["probe_evaluation"]["probes"]}
    assert records["D04"]["execution"] == "executed"
    assert records["D02"]["execution"] == "reused"
    assert len(visual_calls) == (3 if final_drift else 2)
    assert records["spatial.visual"]["execution"] == ("executed" if final_drift else "reused")
    assert row["status"] == ("needs_repair" if final_drift else "ready_for_human_review")


def test_probe_route_controls_remediation_not_model_output():
    record = probes.normalize_record({"probe_id": "D02", "status": "failed", "scope_slide_ids": [1],
                                      "issues": [{"remediation": "spatial_repair", "evidence": "Wrong value"}]}, "content")
    assert record["issues"][0]["remediation"] == "content_revision"


def test_spatial_only_session_supports_arbitrary_names_without_id_collisions(tmp_path, monkeypatch):
    named = page_fixture(tmp_path / "input", 2)
    arbitrary = tmp_path / "input/custom.html"
    arbitrary.write_text(Path(named["source"]).read_text())
    monkeypatch.setattr(repair, "render_and_measure", fake_capture)
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: PASS)
    monkeypatch.setattr(coordinator, "review_pages", lambda *args: pytest.fail("Content disabled"))
    output = tmp_path / "output"
    rows = run_repair_jobs([{"source": filename, "output": str(output)} for filename in [named["source"], str(arbitrary)]],
                          output, "fixture", 1, {"mode": "off"}, client_factory=lambda: None)
    assert len(rows) == 2
    assert all(row["status"] == "needs_evaluation" and row["content_review"]["status"] == "not_run" for row in rows)


def test_source_asset_probe_stays_source_review_not_spatial_edit(tmp_path, monkeypatch):
    page = page_fixture(tmp_path / "input", validity={"source_asset_issue_count": 1})
    monkeypatch.setattr(coordinator, "review_pages", content_report)
    report = probes.evaluate_pages([page], tmp_path / "review", {}, lambda snapshot: PASS, "fixture")
    row = {"status": "ready_for_human_review"}
    probes.apply_evaluation(row, 1, report, report)
    assert row["status"] == row["spatial_status"] == "needs_source_review"


def test_spatial_cache_does_not_cross_model_or_api(tmp_path, monkeypatch):
    page = page_fixture(tmp_path / "input")
    monkeypatch.setattr(coordinator, "review_pages", content_report)
    calls = []
    reviewer = lambda snapshot: calls.append(snapshot) or PASS
    initial = probes.evaluate_pages([page], tmp_path / "initial", {}, reviewer, "first-model")
    probes.evaluate_pages([page], tmp_path / "changed-model", {}, reviewer, "second-model", initial)
    probes.evaluate_pages([page], tmp_path / "changed-api", {"api": "trapi"}, reviewer, "first-model", initial)
    assert len(calls) == 3


def test_session_reuses_matching_generation_content_findings(tmp_path, monkeypatch):
    page = page_fixture(tmp_path / "generation")
    snapshot = {**json.loads(Path(page["png"]).with_suffix(".state.json").read_text()), "slide_id": 1}
    content_dir = tmp_path / "generation/content_review"
    content_dir.mkdir()
    seed = content_report([snapshot], content_dir, {}, issues=[{"affected_slides": [1], "evidence": "Wrong source number"}])
    (content_dir / "report.json").write_text(json.dumps(seed))
    monkeypatch.setattr(coordinator, "review_pages", content_report)
    monkeypatch.setattr(repair, "render_and_measure", fake_capture)
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: PASS)
    row = run_repair_jobs([{"source": page["source"], "output": str(tmp_path / "output")}], tmp_path / "output", "fixture", 1,
                          {"source_run": tmp_path / "generation"}, client_factory=lambda: None)[0]
    assert row["status"] == "needs_content_revision"
    initial = json.loads(Path(row["probe_evaluation"]["initial_report"]).read_text())
    assert all(record["execution"] == "reused" for record in initial["routes"]["content"]["probes"])
