import json

import pytest

from redeck_style.domain.editorial import ART_DIRECTION, EDITORIAL_COPY_POLICY
from redeck_style.evaluation import coordinator, probes
from redeck_style.evaluation.editorial import EDITORIAL_PROBE_ID, content_remediation, editorial_probe
from redeck_style.evaluation.snapshot import capture_page
from redeck_style.library import RuntimeLibrary
from redeck_style.pipeline import ProgramPipeline
from scripts.codegen import SYSTEM_PROMPT, build_group_prompt


def page(text):
    return {"slide_id": 6, "html_sha256": "html", "png_sha256": "png",
            "objects": [{"object_id": "footer", "text_content": text}]}


@pytest.mark.parametrize("text", [
    "Source: Slide 10 typed evidence architecture.",
    "Source: supplied paper evidence architecture and excerpts for slide 3.",
    "SOURCE-GROUNDED\nDETAILS USED HERE",
    "Optional source-detail reservoir",
    "must_cover_subset",
    "Figure preserved with object-fit: contain",
    "Bounded creative brief",
])
def test_internal_copy_is_a_local_content_finding(text):
    result = editorial_probe([page(text)])
    assert result["status"] == "failed"
    assert result["model_calls"] == 0
    assert result["issues"][0]["affected_slides"] == [6]
    assert result["issues"][0]["remediation"] == "content_revision"
    assert result["issues"][0]["evidence"]["object_refs"] == ["footer"]
    assert result["issues"][0]["suggestion"]
    assert "quoted subject matter" in result["issues"][0]["review_requirement"]


def test_ordinary_evidence_and_attribution_are_not_forbidden():
    result = editorial_probe([page("Evidence: 48% on 10 computers. Source: Figure 7, Table 4. Limitations and context.")])
    assert result["status"] == "passed"
    assert result["issues"] == []


def test_probe_uses_rendered_copy_not_css_or_html_comments(tmp_path):
    source = tmp_path / "slide_01.html"
    source.write_text('<html><head><style>.figure{object-fit:contain}</style></head><body>'
                      '<!-- typed evidence architecture --><p>Source: Figure 7.</p>'
                      '<p style="display:none">SOURCE-GROUNDED DETAILS USED HERE</p></body></html>')
    snapshot = {**capture_page(source, tmp_path / "page.png"), "slide_id": 1}
    assert editorial_probe([snapshot])["status"] == "passed"


def test_failures_are_not_reused_after_copy_changes():
    old = editorial_probe([page("typed evidence architecture")])
    new = editorial_probe([page("Source: Figure 7.")])
    assert old["input_sha256"] != new["input_sha256"]
    assert old["issues"] and not new["issues"]


def test_missing_snapshot_is_not_a_pass():
    with pytest.raises(ValueError, match="rendered text snapshots"):
        editorial_probe([])


def test_policy_reaches_generation_but_keeps_source_boundary():
    library = RuntimeLibrary()
    slide = {"slide_id": 1, "role": "context", "primary_proposition": "Context matters.", "must_cover_subset": ["Evidence is limited."]}
    pipeline = ProgramPipeline(library, library.resolve_theme("teal-cool", "light"), [slide])
    assert EDITORIAL_COPY_POLICY in SYSTEM_PROMPT
    assert EDITORIAL_COPY_POLICY in pipeline.prompt_for(slide)
    assert "omit an unsupported footer" in EDITORIAL_COPY_POLICY
    assert "alter numeric facts" in EDITORIAL_COPY_POLICY


@pytest.mark.parametrize("slide_count", [1, 2, 3])
def test_generation_request_injects_editorial_policy_once(slide_count):
    library = RuntimeLibrary()
    slides = [{"slide_id": slide_id, "role": "context", "primary_proposition": f"Evidence layer {slide_id}.",
               "must_cover_subset": [f"Required fact {slide_id}."]} for slide_id in range(1, slide_count + 1)]
    pipeline = ProgramPipeline(library, library.resolve_theme("teal-cool", "light"), slides)
    prompt = build_group_prompt(pipeline, slides)
    assert (SYSTEM_PROMPT + prompt).count(EDITORIAL_COPY_POLICY) == 1
    assert (SYSTEM_PROMPT + prompt).count(ART_DIRECTION) == 1
    for slide in slides:
        assert slide["primary_proposition"] in prompt
        assert slide["must_cover_subset"][0] in prompt
        assert pipeline.prompt_for(slide).count(EDITORIAL_COPY_POLICY) == 1


def test_local_issue_blocks_acceptance_even_if_all_model_probes_pass(tmp_path, monkeypatch):
    source = tmp_path / "slide_06.html"
    source.write_text('<html><body><p>Source: typed evidence architecture.</p></body></html>')
    snapshot = {**capture_page(source, tmp_path / "slide_06.png"), "slide_id": 6}
    monkeypatch.setattr(coordinator, "source_context", lambda *args: {"source_dir": str(tmp_path), "source_hashes": {}, "blueprint": {}})

    def worker(command, **kwargs):
        request = json.loads((tmp_path / "review/request.json").read_text())
        assert EDITORIAL_PROBE_ID not in request["requested_probes"]
        records = [{"probe_id": probe_id, "scope_slide_ids": [6], "status": "passed", "issues": []}
                   for probe_id in coordinator.DEFAULT_PROBES]
        (tmp_path / "review/result.json").write_text(json.dumps({"probes": records}))

    monkeypatch.setattr(coordinator.subprocess, "run", worker)
    report = coordinator.review_pages([snapshot], tmp_path / "review", {"source_run": tmp_path})
    assert len(report["probes"]) == 16
    assert report["status"] == "failed" and report["coverage_complete"]
    assert coordinator.combine_status("ready_for_human_review", report) == "needs_content_revision"
    assert report["remediation"]["applied"] is False
    assert report["remediation"]["automatic_editor_available"] is True
    assert report["remediation"]["pending_issue_count"] == 1


def test_local_findings_survive_missing_source_context(tmp_path, monkeypatch):
    source = tmp_path / "slide_06.html"
    source.write_text('<html><body><p>SOURCE-GROUNDED DETAILS USED HERE</p></body></html>')
    snapshot = {**capture_page(source, tmp_path / "slide_06.png"), "slide_id": 6}
    def missing_source(*args):
        raise ValueError("missing source")

    monkeypatch.setattr(coordinator, "source_context", missing_source)
    monkeypatch.setattr(coordinator.subprocess, "run", lambda *args, **kwargs: pytest.fail("unexpected worker"))
    report = coordinator.review_pages([snapshot], tmp_path / "review", {"source_run": tmp_path})
    assert report["status"] == "failed"
    assert report["coverage_complete"] is False
    assert report["probes"][-1]["probe_id"] == EDITORIAL_PROBE_ID
    assert report["probes"][-1]["status"] == "failed"
    assert all(record["status"] == "error" for record in report["probes"][:-1])


def test_disabled_content_includes_explicit_local_not_run(tmp_path):
    report = coordinator.review_pages([], tmp_path / "review", {"mode": "off"})
    assert report["probes"][-1]["probe_id"] == EDITORIAL_PROBE_ID
    assert report["probes"][-1]["status"] == "not_run"
    assert report["remediation"]["status"] == "not_run"
    route = probes.route_failure("content", [{"slide_id": 6}], "not_run", "disabled")
    assert EDITORIAL_PROBE_ID in {record["probe_id"] for record in route["probes"]}
    assert route["coverage_complete"] is False


def test_no_findings_does_not_claim_automatic_content_editing():
    result = content_remediation([], True)
    assert result["status"] == "not_needed"
    assert result["pending_issue_count"] == 0
    assert result["applied"] is False
