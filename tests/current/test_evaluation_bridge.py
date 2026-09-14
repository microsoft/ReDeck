import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from redeck_style.evaluation import coordinator
from redeck_style.evaluation.contracts import probe_input_hash, validate_probe_output
from redeck_style.evaluation.snapshot import capture_page, file_hash, load_snapshot
from scripts import repair


ROOT = Path(__file__).resolve().parents[2]
BUNDLED_PROBES = ROOT
PROBE_PYTHON = Path(sys.executable)


def test_visual_probe_spatial_evidence_survives_without_legacy_judges():
    from app.modules.evaluators.probe_runner import ProbeRunner, _format_spatial_signal
    from app.schemas.experiment_config import ExperimentConfig
    from app.schemas.issue_types import PROBE_REGISTRY

    block = SimpleNamespace(
        block_id="caption", overflow_bottom_px=24, overflow_right_px=8,
        scroll_h_px=124, client_h_px=100, contrast_ratio=2.345,
        fg_color="#999999", bg_color="#ffffff",
    )
    regions = [{"object_id": "chart"}, {"object_id": "legend"}]
    state = SimpleNamespace(
        blocks=[block], overlap_pairs=[("caption", "chart", 0.12345)],
        overflow_blocks=["caption", "missing"], oob_blocks=["chart"],
        low_contrast_blocks=["caption", "missing"], clipped_blocks=["caption"],
        svg_regions=regions,
    )
    expected = {
        "overlap_pairs": [{"a": "caption", "b": "chart", "overlap_fraction_of_smaller": 0.123}],
        "overflow_blocks": [
            {"block_id": "caption", "overflow_bottom_px": 24, "overflow_right_px": 8,
             "scroll_h_px": 124, "client_h_px": 100},
            {"block_id": "missing"},
        ],
        "oob_blocks": ["chart"],
        "low_contrast": [{"block_id": "caption", "contrast_ratio": 2.3, "fg": "#999999", "bg": "#ffffff"}],
        "clipped_blocks": ["caption"],
        "svg_regions": regions,
    }
    assert _format_spatial_signal(state) == expected
    runner = ProbeRunner(llm=None, config=ExperimentConfig(run_id="visual-probe-test"))
    for probe_id in ("B03", "B04", "B05", "B20"):
        payload = json.loads(runner._build_visual_content(
            PROBE_REGISTRY[probe_id], [8, 10], [], {8: state, 12: state},
        ))
        assert payload["spatial_signals"] == {"8": expected}
        if probe_id == "B20":
            assert payload["inspection_image_order"] == [{
                "slide_id": 8,
                "images": [
                    "full_slide", "svg_region_1_enlarged",
                    "svg_region_1_detail_tiles_top_left_top_right_bottom_left_bottom_right",
                    "svg_region_2_enlarged",
                    "svg_region_2_detail_tiles_top_left_top_right_bottom_left_bottom_right",
                ],
            }]
        else:
            assert "inspection_image_order" not in payload
    assert "app.modules.evaluators.visual_judge" not in sys.modules
    assert "app.modules.evaluators.base_judge" not in sys.modules


def test_visual_probe_accepts_empty_spatial_evidence_without_svg_regions():
    from app.modules.evaluators.probe_runner import _format_spatial_signal

    state = SimpleNamespace(
        blocks=[], overlap_pairs=[], overflow_blocks=[], oob_blocks=[],
        low_contrast_blocks=[], clipped_blocks=[],
    )
    assert _format_spatial_signal(state) == {}


def test_default_judge_arguments_enable_source_review():
    parser = argparse.ArgumentParser()
    coordinator.add_judge_arguments(parser)
    args = parser.parse_args([])
    assert args.judge_mode == "content"
    assert args.judge_model == "gpt-5.5"


@pytest.mark.parametrize("raw", ["not JSON", "{}", '{"probe_id":"D02"}',
                                   '{"probe_id":"D04","issues":[]}',
                                   '{"probe_id":"D02","issues":[{}]}'])
def test_malformed_or_missing_output_is_not_a_pass(raw):
    with pytest.raises((ValueError, TypeError)):
        validate_probe_output(raw, "D02", [8])


def test_probe_scope_and_empty_pass_are_explicit():
    assert validate_probe_output('{"probe_id":"D02","issues":[]}', "D02", [8])["issues"] == []
    raw = {"probe_id": "D02", "issues": [{"severity": "major", "affected_slides": [1], "evidence": "wrong value"}]}
    with pytest.raises(ValueError, match="scope"):
        validate_probe_output(json.dumps(raw), "D02", [8])


def test_coverage_and_acceptance_never_promote_skipped_checks():
    assert coordinator.summarize_review([], coordinator.DEFAULT_PROBES)["status"] == "incomplete"
    records = [{"probe_id": probe, "status": "passed", "issues": []} for probe in coordinator.DEFAULT_PROBES]
    complete = coordinator.summarize_review(records, coordinator.DEFAULT_PROBES)
    assert coordinator.combine_status("ready_for_human_review", complete) == "ready_for_human_review"
    records[0]["status"] = "skipped"
    incomplete = coordinator.summarize_review(records, coordinator.DEFAULT_PROBES)
    assert coordinator.combine_status("ready_for_human_review", incomplete) == "needs_evaluation"
    assert coordinator.summarize_review(records[1:2], ["C02"])["coverage_complete"] is False
    incomplete["issues"] = [{"issue_type": "numeric_error"}]
    assert coordinator.combine_status("needs_repair", incomplete) == "needs_content_revision"
    assert coordinator.combine_status("needs_source_review", incomplete) == "needs_source_review"


def page_stub():
    return {"slide_id": 8, "title": "Results", "html_sha256": "original", "png_sha256": "original",
            "objects": [{"text_content": "80%", "has_image": False, "image_path": ""}]}


def test_css_and_pixel_changes_invalidate_chart_probe_not_source_text_cache():
    original = page_stub()
    changed = {**original, "html_sha256": "changed", "png_sha256": "changed"}
    assert probe_input_hash("D04", [original], "context") != probe_input_hash("D04", [changed], "context")
    assert probe_input_hash("D02", [original], "context") == probe_input_hash("D02", [changed], "context")
    assert probe_input_hash("D02", [original], "new-source") != probe_input_hash("D02", [original], "context")
    changed = copy.deepcopy(original)
    changed["objects"][0]["text_content"] = "40%"
    assert probe_input_hash("D02", [original], "context") != probe_input_hash("D02", [changed], "context")


def test_off_records_not_run_without_reading_source_or_calling_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(coordinator.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected worker"))
    report = coordinator.review_pages([], tmp_path / "review", {"mode": "off"})
    assert report["status"] == "incomplete"
    assert all(item["status"] == "not_run" for item in report["probes"])


def test_missing_context_records_error_not_pass(tmp_path):
    report = coordinator.review_pages([{"slide_id": 8, "source": str(tmp_path / "slide_08.html")}],
                                      tmp_path / "review")
    assert report["status"] == "incomplete"
    assert all(item["status"] == "error" for item in report["probes"])


def test_source_snapshot_refuses_changed_paper(tmp_path):
    source_dir = tmp_path / "source_pack"
    source_dir.mkdir()
    paper = source_dir / "paper_full.md"
    paper.write_text("Original evidence")
    run = tmp_path / "run"
    run.mkdir()
    (run / "run_manifest.json").write_text(json.dumps({"case": "example"}))
    coordinator.save_source_context(run, source_dir, {"slides": []})
    paper.write_text("Changed evidence")
    with pytest.raises(ValueError, match="changed"):
        coordinator.source_context(run, BUNDLED_PROBES)


def test_snapshot_reuses_exact_pixels_and_full_visible_text(tmp_path, monkeypatch):
    source = tmp_path / "slide_08.html"
    source.write_text('<html><body><h1>Evidence</h1><p>' + 'Complete source claim. ' * 30 + '</p><p style="display:none">Hidden</p><section style="opacity:0"><p>Invisible ancestor</p></section></body></html>')
    png = tmp_path / "slide_08.png"
    snapshot = capture_page(source, png)
    text = " ".join(item["text_content"] for item in snapshot["objects"])
    assert text.count("Complete source claim.") == 30
    assert "Hidden" not in text
    assert "Invisible ancestor" not in text
    monkeypatch.setattr("redeck_style.evaluation.snapshot.capture_page", lambda *args: pytest.fail("duplicate render"))
    assert load_snapshot(source, png) == snapshot


def test_review_refreshes_stale_snapshot_without_overwriting_frozen_png(tmp_path, monkeypatch):
    source = tmp_path / "slide_08.html"
    source.write_text('<html>Current content</html>')
    png = tmp_path / "frozen.png"
    png.write_bytes(b'frozen screenshot')
    png.with_suffix('.state.json').write_text(json.dumps({"schema_version": "outdated"}))
    target = tmp_path / "new_review.png"
    calls = []
    monkeypatch.setattr("redeck_style.evaluation.snapshot.capture_page", lambda source, destination: calls.append(destination))
    load_snapshot(source, png, fallback_png=target)
    assert calls == [target]
    assert png.read_bytes() == b'frozen screenshot'


def test_bundled_runner_vision_scope_cache_and_error(tmp_path):
    source_dir = tmp_path / "source_pack"
    source_dir.mkdir()
    (source_dir / "paper_full.md").write_text("# Results\n\nSystem A obtained 80 percent accuracy in the reported evaluation.")
    html = tmp_path / "slide_08.html"
    html.write_text('<html><body>80%</body></html>')
    png = tmp_path / "slide_08.png"
    Image.new("RGB", (1280, 720), "white").save(png)
    page = {**page_stub(), "source": str(html), "png": str(png),
            "html_sha256": file_hash(html), "png_sha256": file_hash(png)}
    page["objects"] = [{"object_id": "value", "object_type": "text_box", **page["objects"][0]}]
    request = {"probe_root": str(BUNDLED_PROBES), "model": "fixture-model", "api": "local", "case_id": "fixture",
               "source_dir": str(source_dir), "source_hashes": coordinator.source_hashes(source_dir),
               "context_origin": "fixture", "pages": [page], "requested_probes": ["C01", "D02", "D04"],
               "blueprint": {"slides": [
                   {"slide_id": number, "role": "results", "primary_proposition": "System A scored 80%", "must_cover_subset": ["80%"]}
                   for number in [8, 10]]}}
    harness = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts import content_probe_worker as worker
class FakeClient:
    def __init__(self, *args): self.calls = []
    def call_text(self, **kwargs):
        if self.probe_id == 'D04': raise AssertionError('D04 needs pixels')
        if self.probe_id == 'C03':
            assert len(json.loads(kwargs['user_content'])['deck_context']) == 2
        self.calls.append({'status':'completed'})
        return json.dumps({'probe_id':self.probe_id,'issues':[]})
    def call_vision(self, image_urls, **kwargs):
        assert len(image_urls) == len(self.slide_ids) and all(image.startswith('data:image/') for image in image_urls)
        self.calls.append({'status':'completed'})
        return json.dumps({'probe_id':self.probe_id,'issues':[]})
worker.LoggedProbeClient = FakeClient
worker.run(json.loads(Path(sys.argv[2]).read_text()))
'''
    previous = None
    for index in range(3):
        if index == 2:
            html.write_text('<html><body style="margin-left:5px">80%</body></html>')
            page["html_sha256"] = file_hash(html)
        output = tmp_path / f"review_{index}"
        output.mkdir()
        request.update(output_dir=str(output), baseline=previous)
        path = output / "request.json"
        path.write_text(json.dumps(request))
        subprocess.run([str(PROBE_PYTHON), "-c", harness, str(ROOT), str(path)], check=True, capture_output=True, text=True)
        previous = json.loads((output / "result.json").read_text())
        records = {item["probe_id"]: item for item in previous["probes"]}
        assert records["C01"]["status"] == "skipped"
        assert records["D04"]["requires_vision"] is True
        assert previous["status"] == "incomplete"
        assert previous["model_calls"] == [2, 0, 1][index]
        assert records["D02"]["execution"] == ("executed" if index == 0 else "reused")
        assert records["D04"]["execution"] == ("reused" if index == 1 else "executed")

    request["pages"] = [page, {**copy.deepcopy(page), "slide_id": 10}]
    request["requested_probes"] = ["C01", "C03", "D02", "D04"]
    previous = None
    for index, workers in enumerate((1, 3, 3)):
        if index == 1:
            request["pages"][1]["objects"][0]["text_content"] = "90%"
        output = tmp_path / f"scoped_{index}"
        output.mkdir()
        request.update(output_dir=str(output), baseline=previous, content_workers=workers, cache_enabled=index != 2)
        path = output / "request.json"
        path.write_text(json.dumps(request))
        subprocess.run([str(PROBE_PYTHON), "-c", harness, str(ROOT), str(path)], check=True, capture_output=True, text=True)
        previous = json.loads((output / "result.json").read_text())
        records = {item["probe_id"]: item for item in previous["probes"]}
        assert previous["model_calls"] == [6, 4, 6][index]
        assert previous["status"] == "incomplete" and not previous["issues"]
        assert all(record["status"] == "passed" for record in previous["probes"])
        if index == 1:
            assert [part["execution"] for part in records["D02"]["parts"]] == ["reused", "executed"]
            assert records["C03"]["execution"] == "executed"


def test_legacy_transport_logs_invalid_model_output_as_error(tmp_path, monkeypatch):
    from scripts import codegen, content_probe_worker

    monkeypatch.setattr(codegen, "get_client", lambda api: None)
    monkeypatch.setattr(codegen, "call_llm", lambda *args: ('{"unexpected":true}', 3, 5, 0.1))
    client = content_probe_worker.LoggedProbeClient("local", tmp_path, "fixture-model")
    client.probe_id, client.slide_ids = "D02", [8]
    with pytest.raises(ValueError):
        client.call_text("rubric", "claims")
    assert client.calls[-1]["status"] == "error"
    assert len(client.calls) == 2
    assert client.calls[-1]["input_tokens"] == 3
    assert list(tmp_path.glob("*.response.txt"))
    with pytest.raises(ValueError, match="every"):
        client.call_vision("rubric", "claims", [])


def test_repair_batch_reviews_deck_once_and_routes_issues_per_slide(tmp_path, monkeypatch):
    jobs = [{"source": str(tmp_path / f"slide_{slide_id:02d}.html"), "output": str(tmp_path),
             "row": {"status": "ready_for_human_review"}} for slide_id in [1, 2]]
    calls = []
    def review(pages, output, options, baseline=None):
        calls.append((pages, baseline))
        return {"status": "failed", "coverage_complete": True, "scope_slide_ids": [1, 2],
                "issues": [{"affected_slides": [2], "issue_type": "numeric_error"}],
                "report_path": str(output / "report.json"), "probes": []}
    monkeypatch.setattr(coordinator, "review_pages", review)
    with pytest.warns(DeprecationWarning):
        coordinator.review_repair_batch(jobs, tmp_path, {"source_run": tmp_path})
    assert len(calls) == 2
    assert len(calls[0][0]) == 2
    assert calls[1][1]["status"] == "failed"
    assert jobs[0]["row"]["status"] == "ready_for_human_review"
    assert jobs[1]["row"]["status"] == "needs_content_revision"


def test_explicit_spatial_mode_supports_legacy_arbitrary_filenames(tmp_path):
    jobs = [{"source": str(tmp_path / "legacy.html"), "output": str(tmp_path),
             "row": {"status": "ready_for_human_review"}}]
    with pytest.warns(DeprecationWarning):
        summaries = coordinator.review_repair_batch(jobs, tmp_path, {"mode": "off"})
    assert summaries[0]["status"] == "not_run"
    assert jobs[0]["row"]["status"] == "needs_evaluation"
    assert jobs[0]["row"]["spatial_status"] == "ready_for_human_review"


def test_repair_preserves_spatial_result_but_routes_content_failure(monkeypatch, tmp_path):
    source = tmp_path / "slide_08.html"
    source.write_text('<html><body>50%</body></html>')
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: {"verdict": "pass", "issues": [], "valid": True})
    monkeypatch.setattr(repair, "visual_change_audit", lambda *args: {})
    calls = []
    def review(pages, output, options, baseline=None):
        calls.append(baseline)
        records = [{"probe_id": "D02", "scope_slide_ids": [8], "status": "failed",
                    "issues": [{"issue_type": "numeric_error", "affected_slides": [8]}]}]
        return {"status": "failed", "coverage_complete": False, "issues": records[0]["issues"], "probes": records}
    monkeypatch.setattr(coordinator, "review_pages", review)
    result = repair.repair_file(None, "fixture-model", source, tmp_path / "repair", 1,
                                judge_config={"source_run": tmp_path})
    assert result["spatial_status"] == "ready_for_human_review"
    assert result["status"] == "needs_content_revision"
    assert result["changed"] is False
    assert calls[0] is None and calls[1]["status"] == "failed"
