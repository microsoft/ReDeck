import json
import re
import sys
from pathlib import Path

import pytest
from PIL import Image

from redeck_style.domain.constraints import MIN_BODY_PX, MIN_LABEL_PX, MIN_TEXT_CONTRAST, title_size_ceiling
from redeck_style.evaluation.editorial import content_remediation
from redeck_style.library import RuntimeLibrary
from redeck_style.pipeline import ProgramPipeline
from redeck_style.validation.source_assets import audit_source_assets, inspect_source_figure
from scripts import codegen


@pytest.mark.parametrize("role,length,expected", [
    ("context", 60, 50), ("context", 69, 44), ("context", 81, 42), ("context", 85, 42),
    ("context", 92, 42), ("context", 93, 38), ("title", 60, 52), ("title", 85, 42),
])
def test_title_ceiling_is_identical_in_planner_and_kernel(role, length, expected):
    library = RuntimeLibrary()
    slide = {"slide_id": 1, "role": role, "primary_proposition": "word " * (length // 5) + "x" * (length % 5),
             "must_cover_subset": ["Grounded evidence."]}
    pipeline = ProgramPipeline(library, library.resolve_theme("gray-mono", "light"), [slide])
    program = pipeline.programs[1]
    typography = next(item for item in program.vocab if item.kind == "typography")
    assert title_size_ceiling(role, length) == expected
    assert typography.parameters["title_size_ceiling_px"] == expected
    assert f"--kernel-title-size:{expected}px" in pipeline.prompt_for(slide)
    assert program.guardrails.min_body_px == MIN_BODY_PX
    assert program.guardrails.min_label_px == MIN_LABEL_PX


def test_system_prompt_uses_shared_limits():
    assert f"at least {MIN_BODY_PX}px" in codegen.SYSTEM_PROMPT
    assert f"at least {MIN_LABEL_PX}px" in codegen.SYSTEM_PROMPT
    assert f"at least {MIN_TEXT_CONTRAST:g}:1" in codegen.SYSTEM_PROMPT
    assert not re.search(r"\$MIN_", codegen.SYSTEM_PROMPT)


@pytest.mark.parametrize("size,issues", [((667, 28), ["suspected-extraction-fragment"]), ((667, 280), [])])
def test_preflight_uses_real_image_dimensions(tmp_path, size, issues):
    path = tmp_path / "figure.png"
    Image.new("RGB", size, "white").save(path)
    result = inspect_source_figure({"path": str(path)})
    assert result["issues"] == issues
    assert (result["intrinsic_width"], result["intrinsic_height"]) == size


def test_preflight_reports_missing_corrupt_and_mismatched_assets(tmp_path):
    assert inspect_source_figure({})["issues"] == ["unavailable-image"]
    path = tmp_path / "figure.png"
    path.write_bytes(b"not an image")
    assert inspect_source_figure({"path": str(path)})["issues"] == ["unreadable-image"]
    Image.new("RGB", (600, 300), "white").save(path)
    assert inspect_source_figure({"path": str(path), "width": 600, "height": 600})["issues"] == ["intrinsic-size-metadata-mismatch"]


def test_preflight_only_checks_selected_figures_not_native_table_screenshots(tmp_path):
    path = tmp_path / "valid.png"
    Image.new("RGB", (600, 300), "white").save(path)
    assets = {"valid": {"kind": "figure", "path": str(path)},
              "missing": {"kind": "figure", "path": ""},
              "table": {"kind": "table", "rows": [["A", "0.9"]], "path": ""}}
    selected = [{"slide_id": 1, "assigned_figure_id": "valid"}, {"slide_id": 2, "assigned_figure_id": "table"}]
    report = audit_source_assets(selected, assets)
    assert len(report) == 1
    assert report[0]["status"] == "ready"


def test_native_table_data_does_not_require_screenshot_path():
    library = RuntimeLibrary()
    slide = {"slide_id": 1, "role": "results", "primary_proposition": "System A obtains 0.9.",
             "must_cover_subset": ["System A obtains 0.9."], "assigned_figure_id": "table"}
    figures = {"table": {"kind": "table", "path": "", "caption": "Source measurements",
                         "rows": [["System A", "0.9"]], "row_count": 1, "col_count": 2}}
    prompt = ProgramPipeline(library, library.resolve_theme("gray-mono", "light"), [slide], figures).prompt_for(slide)
    assert "Display table data:" in prompt
    assert "Source measurements" in prompt


def test_source_failures_do_not_enter_layout_regeneration():
    results = [
        {"slide_id": 1, "status": "source-review-required"},
        {"slide_id": 2, "status": "layout-invalid", "layout_validity": {"source_asset_issue_count": 1}},
        {"slide_id": 3, "status": "layout-invalid"},
        {"slide_id": 4, "status": "generic-drift"},
        {"slide_id": 5, "status": "in-band"},
    ]
    assert codegen.regeneration_candidates(results, {1, 2, 3, 5}) == [results[2]]
    assert "Do not regenerate layout" in codegen.bams_repair_feedback(results[0])
    assert "Do not regenerate layout" in codegen.bams_repair_feedback(results[1])


@pytest.fixture(autouse=True)
def local_source_case(monkeypatch, tmp_path):
    source = tmp_path / "cases/db_002/source_pack"
    source.mkdir(parents=True)
    (source / "paper_full.md").write_text("Synthetic source evidence: the observed rate is 48 percent.")
    monkeypatch.setenv("REDECK_CASES_ROOT", str(tmp_path / "cases"))


def test_cli_rejects_invalid_asset_before_creating_model_client(monkeypatch, tmp_path):
    slides = [{"slide_id": 1, "role": "results", "primary_proposition": "Source evidence",
               "must_cover_subset": ["Grounded evidence."], "assigned_figure_id": "missing"}]
    monkeypatch.setattr(codegen, "load_case", lambda directory: ("", {"missing": {"kind": "figure", "path": ""}}))
    monkeypatch.setattr(codegen, "resolve_blueprint", lambda *args: (Path("example.json"), {"slides": slides}))

    def forbidden_client(*args):
        pytest.fail("invalid source asset reached model client")

    monkeypatch.setattr(codegen, "get_client", forbidden_client)
    monkeypatch.setattr(sys, "argv", ["codegen.py", "--case", "db_002", "--out", str(tmp_path)])
    with pytest.raises(SystemExit, match="No model requests were made"):
        codegen.main()
    report = json.loads((tmp_path / "source_asset_audit.json").read_text())
    assert report[0]["status"] == "needs_source_review"
    assert not list((tmp_path / "slide_code").glob("*.html"))


def test_cli_design_family_alias_and_partial_dry_run(monkeypatch, tmp_path):
    slides = [{"slide_id": index, "role": "context", "primary_proposition": "Source evidence",
               "must_cover_subset": ["Grounded evidence."]} for index in (1, 2)]
    slides[1]["assigned_figure_id"] = "missing"
    monkeypatch.setattr(codegen, "load_case", lambda directory: ("", {"missing": {"kind": "figure", "path": ""}}))
    monkeypatch.setattr(codegen, "resolve_blueprint", lambda *args: (Path("example.json"), {"slides": slides}))
    monkeypatch.setattr(sys, "argv", ["codegen.py", "--case", "db_002", "--out", str(tmp_path),
                                     "--dry-run", "--slides", "1", "--design-family", "type-serif-classic"])
    codegen.main()
    plan = json.loads((tmp_path / "deck_plan.json").read_text())
    assert plan["dialect_id"] == "type-serif-classic"
    assert len(list((tmp_path / "slide_programs").glob("*.json"))) == 2
    assert json.loads((tmp_path / "source_asset_audit.json").read_text()) == []


def test_actual_feedback_and_retry_prompts_are_preserved(monkeypatch, tmp_path):
    slides = [{"slide_id": 1, "role": "context", "primary_proposition": "Evidence overview",
               "must_cover_subset": ["Grounded evidence."]}]
    feedback = tmp_path / "feedback.json"
    feedback.write_text(json.dumps({"1": "Human requested more separation."}))
    monkeypatch.setattr(codegen, "load_case", lambda directory: ("", {}))
    monkeypatch.setattr(codegen, "resolve_blueprint", lambda *args: (Path("example.json"), {"slides": slides}))
    monkeypatch.setattr(codegen, "get_client", lambda *args: None)
    monkeypatch.setattr(codegen, "render_slides", lambda *args: None)
    reports = iter([[{"slide_id": 1, "status": "generic-drift"}], [{"slide_id": 1, "status": "in-band"}]])
    monkeypatch.setattr(codegen, "evaluate_bams_similarity", lambda *args: next(reports))
    monkeypatch.setattr(codegen, "bams_repair_feedback", lambda *args: "Automatic layout feedback.")
    requests = []

    def call(client, model, system, user):
        requests.append((system, user))
        return "<!doctype html><html><body>Grounded evidence.</body></html>", 1, 1, 0

    monkeypatch.setattr(codegen, "call_llm", call)
    monkeypatch.setattr(sys, "argv", ["codegen.py", "--case", "db_002", "--out", str(tmp_path),
                                     "--visual-feedback", str(feedback), "--bams-retries", "1", "--judge-mode", "off"])
    codegen.main()
    assert len(requests) == 2
    assert (tmp_path / "prompts/system.txt").read_text() == requests[0][0]
    for attempt, request in enumerate(requests):
        assert (tmp_path / f"prompts/slide_01_attempt_{attempt:02d}.txt").read_text() == request[1]
        assert "Human requested more separation." in request[1]
    assert "Automatic layout feedback." not in requests[0][1]
    assert "Automatic layout feedback." in requests[1][1]


def test_codegen_default_routes_content_review_into_manifest(monkeypatch, tmp_path):
    slides = [{"slide_id": 8, "role": "results", "primary_proposition": "Observed result",
               "must_cover_subset": ["The observed rate is 48 percent."]}]
    monkeypatch.setattr(codegen, "load_case", lambda directory: ("Source evidence.", {}))
    monkeypatch.setattr(codegen, "resolve_blueprint", lambda *args: (tmp_path / "blueprint.json", {"slides": slides}))
    monkeypatch.setattr(codegen, "get_client", lambda *args: None)
    monkeypatch.setattr(codegen, "call_llm", lambda *args: ('<html><body>50 percent</body></html>', 1, 1, 0))
    monkeypatch.setattr(codegen, "render_slides", lambda *args: None)
    monkeypatch.setattr(codegen, "evaluate_bams_similarity", lambda *args: [{"slide_id": 8, "status": "in-band"}])
    calls = []
    def review(run, output, options):
        calls.append(options)
        return {"status": "failed", "coverage_complete": True, "issues": [{"issue_type": "numeric_error"}],
                "probes": [{"status": "failed"}], "report_path": str(output / "report.json"),
                "remediation": content_remediation([{"issue_type": "numeric_error"}], True)}
    monkeypatch.setattr(codegen, "review_run", review)
    monkeypatch.setattr(sys, "argv", ["codegen.py", "--case", "db_002", "--out", str(tmp_path)])
    codegen.main()
    assert calls[0]["mode"] == "content"
    assert calls[0]["model"] == "gpt-5.5"
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["evaluation"]["status"] == "needs_content_revision"
    assert manifest["evaluation"]["visual_review"] == "not_run"
    assert manifest["evaluation"]["content_remediation"]["automatic_editor_available"] is True
    assert manifest["evaluation"]["content_remediation"]["applied"] is False
    assert manifest["evaluation"]["content_remediation"]["pending_issue_count"] == 1
    context = json.loads((tmp_path / "judge_context.json").read_text())
    assert context["blueprint"]["slides"][0]["slide_id"] == 8
    assert context["source_hashes"]["paper_full.md"]


def test_codegen_refuses_to_overwrite_existing_run(monkeypatch, tmp_path):
    (tmp_path / "run_manifest.json").write_text('{}')
    monkeypatch.setattr(sys, "argv", ["codegen.py", "--case", "db_002", "--out", str(tmp_path)])
    with pytest.raises(SystemExit):
        codegen.main()
