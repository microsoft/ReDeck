import copy
import json

import pytest

from redeck_style.content_repair import actionable_issues, new_content_findings
from redeck_style.evaluation.contracts import (
    ground_findings, probe_input_hash, validate_observation_refs, validate_probe_output,
)
from redeck_style.evaluation.reading import content_objects, needs_visual_evidence, reading_prompt
from redeck_style.evaluation.snapshot import capture_page
from redeck_style.repair import validate_repair


def capture(tmp_path, body):
    source = tmp_path / "slide.html"
    source.write_text('<html><body style="margin:30px;font:18px Arial">' + body + '</body></html>')
    return {**capture_page(source, tmp_path / "slide.png"), "slide_id": 1}


def finding(**changes):
    return {"probe_id": "D02", "issue_id": "old", "issue_type": "numeric_error", "affected_slides": [1],
            "severity": "major", "evidence": {"object_refs": ["reading-value"], "description": "Incorrect F1"},
            "fix_detail": {"correct_content": "0.7351", "source_ref": "Table 1"}, **changes}


def report(issues):
    return {"routes": {"content": {"issues": issues}}}


def test_reading_merges_inline_values_without_changing_spatial_objects(tmp_path):
    page = capture(tmp_path, '<p id="result">F1 <b>0.7351</b>, accuracy <strong>0.9039</strong>.</p>')
    blocks = page["reading_view"]["blocks"]
    assert [block["text_content"] for block in blocks] == ["F1 0.7351, accuracy 0.9039."]
    assert len(blocks[0]["source_object_ids"]) == 3
    assert any(item["text_content"] == "F1 , accuracy ." for item in page["objects"])
    assert content_objects(page)[0]["text_content"] == "F1 0.7351, accuracy 0.9039."


def test_reading_preserves_br_and_omits_hidden_or_active_text(tmp_path):
    page = capture(tmp_path, '<h1>Two<br>lines</h1><p>Visible <b style="display:none">secret</b> text</p>'
                   '<div style="opacity:0"><p>hidden ancestor</p></div><script>untrusted()</script><style>p{color:black}</style>')
    text = " ".join(block["text_content"] for block in page["reading_view"]["blocks"])
    assert text == "Two lines Visible text"


def test_reading_observes_clipping_without_claiming_missing_evidence(tmp_path):
    page = capture(tmp_path, '<div style="height:18px;overflow:hidden"><p id="clipped">Several lines<br>of evidence</p></div>'
                   '<p style="clip-path:inset(0 50% 0 0)">Masked evidence</p>')
    blocks = page["reading_view"]["blocks"]
    assert "ancestor_clipping" in blocks[0]["observation"]["reasons"]
    assert "clip_or_mask_requires_visual_review" in blocks[1]["observation"]["reasons"]
    assert "Several lines of evidence" == blocks[0]["text_content"]


def test_reading_captures_table_relationships_and_missing_image(tmp_path):
    page = capture(tmp_path, '<table><tr><th>Model</th><th>F1</th></tr><tr><td>A</td><td><b>0.7351</b></td></tr></table>'
                   '<img src="missing.png" width="120" height="50" alt="Not pixel evidence">')
    table = page["reading_view"]["tables"][0]
    assert [[cell["text"] for cell in row] for row in table["rows"]] == [["Model", "F1"], ["A", "0.7351"]]
    assert table["rows"][0][1]["header"]
    assert page["reading_view"]["images"][0]["observation"]["status"] == "unavailable"
    assert any(item["has_image"] for item in content_objects(page))


def test_reading_separates_block_annotations_inside_table_cells(tmp_path):
    page = capture(tmp_path, '<table><tr><td id="method">Generative Graph Learner G'
                   '<span style="display:block">best conventional result</span></td></tr></table>')
    block = page["reading_view"]["blocks"][0]
    assert block["text_content"] == "Generative Graph Learner G best conventional result"
    assert block["lines"] == ["Generative Graph Learner G", "best conventional result"]


def test_inline_word_fragments_are_not_separated(tmp_path):
    page = capture(tmp_path, '<p>Graph<b>S4mer</b> backbone</p>')
    assert page["reading_view"]["blocks"][0]["text_content"] == "GraphS4mer backbone"


def test_svg_reading_keeps_wrapped_labels_and_measured_bar_ratio(tmp_path):
    page = capture(tmp_path, '<svg width="300" height="180"><text x="10" y="20">'
                   '<tspan x="10">Industrial district</tspan><tspan x="10" dy="18">daytime runs</tspan></text>'
                   '<rect x="10" y="80" width="179.3" height="9"/><rect x="10" y="110" width="192.9" height="9"/></svg>')
    assert page["reading_view"]["blocks"][0]["text_content"] == "Industrial district daytime runs"
    marks = page["reading_view"]["charts"][0]["marks"]
    bars = [mark for mark in marks if mark["kind"] == "rect"]
    assert bars[0]["bounds"]["width"] / bars[1]["bounds"]["width"] == pytest.approx(179.3 / 192.9, abs=0.0001)
    assert "reconcile rendered mark geometry" in reading_prompt([page])


@pytest.mark.parametrize("probe_id", ["C03", "C04", "D04", "E04"])
def test_evidence_visibility_probes_need_pixels(probe_id):
    assert needs_visual_evidence(probe_id, [{"objects": []}])


def test_image_pages_enable_visual_factual_probes():
    assert needs_visual_evidence("D02", [{"objects": [{"has_image": True}]}])
    assert not needs_visual_evidence("D02", [{"objects": [{"has_image": False}]}])


def test_reading_and_visual_cache_dependencies(tmp_path):
    page = capture(tmp_path, '<p id="value">F1 <b>0.7351</b></p>')
    before = probe_input_hash("C03", [page], "context", True)
    updated = copy.deepcopy(page)
    updated["png_sha256"] = "different clipping"
    assert before != probe_input_hash("C03", [updated], "context", True)
    updated = copy.deepcopy(page)
    updated["reading_view"]["blocks"][0]["text_content"] = "F1 0.7907"
    assert probe_input_hash("D02", [page], "context") != probe_input_hash("D02", [updated], "context")


def test_unknown_object_refs_are_not_valid_observations():
    pages = [{"slide_id": 1, "objects": [{"object_id": "reading-value"}]}]
    validate_observation_refs({"issues": [finding()]}, pages)
    bad = finding(evidence={"object_refs": ["invented"], "description": "Guess"})
    with pytest.raises(ValueError, match="actual"):
        validate_observation_refs({"issues": [bad]}, pages)
    anchored, unconfirmed = ground_findings([finding(), finding(evidence={"description": "Guess"})], pages)
    assert anchored["observation_status"] == "anchored"
    assert unconfirmed["observation_status"] == "unconfirmed"
    assert actionable_issues([unconfirmed], 1) == []


def test_string_evidence_cannot_bypass_the_observation_contract():
    with pytest.raises(ValueError, match="evidence must be an object"):
        validate_observation_refs({"issues": [finding(evidence="Trust me: reading-value")]},
                                 [{"slide_id": 1, "objects": [{"object_id": "reading-value"}]}])


def test_unresolved_observation_is_explicit_and_scoped():
    raw = {"probe_id": "C03", "issues": [], "unresolved_observations": [
        {"slide_id": 1, "object_refs": ["image"], "reason": "Footnote too small to read"}]}
    assert validate_probe_output(json.dumps(raw), "C03", [1])["unresolved_observations"]
    raw["unresolved_observations"][0]["slide_id"] = 2
    with pytest.raises(ValueError, match="in-scope"):
        validate_probe_output(json.dumps(raw), "C03", [1])


def test_unconfirmed_observation_does_not_become_a_repair_obligation():
    from redeck_style.evaluation.contracts import summarize_records
    from redeck_style.evaluation.coordinator import combine_status
    from redeck_style.evaluation.editorial import content_remediation
    from redeck_style.evaluation.probes import normalize_record

    issue = finding(observation_status="unconfirmed")
    record = normalize_record({"probe_id": "D02", "status": "incomplete", "issues": [issue]}, "content")
    assert record["issues"][0]["remediation"] == "content_observation"
    summary = summarize_records([record], False)
    assert summary["status"] == "incomplete"
    assert combine_status("ready_for_human_review", summary) == "needs_evaluation"
    assert content_remediation([issue], False)["status"] == "observation_required"


def test_invalid_probe_json_gets_one_bounded_logged_retry(tmp_path, monkeypatch):
    from scripts import codegen, content_probe_worker

    replies = iter(['{"probe_id":"D02","issues":', '{"probe_id":"D02","issues":[]}'])
    monkeypatch.setattr(codegen, "get_client", lambda api: None)
    monkeypatch.setattr(codegen, "call_llm", lambda *args: (next(replies), 3, 5, 0.1))
    client = content_probe_worker.LoggedProbeClient("local", tmp_path, "fixture-model")
    client.probe_id, client.slide_ids = "D02", [1]
    assert json.loads(client.call_text("rubric", "claims"))["issues"] == []
    assert [call["status"] for call in client.calls] == ["error", "completed"]
    assert len(list(tmp_path.glob("*.response.txt"))) == 2


def test_same_category_different_fact_is_a_new_finding():
    before = finding()
    after = finding(fix_detail={"correct_content": "0.7907", "source_ref": "Table 1"})
    assert new_content_findings(report([before]), report([after]), 1)
    after = finding(evidence={"object_refs": ["other-value"], "description": "Incorrect F1"})
    assert new_content_findings(report([before]), report([after]), 1)


def test_anchored_finding_identity_ignores_model_id_and_paraphrase():
    after = finding(issue_id="new", evidence={"object_refs": ["reading-value"], "description": "Different explanation"})
    assert not new_content_findings(report([finding()]), report([after]), 1)
    assert new_content_findings(report([finding()]), report([finding(), after]), 1)


SVG = '<svg><text x="20" y="30">Industrial district daytime runs</text><text x="20" y="90">F1 0.7351</text></svg>'
WRAPPED = '<text x="20" y="30"><tspan x="20">Industrial district</tspan><tspan x="20" dy="18">daytime runs</tspan></text>'


def test_svg_layout_spans_preserve_semantics():
    changed = SVG.replace('<text x="20" y="30">Industrial district daytime runs</text>', WRAPPED)
    assert validate_repair(SVG, changed).accepted
    assert validate_repair(changed, SVG).accepted


@pytest.mark.parametrize("line_break", ["<br>", "<br/>", "<br><br>"])
def test_html_layout_breaks_preserve_words_and_table_structure(line_break):
    original = '<table><tr><th>Disengagements / 1k mi</th><th>Gate</th></tr></table>'
    changed = original.replace('Disengagements /', f'Disengagements{line_break}/')
    assert validate_repair(original, changed).accepted
    assert validate_repair(changed, original).accepted


@pytest.mark.parametrize("original,changed", [
    ('<p>A</p><p>B</p>', '<p>A<br>B</p><p></p>'),
    ('<p>A</p><p>B</p>', '<p>A<br></p><p>B C</p>'),
    ('<p>12</p>', '<p>1<br>2</p>'),
    ('<p>A B</p>', '<p>A<br style="display:none">B</p>'),
    ('<p>A B</p>', '<p>A<br class="semantic">B</p>'),
])
def test_html_breaks_cannot_move_text_across_blocks_or_hide_changes(original, changed):
    assert not validate_repair(original, changed).accepted


@pytest.mark.parametrize("change", [
    lambda source: source.replace("daytime runs", "night runs"),
    lambda source: source.replace("0.7351", "0.7907"),
    lambda source: source.replace('dy="18"', 'dy="18" style="display:none"'),
    lambda source: source.replace('dy="18"', 'dy="18" aria-label="other meaning"'),
    lambda source: source.replace('dy="18"', 'dy="18" class="semantic-role"'),
    lambda source: source.replace("daytime runs", ""),
])
def test_svg_wrap_exception_does_not_authorize_semantic_changes(change):
    changed = SVG.replace('<text x="20" y="30">Industrial district daytime runs</text>', WRAPPED)
    assert not validate_repair(SVG, change(changed)).accepted


def test_svg_label_values_cannot_be_swapped_or_split_into_different_numbers():
    original = '<svg><text>12</text><text>34</text></svg>'
    assert not validate_repair(original, '<svg><text>34</text><text>12</text></svg>').accepted
    assert not validate_repair(original, '<svg><text><tspan x="1">1</tspan><tspan x="20">2</tspan></text><text>34</text></svg>').accepted


def test_editorial_probe_catches_row_selection_language_without_deleting_facts():
    from redeck_style.evaluation.editorial import editorial_probe

    page = {"slide_id": 1, "objects": [{"object_id": "title", "text_content": "CLAIM-BEARING ROWS"},
            {"object_id": "note", "text_content": "Selection follows claim overlap and source-group boundaries; not a ranking."}]}
    result = editorial_probe([page])
    assert len(result["issues"]) == 2
    assert result["issues"][1]["evidence"]["observed_text"].endswith("not a ranking.")
