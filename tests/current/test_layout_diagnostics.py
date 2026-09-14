from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import sync_playwright

from scripts.evaluate_scene_similarity import _layout_validity


BASE = """<!doctype html><style>
html,body{margin:0;width:1280px;height:720px}.slide{position:relative;width:1280px;height:720px}
.copy{position:absolute;left:100px;top:100px;font:32px/1 Arial;color:#000}
%s
</style><main class=slide><div class=copy><span>Visible words</span></div>%s</main>"""


def measure(tmp_path: Path, css: str, markup: str) -> dict:
    source = tmp_path / "slide.html"
    source.write_text(BASE % (css, markup))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(source.resolve().as_uri())
        result = _layout_validity(page)
        browser.close()
    return result


@pytest.mark.parametrize("offset,expected", [(0, 0), (100, 1), (-100, 1)])
def test_svg_dash_gaps_are_not_solid_obstacles(tmp_path, offset, expected):
    result = measure(tmp_path, "", '<svg width="1280" height="720" style="position:absolute;inset:0">'
        f'<line x1="150" y1="0" x2="150" y2="400" stroke="black" stroke-dasharray="50 150" stroke-dashoffset="{offset}"/>'
        '</svg>')
    assert result["graphic_text_collision_count"] == expected


@pytest.mark.parametrize("width,crowded", [(96, True), (140, False)])
def test_small_centered_labels_need_clearance_from_vertical_borders(tmp_path, width, crowded):
    result = measure(tmp_path, f".copy{{font:12px/1 monospace;text-align:center;text-transform:uppercase;"
                     f"border-inline:1px solid #000;height:80px;width:{width}px}}", "")
    assert bool(result["graphic_text_clearance_count"]) is crowded


@pytest.mark.parametrize("css,expected", [
    (".copy{transform:scaleX(.86)}", True),
    (".copy{transform:scaleY(.8)}", True),
    (".copy{scale:86% 100%}", True),
    (".copy{zoom:.8}", True),
    (".slide{transform:scale(.95)}.copy{transform:scale(.9)}", True),
    (".copy{transform:rotate(20deg)}", False),
    (".copy{rotate:20deg}", False),
    (".copy{transform:scale(.88)}", True),
    (".slide{transform:scale(.8)}.copy{transform:scale(1.25)}", False),
    (".copy{transform:scale(1.1)}", False),
])
def test_rendered_typography_scale_cannot_bypass_font_guard(tmp_path, css, expected):
    from scripts.repair import computed_type_reductions

    before = measure(tmp_path, "", "")
    after = measure(tmp_path, css, "")
    assert bool(computed_type_reductions(before, after)) is expected


@pytest.mark.parametrize("width,blocked", [(150, False), (80, True)])
def test_svg_viewbox_scale_is_audited_against_effective_floor(tmp_path, width, blocked):
    from scripts.repair import computed_type_reductions
    from redeck_style.typography import typography_audit

    markup = '<svg class="chart" width="300" height="100" viewBox="0 0 300 100"><text x="20" y="40" font-size="32">Chart label</text></svg>'
    before = measure(tmp_path, "", markup)
    after = measure(tmp_path, f".chart{{width:{width}px;height:{width / 3}px}}", markup)
    assert bool(computed_type_reductions(before, after)) is blocked
    assert typography_audit(before, after)["review_required"]


def test_existing_text_scale_is_not_a_new_reduction(tmp_path):
    from scripts.repair import computed_type_reductions

    before = measure(tmp_path, ".copy{transform:scaleX(.8)}", "")
    after = measure(tmp_path, ".copy{transform:scaleX(.8);left:180px}", "")
    assert not computed_type_reductions(before, after)


def test_svg_path_length_scales_dashes_and_hidden_stroke_is_not_a_hit(tmp_path):
    result = measure(tmp_path, "", '<svg width="1280" height="720" style="position:absolute;inset:0">'
        '<line x1="150" y1="0" x2="150" y2="400" pathLength="100" stroke="black" stroke-dasharray="12.5 37.5"/>'
        '<line x1="160" y1="0" x2="160" y2="400" stroke="black" stroke-opacity="0"/></svg>')
    assert result["graphic_text_collision_count"] == 0


@pytest.mark.parametrize("shape", [
    '<line x1="150" y1="0" x2="150" y2="400" stroke-dasharray="50 150 50"/>',
    '<path d="M150 0 L150 400" stroke-dasharray="50 150"/>',
    '<path d="M140 0 Q160 200 140 400" stroke-dasharray="50 150"/>',
])
def test_dashed_single_path_and_odd_arrays_preserve_empty_gaps(tmp_path, shape):
    result = measure(tmp_path, "", '<svg width="1280" height="720" style="position:absolute;inset:0">'
        f'<g stroke="black" fill="none">{shape}</g></svg>')
    assert result["graphic_text_collision_count"] == 0


def test_all_graphic_pairs_are_retained_in_diagnostics(tmp_path):
    lines = ''.join(f'<line x1="{110+index*10}" y1="90" x2="{110+index*10}" y2="145"/>' for index in range(12))
    result = measure(tmp_path, "", '<svg width="1280" height="720" style="position:absolute;inset:0">'
        f'<g stroke="black">{lines}</g></svg>')
    assert result["graphic_text_collision_count"] > 8
    assert len(result["graphic_text_collision_details"]) == result["graphic_text_collision_count"]


@pytest.mark.parametrize("background,fill_width,label_left,expected", [
    ("#eee", 100, 170, 0), ("#222", 100, 170, 1), ("#eee", 220, 170, 2),
])
def test_readable_track_labels_are_not_separator_collisions(tmp_path, background, fill_width, label_left, expected):
    result = measure(tmp_path,
        f'.track{{position:absolute;left:100px;top:220px;width:400px;height:8px;background:{background}}}'
        f'.fill{{width:{fill_width}px;height:8px;background:#16a}}'
        f'.value{{position:absolute;left:{100+label_left}px;top:207px;font:20px/1 Arial;color:#000}}',
        '<div class="track"><div class="fill"></div></div><div class="value">0.7500</div>')
    assert result["graphic_text_collision_count"] == expected
    assert bool(result["background_label_overlaps"]) == (expected == 0)


def test_text_collision_counts_distinct_element_pairs(tmp_path):
    result = measure(tmp_path, '.pair{position:absolute;left:100px;top:100px;font:32px Arial}'
        '.pair.second{top:200px}.pair.third{top:200px}',
        '<div class="pair">Overlap</div><div class="pair second">Second</div><div class="pair third">Third</div>')
    assert result["text_collision_count"] == 2
    assert len(result["text_collision_details"]) == 2


@pytest.mark.parametrize("size", [(667, 28), (28, 667)])
def test_source_fragment_uses_intrinsic_dimensions_not_display_size(tmp_path, size):
    source = tmp_path / "fragment.png"
    Image.new("RGB", size, "white").save(source)
    result = measure(tmp_path, "", '<img id="evidence" src="fragment.png" width="600" height="300">')
    assert result["source_asset_issue_count"] == 1
    issue = result["source_asset_issue_details"][0]
    assert issue["reason"] == "suspected-extraction-fragment"
    assert (issue["intrinsic_width"], issue["intrinsic_height"]) == size
    assert issue["selector"] == "#evidence"


@pytest.mark.parametrize("size", [(667, 280), (2441, 215), (24, 24)])
def test_regular_figures_wide_figures_and_icons_are_not_source_fragments(tmp_path, size):
    Image.new("RGB", size, "white").save(tmp_path / "figure.png")
    result = measure(tmp_path, "", '<img src="figure.png" width="80" height="20">')
    assert result["source_asset_issue_count"] == 0


def test_unavailable_source_image_requires_review(tmp_path):
    result = measure(tmp_path, "", '<img src="missing.png" width="600" height="300">')
    assert result["source_asset_issue_count"] == 1
    assert result["source_asset_issue_details"][0]["reason"] == "unavailable-image"


def test_css_cannot_hide_an_informative_source_fragment(tmp_path):
    Image.new("RGB", (667, 28), "white").save(tmp_path / "fragment.png")
    result = measure(tmp_path, "", '<img src="fragment.png" style="display:none">')
    assert result["source_asset_issue_count"] == 1


def test_explicit_decoration_is_not_source_evidence(tmp_path):
    Image.new("RGB", (667, 28), "white").save(tmp_path / "rule.png")
    result = measure(tmp_path, "", '<img class="deco" src="rule.png">')
    assert result["source_asset_issue_count"] == 0


ARROW = ('<svg style="position:absolute;inset:0" width="1280" height="720">'
         '<defs><marker id="tip" markerWidth="8" markerHeight="8" refX="6.5" refY="4" orient="auto">'
         '<path d="M0 0 L8 4 L0 8 Z" fill="#008080"/></marker></defs>'
         '<path id="connector" d="%s" fill="none" stroke="#008080" stroke-width="2" marker-end="url(#tip)"/></svg>')


def test_arrow_crossing_separator_without_touching_text_is_reported(tmp_path):
    result = measure(tmp_path,
                     '.separator{position:absolute;left:498px;top:397px;width:628px;height:90px;border-top:1px solid #777}',
                     '<div class="separator"></div>' + ARROW % 'M988 346 C1048 346 1062 391 1046 416')
    assert result['graphic_text_collision_count'] == 0
    assert result['connector_rule_collision_count'] == 1
    issue = result['connector_rule_collision_details'][0]
    assert issue['connector']['selector'] == '#connector'
    assert abs(issue['rect']['y'] + 12 - 397.5) < 1
    assert any(item['selector'] == '#connector' for item in result['graphic_geometry'])


def test_arrow_crossing_thin_filled_separator_is_reported(tmp_path):
    result = measure(tmp_path,
                     '.separator{position:absolute;left:400px;top:400px;width:400px;height:2px;background:#777}',
                     '<div class="separator"></div>' + ARROW % 'M600 350 L600 450')
    assert result['connector_rule_collision_count'] == 1


def test_node_docking_is_allowed_but_separator_is_not_a_target(tmp_path):
    result = measure(tmp_path,
                     '.separator{position:absolute;left:400px;top:400px;width:400px;height:90px;border:1px solid #777}',
                     '<div class="separator"></div>' + ARROW % 'M600 350 L600 400')
    assert result['connector_rule_collision_count'] == 0
    result = measure(tmp_path,
                     '.separator{position:absolute;left:400px;top:400px;width:400px;height:90px;border-top:1px solid #777}',
                     '<div class="separator"></div>' + ARROW % 'M600 350 L600 400')
    assert result['connector_rule_collision_count'] == 1


def test_arrowhead_at_separator_endpoint_is_not_a_clean_fix(tmp_path):
    result = measure(tmp_path,
                     '.separator{position:absolute;left:400px;top:400px;width:400px;height:90px;border-top:1px solid #777}',
                     '<div class="separator"></div>' + ARROW % 'M900 350 Q920 400 802 400')
    assert result['connector_rule_collision_count'] == 1
    result = measure(tmp_path,
                     '.separator{position:absolute;left:400px;top:400px;width:400px;height:90px;border-top:1px solid #777}',
                     '<div class="separator"></div>' + ARROW % 'M900 350 Q920 400 825 400')
    assert result['connector_rule_collision_count'] == 0


def test_chart_axis_and_grid_intersections_are_not_connector_errors(tmp_path):
    result = measure(tmp_path, '', ARROW % 'M400 600 L900 600' +
                     '<svg style="position:absolute;inset:0" width="1280" height="720">'
                     '<path d="M500 300 V620 M600 300 V620" stroke="#aaa" fill="none"/></svg>')
    assert result['connector_rule_collision_count'] == 0


def test_pseudo_border_remains_detectable_after_rule_reimplementation(tmp_path):
    result = measure(tmp_path,
                     '.separator{position:absolute;left:400px;top:400px;width:400px;height:90px}'
                     '.separator:before{content:"";position:absolute;left:0;top:0;width:400px;border-top:1px solid #777}',
                     '<div class="separator"></div>' + ARROW % 'M600 350 L600 450')
    assert result['connector_rule_collision_count'] == 1


def test_arrowhead_hidden_in_later_painted_panel_is_reported(tmp_path):
    css = '.panel{position:absolute;left:400px;top:400px;width:400px;height:180px;background:#008080}'
    result = measure(tmp_path, css, ARROW % 'M600 350 L600 450' + '<div class="panel"></div>')
    assert result['connector_occlusion_count'] == 1
    result = measure(tmp_path, css, ARROW % 'M600 350 L600 398' + '<div class="panel"></div>')
    assert result['connector_occlusion_count'] == 0
    # Same boxes, reversed painting order: the endpoint remains visible.
    result = measure(tmp_path, css, '<div class="panel"></div>' + ARROW % 'M600 350 L600 450')
    assert result['connector_occlusion_count'] == 0


def test_svg_connector_crossing_text_is_reported(tmp_path):
    result = measure(
        tmp_path,
        "",
        '<svg style="position:absolute;inset:0" width="1280" height="720">'
        '<line x1="90" y1="118" x2="330" y2="118" stroke="#f00" stroke-width="3"/></svg>',
    )
    assert result["graphic_text_collision_count"] >= 1
    assert any("svg-connector" in role for role in result["graphic_text_collision_roles"])


def test_css_rule_and_pseudo_arrow_crossing_text_are_reported(tmp_path):
    result = measure(
        tmp_path,
        ".rule{position:absolute;left:80px;top:116px;width:280px;height:4px;background:#f00}"
        ".arrow{position:absolute;left:200px;top:90px;width:30px;height:20px}"
        ".arrow:after{content:'→';position:absolute;left:0;top:10px;font:28px/1 Arial;color:#00f}",
        '<div class="rule"></div><div class="arrow"></div>',
    )
    assert result["graphic_text_collision_count"] >= 2
    roles = " ".join(result["graphic_text_collision_roles"])
    assert "css-rule" in roles
    assert "pseudo-after" in roles


def test_enclosing_border_and_distant_connector_are_not_reported(tmp_path):
    result = measure(
        tmp_path,
        ".copy{border:2px solid #000;padding:12px}.rule{position:absolute;left:80px;top:250px;width:280px;height:4px;background:#f00}",
        '<div class="rule"></div>',
    )
    assert result["graphic_text_collision_count"] == 0


def test_svg_marker_footprint_crossing_text_is_reported(tmp_path):
    result = measure(
        tmp_path,
        ".copy{left:215px}",
        '<svg class="flow" style="position:absolute;inset:0" width="1280" height="720">'
        '<defs><marker id="tip" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto">'
        '<path d="M0 0 L10 5 L0 10 Z" fill="#f00"/></marker></defs>'
        '<line x1="100" y1="118" x2="212" y2="118" stroke="#f00" stroke-width="3" marker-end="url(#tip)"/>'
        '</svg>',
    )
    assert any("svg-marker-end" in role for role in result["graphic_text_collision_roles"])


def test_filled_svg_arrowhead_crossing_text_is_reported(tmp_path):
    result = measure(
        tmp_path,
        ".copy{left:200px}",
        '<svg class="flow" style="position:absolute;inset:0" width="1280" height="720">'
        '<polygon points="190,108 220,118 190,128" fill="#f00"/></svg>',
    )
    assert any("svg-filled-mark" in role for role in result["graphic_text_collision_roles"])


def test_parent_border_that_crosses_descendant_text_is_reported(tmp_path):
    result = measure(
        tmp_path,
        ".copy{border-top:4px solid #f00}.copy span{position:relative;top:-18px}",
        "",
    )
    assert result["graphic_text_collision_count"] >= 1


def test_color_mix_border_crossing_overhanging_text_is_reported(tmp_path):
    result = measure(
        tmp_path,
        ".copy{width:120px;font:900 68px/.88 Impact,Arial,sans-serif;"
        "border-right:3px solid color-mix(in srgb,#000 22%,transparent)}",
        "",
    )
    assert any("css-border" in role for role in result["graphic_text_collision_roles"])


def test_color_mix_border_clear_of_overhanging_text_is_not_reported(tmp_path):
    result = measure(tmp_path, ".copy{width:260px;border-right:3px solid color-mix(in srgb,#000 22%,transparent)}", "")
    assert result["graphic_text_collision_count"] == 0


def test_large_display_text_nearly_touching_divider_needs_clearance(tmp_path):
    result = measure(tmp_path, ".copy{font:64px/1 monospace;white-space:nowrap;width:504px;border-right:3px solid #000}", "")
    assert result["graphic_text_collision_count"] == 0
    assert result["graphic_text_clearance_count"] == 1
    assert result["graphic_text_clearance_details"][0]["gap_px"] < 12


def test_large_display_text_with_breathing_room_passes(tmp_path):
    result = measure(tmp_path, ".copy{font:64px/1 monospace;white-space:nowrap;width:524px;border-right:3px solid #000}", "")
    assert result["graphic_text_collision_count"] == 0
    assert result["graphic_text_clearance_count"] == 0


def test_display_clearance_just_under_threshold_is_not_lost_to_ink_inset(tmp_path):
    result = measure(tmp_path, ".copy{font:64px/1 monospace;white-space:nowrap;width:calc(13ch + 11.6px);border-right:3px solid #000}", "")
    assert result["graphic_text_collision_count"] == 0
    assert result["graphic_text_clearance_count"] == 1
    assert 11.5 < result["graphic_text_clearance_details"][0]["gap_px"] < 12


def test_relation_label_wedged_into_body_is_not_clean(tmp_path):
    result = measure(tmp_path, ".copy{font:20px/1 monospace}.relation{position:absolute;left:258px;top:102px;font:11px/1 Arial}", '<div class="relation">causes</div>')
    assert result["text_collision_count"] == 0
    assert result["text_clearance_count"] == 1


def test_relation_label_above_body_passes(tmp_path):
    result = measure(tmp_path, ".copy{font:20px/1 monospace}.relation{position:absolute;left:258px;top:65px;font:11px/1 Arial}", '<div class="relation">causes</div>')
    assert result["text_clearance_count"] == 0


def test_floating_label_between_two_prose_groups_needs_own_lane(tmp_path):
    result = measure(tmp_path, ".copy{font:20px/1 monospace}.relation{position:absolute;left:270px;top:102px;font:11px/1 monospace}.body{position:absolute;left:321px;top:100px;font:20px/1 monospace}",
                     '<div class="relation">causes</div><p class="body" style="margin:0">Another sentence</p>')
    assert result["text_collision_count"] == 0
    assert result["text_clearance_count"] == 0
    assert result["text_association_count"] == 1


def test_low_contrast_report_identifies_actual_text(tmp_path):
    result = measure(tmp_path, ".copy{color:color-mix(in srgb,#000 10%,transparent)}", "")
    assert result["low_contrast_count"] >= 1
    assert result["low_contrast_details"][0]["text"] == "Visible words"
    assert result["low_contrast_details"][0]["contrast_ratio"] < 3


def test_contrast_between_three_and_four_point_five_is_not_a_pass(tmp_path):
    result = measure(tmp_path, ".copy{color:#888;background:#fff}", "")
    issue = result["low_contrast_details"][0]
    assert 3 < issue["contrast_ratio"] < 4.5
    assert issue["minimum"] == 4.5


def test_transparent_color_mix_rule_is_not_reported(tmp_path):
    result = measure(tmp_path, ".copy{width:120px;border-right:3px solid color-mix(in srgb,#000 0%,transparent)}", "")
    assert result["graphic_text_collision_count"] == 0


def test_svg_disconnected_subpaths_do_not_create_phantom_diagonal(tmp_path):
    result = measure(tmp_path, "", '<svg width="1280" height="720" style="position:absolute;inset:0">'
                     '<path d="M50 80H400 M50 155H400" fill="none" stroke="#000"/></svg>')
    assert result["graphic_text_collision_count"] == 0


def test_repeated_classes_and_nested_svg_selectors_resolve_uniquely(tmp_path):
    result = measure(tmp_path, ".copy:nth-child(2){top:180px}",
                     '<div class="copy"><span>Second words</span></div>'
                     '<svg width="1280" height="720" style="position:absolute;inset:0">'
                     '<defs><marker id="tip"><path d="M0 0L5 5"/></marker></defs>'
                     '<g><path d="M90 118H330 M90 198H330" fill="none" stroke="#000"/></g></svg>')
    assert result["graphic_text_collision_count"] == 2
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto((tmp_path / "slide.html").as_uri())
        for issue in result["graphic_text_collision_details"]:
            assert page.locator(issue["graphic"]["selector"]).count() == 1
            assert page.locator(issue["text"]["selector"]).count() == 1
        browser.close()
