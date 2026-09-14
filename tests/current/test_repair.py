from redeck_style.repair import font_scale_audit, hard_issue_count, semantic_signature, validate_repair
from scripts.repair import source_change_audit
from redeck_style.repair import parse_visual_review
from scripts import repair
import json
import pytest


ORIGINAL = """<!doctype html><style>:root{--surface-canvas:#fff;--ink-canvas:#000}.title{font-size:50px}.body{font-size:16px}</style><main><h1>Same title</h1><p>Same body</p><img src="figure.png" alt="evidence"></main>"""


def test_semantic_signature_ignores_css_changes():
    changed = ORIGINAL.replace("font-size:50px", "font-size:46px")
    assert semantic_signature(ORIGINAL) == semantic_signature(changed)


def test_repair_guard_accepts_local_geometry_change():
    changed = ORIGINAL.replace(".body{", ".body{margin-top:20px;")
    assert validate_repair(ORIGINAL, changed).accepted


def test_repair_guard_rejects_visible_text_or_media_drift():
    text = validate_repair(ORIGINAL, ORIGINAL.replace("Same body", "Different body"))
    media = validate_repair(ORIGINAL, ORIGINAL.replace("figure.png", "other.png"))
    assert "visible text changed" in text.reasons
    assert "media sources or alt text changed" in media.reasons


def test_css_guard_defers_size_safety_to_rendered_contract():
    changed = ORIGINAL.replace("font-size:50px", "font-size:30px").replace("font-size:16px", "font-size:10px")
    result = validate_repair(ORIGINAL, changed)
    assert result.accepted
    assert result.audit["requires_rendered_validation"]
    assert result.audit["largest_selector_reductions"]


def test_repair_guard_audits_but_does_not_veto_local_type_reduction():
    changed = ORIGINAL.replace("font-size:50px", "font-size:43px")
    result = validate_repair(ORIGINAL, changed)
    assert result.accepted
    assert font_scale_audit(ORIGINAL, changed)["largest_selector_reductions"][0]["ratio"] == 0.86


def test_repair_guard_rejects_dom_rebuild_even_if_copy_is_preserved():
    changed = ORIGINAL.replace("<p>Same body</p>", '<div class="replacement">Same body</div>')
    result = validate_repair(ORIGINAL, changed)
    assert not result.accepted
    assert "DOM structure or semantic roles changed" in result.reasons


def test_hard_issue_count_is_explicit():
    assert hard_issue_count({"overflow_count": 2, "text_clip_count": 1, "text_collision_count": 3, "graphic_text_collision_count": 2, "low_contrast_count": 1, "gradient_violation_count": 1}) == 10
    assert hard_issue_count({"graphic_text_clearance_count": 1}) == 1
    assert hard_issue_count({"connector_rule_collision_count": 1}) == 1


def test_source_change_audit_exposes_edit_scope():
    audit = source_change_audit("a\nb\nc\n", "a\nchanged\nc\n")
    assert audit["changed_regions"] == 1
    assert audit["deleted_lines"] == 1
    assert audit["inserted_lines"] == 1


@pytest.mark.parametrize("raw", ['not json', '{"verdict":"pass","issues":[{}]}', '{"verdict":"revise","issues":[]}'])
def test_invalid_visual_review_never_passes(raw):
    assert parse_visual_review(raw, {"h1"})["verdict"] == "uncertain"


def test_visual_review_requires_real_dom_target():
    raw = json.dumps({"verdict": "revise", "issues": [{"kind": "clearance", "selector": "#invented",
                      "description": "too close", "suggestion": "move region"}]})
    assert not parse_visual_review(raw, {"h1"})["valid"]
    assert parse_visual_review(raw.replace("#invented", "h1"), {"h1"})["valid"]


def test_computed_font_guard_catches_unreadable_inherited_override():
    before = {"text_geometry": [{"selector": "h1", "font_px": 62}]}
    after = {"text_geometry": [{"selector": "h1", "font_px": 8}]}
    assert repair.computed_type_reductions(before, after)


def test_no_trade_of_collision_for_overflow():
    assert repair.issue_regressions({"text_collision_count": 3}, {"overflow_count": 1})
    assert repair.issue_regressions({}, {"source_asset_issue_count": 1})
    assert not repair.issue_regressions({"graphic_text_collision_count": 1}, {"graphic_text_clearance_count": 1})
    assert repair.issue_regressions({"graphic_text_collision_count": 1}, {"connector_rule_collision_count": 1})


@pytest.mark.parametrize("rect", [
    {"x": 1500, "y": 10, "w": 30, "h": 20},
    {"x": 0, "y": -300, "w": 30, "h": 20},
    {"x": float("nan"), "y": 10, "w": 30, "h": 20},
    {"x": 10, "y": 10, "w": 0, "h": 20},
    {},
])
def test_invalid_or_off_canvas_crops_are_skipped(rect):
    assert repair.review_crop_box(rect, 1280, 720) is None


def test_fractional_crop_is_integer_and_clamped():
    assert repair.review_crop_box({"x": 1.25, "y": 10.5, "w": 200.1, "h": 20.1}, 1280, 720) == (0, 0, 312, 101)


def setup_loop(monkeypatch, tmp_path, counts, reviews, proposals):
    source = tmp_path / "source.html"
    initial = '<!doctype html><html><style>.a{left:0px}</style><body><p>Fixed copy</p></body></html>'
    source.write_text(initial)
    drafts = [initial] + [initial.replace("left:0px", f"left:{i}px") for i in range(1, proposals+1)]
    def measure(path, png):
        idx = drafts.index(path.read_text())
        return {"text_collision_count": counts[idx]}
    inputs = []
    def propose(client, model, prompt, png):
        inputs.append(prompt)
        return drafts[len(inputs)]
    review_iter = iter(reviews)
    monkeypatch.setattr(repair, "render_and_measure", measure)
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: next(review_iter))
    monkeypatch.setattr(repair, "call_repair", propose)
    monkeypatch.setattr(repair, "visual_change_audit", lambda *args: {"changed_pixel_ratio": .01})
    return source, drafts, inputs


PASS = {"verdict": "pass", "issues": [], "valid": True}
REVISE = {"verdict": "revise", "issues": [{"description": "relation label crowds body"}], "valid": True}
UNCERTAIN = {"verdict": "uncertain", "issues": [], "valid": False}


def test_source_review_cannot_be_overridden_by_model_pass(monkeypatch, tmp_path):
    source, drafts, inputs = setup_loop(monkeypatch, tmp_path, [0], [PASS], 0)
    monkeypatch.setattr(repair, "render_and_measure", lambda *args: {
        "text_collision_count": 0, "source_asset_issue_count": 1,
        "source_asset_issue_details": [{"reason": "suspected-extraction-fragment"}],
    })
    result = repair.repair_file(None, "test", source, tmp_path / "run", 2)
    assert result["status"] == "needs_source_review"
    assert result["source_review_required"]
    assert result["final_hard_issues"] == 0
    assert not result["changed"]
    assert not inputs


def test_spatial_repair_does_not_clear_source_review(monkeypatch, tmp_path):
    source, drafts, inputs = setup_loop(monkeypatch, tmp_path, [1, 0], [REVISE, PASS], 1)
    original_measure = repair.render_and_measure

    def measure(*args):
        return {**original_measure(*args), "source_asset_issue_count": 1}

    monkeypatch.setattr(repair, "render_and_measure", measure)
    result = repair.repair_file(None, "test", source, tmp_path / "run", 2)
    assert result["selected_attempt"] == 1
    assert result["initial_hard_issues"] == 1
    assert result["final_hard_issues"] == 0
    assert result["changed"]
    assert result["status"] == "needs_source_review"
    assert result["source_review_required"]


def test_zero_geometry_still_runs_visual_repair(monkeypatch, tmp_path):
    source, drafts, inputs = setup_loop(monkeypatch, tmp_path, [0, 0], [REVISE, PASS], 1)
    result = repair.repair_file(None, "test", source, tmp_path / "run", 2)
    assert result["selected_attempt"] == 1
    assert result["status"] == "ready_for_human_review"
    assert "relation label crowds body" in inputs[0]


def test_equal_count_draft_is_used_for_next_attempt(monkeypatch, tmp_path):
    source, drafts, inputs = setup_loop(monkeypatch, tmp_path, [1, 1, 0], [REVISE, REVISE, PASS], 2)
    result = repair.repair_file(None, "test", source, tmp_path / "run", 2)
    assert drafts[1] in inputs[1]
    assert result["attempts"][1]["parent_attempt"] == 1
    assert result["status"] == "ready_for_human_review"


def test_rejected_draft_does_not_mix_html_and_diagnostics(monkeypatch, tmp_path):
    source, drafts, inputs = setup_loop(monkeypatch, tmp_path, [1, 2, 0], [REVISE, PASS], 2)
    result = repair.repair_file(None, "test", source, tmp_path / "run", 2)
    assert drafts[0] in inputs[1]
    assert drafts[1] not in inputs[1]
    assert result["attempts"][1]["parent_attempt"] == 0


def test_uncertain_review_cannot_accept_zero_count_candidate(monkeypatch, tmp_path):
    source, drafts, inputs = setup_loop(monkeypatch, tmp_path, [1, 0], [REVISE, UNCERTAIN], 1)
    result = repair.repair_file(None, "test", source, tmp_path / "run", 1)
    assert result["selected_attempt"] == 0
    assert result["status"] == "needs_repair"
