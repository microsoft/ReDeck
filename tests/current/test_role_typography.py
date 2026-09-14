import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from redeck_style.content_repair import apply_proposal
from redeck_style.repair import parse_visual_review, typography_policy_prompt, validate_repair
from redeck_style.typography import typography_audit, typography_constraints
from scripts import content_repair, repair
from scripts.evaluate_scene_similarity import _layout_validity
from scripts.repair_session import run_repair_jobs
from test_content_repair import HTML, PASS, context, proposal, setup_session
from test_joint_repair import REVISE, install_measure


QUALITY = {**PASS, "scope": {"verdict": "preserved", "reason": "Palette and semantic roles remain."},
           "typography": {"verdict": "readable", "reason": "The secondary heading is readable at 28px."},
           "composition": {"verdict": "coherent", "reason": "The sidebar and main content keep clear tracks."}}


def text(size, role="sidebar_heading", **extra):
    return {"selector": "p", "font_px": size, "font_scale": {"x": 1, "y": 1},
            "typography": {"role": role, "available_width_px": 140, "max_word_width_px": 335.43}, **extra}


def validity(*items):
    return {"text_geometry": list(items)}


def test_secondary_type_can_shrink_by_more_than_half_with_review():
    audit = typography_audit(validity(text(58)), validity(text(28)))
    assert not audit["violations"] and audit["review_required"]
    assert audit["changes"][0]["minimum_effective_px"] == 24
    assert typography_constraints(validity(text(58)))[0]["proportional_fit_hint_px"] == 24.21


@pytest.mark.parametrize("role,original,proposed", [("body", 16, 8), ("title", 48, 24),
                                                  ("sidebar_heading", 58, 16), ("note", 13, 9),
                                                  ("unknown", 24, 12), ("citation", 10, 8)])
def test_rendered_role_floors_are_hard_boundaries(role, original, proposed):
    audit = typography_audit(validity(text(original, role)), validity(text(proposed, role)))
    assert audit["violations"]
    assert "floor" in audit["violations"][0]["reason"]


def test_original_small_copy_is_grandfathered_without_further_shrink():
    original = validity(text(10, "body"))
    assert not typography_audit(original, validity(text(10, "body")))["violations"]
    assert typography_audit(original, validity(text(9.5, "body")))["violations"]


@pytest.mark.parametrize("size", [13.336, 11.996])
def test_fractional_original_floor_is_not_rounded_up(size):
    original = validity(text(size, "body"))
    assert typography_constraints(original)[0]["minimum_effective_px"] == size
    assert not typography_audit(original, original)["violations"]
    assert typography_audit(original, validity(text(size - 0.1, "body")))["violations"]


def test_candidate_cannot_relabel_role_to_lower_its_floor():
    assert typography_audit(validity(text(58)), validity(text(12, "note")))["violations"]
    original = '<html><body><p data-level="body">Unchanged words</p></body></html>'
    assert not validate_repair(original, original.replace('"body"', '"note"')).accepted


@pytest.mark.parametrize("scale", [{"x": .9, "y": 1}, {"x": 1, "y": .9}, {"x": .9, "y": .9}])
def test_transform_compression_is_not_ordinary_font_size_adjustment(scale):
    audit = typography_audit(validity(text(58)), validity(text(58, font_scale=scale)))
    assert audit["violations"] and "compression" in audit["violations"][0]["reason"]


def test_excessive_tracking_cannot_replace_font_size_repair():
    candidate = text(58, typography={"role": "sidebar_heading", "tracking_px": -12})
    assert typography_audit(validity(text(58)), validity(candidate))["violations"]


def test_widespread_body_reduction_requires_visual_review_even_above_floor():
    original = validity(text(24, "body"), text(24, "body", selector="p2"))
    candidate = validity(text(22, "body"), text(22, "body", selector="p2"))
    result = typography_audit(original, candidate)
    assert not result["violations"] and result["review_required"]
    assert any("Most body" in item["reason"] for item in result["warnings"])


@pytest.mark.parametrize("key", ["typography", "composition"])
@pytest.mark.parametrize("detail", [None, {}, {"verdict": "uncertain", "reason": "Cannot assess"},
                                   {"verdict": "needs_repair", "reason": "Competing hierarchy"}])
def test_visual_pass_requires_both_quality_dimensions(key, detail):
    candidate = {**QUALITY, key: detail}
    assert not parse_visual_review(json.dumps(candidate), {"p"}, require_scope=True, require_quality=True)["valid"]


def test_zero_hard_count_does_not_overrule_bad_composition():
    review = {**QUALITY, **REVISE,
              "composition": {"verdict": "needs_repair", "reason": "A background patch displaces the main argument."}}
    parsed = parse_visual_review(json.dumps(review), {"p"}, require_scope=True, require_quality=True)
    assert parsed["valid"] and repair.needs_spatial({"validity": {}, "review": parsed})


@pytest.mark.parametrize("content_enabled", [False, True])
@pytest.mark.parametrize("target_size,approved", [(28, True), (12, False)])
def test_both_repair_actions_use_the_same_rendered_type_contract(tmp_path, context, monkeypatch, content_enabled, target_size, approved):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    source = Path(jobs[0]["source"])
    source.write_text(HTML.replace("24px", "58px"))
    install_measure(monkeypatch, lambda html: {**validity(text(58 if "58px" in html else target_size)),
                                               "text_collision_count": int("58px" in html)})
    monkeypatch.setattr(repair, "call_visual_review", lambda client, model, original, current, measured:
                        {**QUALITY, **REVISE} if measured.get("text_collision_count") else QUALITY)

    def spatial(client, model, prompt, png):
        assert typography_policy_prompt() in repair.repair_system_prompt()
        assert typography_policy_prompt() not in prompt
        assert '"minimum_effective_px": 24' in prompt
        return prompt.split("Current complete HTML:\n", 1)[1].strip().replace("58px", f"{target_size}px")

    def content(client, model, current, png, measured, issues, catalog, feedback, prefix, layout):
        assert typography_policy_prompt() in content_repair.SYSTEM
        action = proposal()
        action["css_edits"] = [{"search": "58px", "replace": f"{target_size}px"}]
        return {**apply_proposal(current, action, issues, catalog, layout), "calls": []}

    monkeypatch.setattr(repair, "call_repair", spatial)
    monkeypatch.setattr(content_repair, "propose", content)
    if not content_enabled:
        options = {**options, "mode": "off"}
    row = run_repair_jobs(jobs, output, "fixture", 1, options, client_factory=lambda: None)[0]
    assert row["changed"] is approved
    assert row["content_edit"]["applied"] is (approved and content_enabled)
    assert row["attempts"][0]["gates"]["safety_passed"] is approved
    if approved:
        assert row["attempts"][0]["gates"]["typography_required"]
        assert row["attempts"][0]["typography_audit"]["review_required"]
        assert row["attempt_budget"]["used"] == 1


def test_large_font_change_cannot_be_selected_without_quality_review(tmp_path, context, monkeypatch):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    source = Path(jobs[0]["source"])
    source.write_text(HTML.replace("24px", "58px"))
    install_measure(monkeypatch, lambda html: {**validity(text(58 if "58px" in html else 28)),
                                               "text_collision_count": int("58px" in html)})
    monkeypatch.setattr(repair, "call_visual_review", lambda *args: PASS)
    monkeypatch.setattr(repair, "call_repair", lambda client, model, prompt, png:
                        prompt.split("Current complete HTML:\n", 1)[1].strip().replace("58px", "28px"))
    row = run_repair_jobs(jobs, output, "fixture", 1, {**options, "mode": "off"}, client_factory=lambda: None)[0]
    assert not row["changed"]
    assert any("Typography changes require" in reason for reason in row["attempts"][0]["review_reasons"])


@pytest.mark.parametrize("bypass_proposal_gate", [False, True])
def test_content_only_cannot_authorize_large_typography_change(tmp_path, context, monkeypatch, bypass_proposal_gate):
    jobs, output, options = setup_session(tmp_path, context, monkeypatch)
    Path(jobs[0]["source"]).write_text(HTML.replace("24px", "58px"))
    install_measure(monkeypatch, lambda html: validity(text(58 if "58px" in html else 28)))

    def content(client, model, current, png, measured, issues, catalog, feedback, prefix, layout):
        action = proposal()
        action["css_edits"] = [{"search": "58px", "replace": "28px"}]
        return {**apply_proposal(current, action, issues, catalog, True if bypass_proposal_gate else layout), "calls": []}

    monkeypatch.setattr(content_repair, "propose", content)
    row = run_repair_jobs(jobs, output, "fixture", 1, {**options, "routes": ["content"]}, client_factory=lambda: None)[0]
    assert not row["changed"] and not row["content_edit"]["applied"]
    if bypass_proposal_gate:
        assert any("Typography changes require" in reason for reason in row["attempts"][0]["review_reasons"])
    else:
        assert "Layout edits are disabled" in row["attempts"][0]["reason"]


def test_browser_secondary_heading_fit_without_background_patch():
    original = '<html><style>body{margin:0}aside{width:196px;padding:28px;box-sizing:border-box}' \
               '.big{font:900 58px/1 Arial;letter-spacing:-1.9px;text-transform:uppercase}h1{font:700 38px Arial}</style>' \
               '<body><aside><div class="big">Mediated<br>inclusion?</div></aside><h1>Main claim</h1></body></html>'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.set_content(original)
        before = _layout_validity(page)
        page.set_content(original.replace("58px", "28px").replace("28px;box-sizing", "16px;box-sizing").replace("-1.9px", "-.9px"))
        after = _layout_validity(page)
        browser.close()
    heading = next(item for item in before["text_geometry"] if "big" in item["selector"])
    resized = next(item for item in after["text_geometry"] if item["selector"] == heading["selector"])
    assert heading["typography"]["role"] == "sidebar_heading"
    assert resized["typography"]["max_word_width_px"] <= resized["typography"]["available_width_px"]
    audit = typography_audit(before, after)
    assert not audit["violations"] and audit["review_required"]
