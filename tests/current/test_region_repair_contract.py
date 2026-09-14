import json

import pytest
from playwright.sync_api import sync_playwright

from redeck_style.evaluation import probes
from redeck_style.evaluation.contracts import summarize_records
from redeck_style.repair import compact_diagnostics, hard_issue_count, issue_counts, needs_spatial, repair_feedback, validate_repair
from redeck_style.typography import typography_audit, typography_constraints
from scripts.evaluate_scene_similarity import _layout_validity
from test_role_typography import QUALITY


@pytest.fixture
def measure():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        def capture(source):
            page.set_content(source)
            return _layout_validity(page)

        yield capture
        browser.close()


SVG = '<svg width="400" height="140" viewBox="0 0 600 210"><text x="20" y="50" font-size="18">Industrial district daytime runs</text></svg>'
WRAP = '<text x="20" y="50" font-size="18"><tspan x="20">Industrial district</tspan><tspan x="20" dy="22">daytime runs</tspan></text>'


def wrapped():
    return SVG.replace('<text x="20" y="50" font-size="18">Industrial district daytime runs</text>', WRAP)


def test_svg_layout_lines_inherit_original_rendered_identity(measure):
    before, after = measure(SVG), measure(wrapped())
    assert validate_repair(SVG, wrapped()).accepted
    spans = [item for item in after["text_geometry"] if "tspan" in item["selector"]]
    assert len(spans) == 2
    assert all(item["layout_parent_selector"] == "text" for item in spans)
    assert not typography_audit(before, after)["violations"]
    assert not typography_audit(after, before)["violations"]


@pytest.mark.parametrize("change", [lambda source: source.replace('font-size="18"', 'font-size="8"'),
                                    lambda source: source.replace('0 0 600 210', '0 0 900 210')])
def test_svg_layout_lines_cannot_hide_real_size_compression(measure, change):
    before, after = measure(SVG), measure(change(wrapped()))
    assert typography_audit(before, after)["violations"]


def test_unrelated_new_svg_label_does_not_inherit_floor(measure):
    candidate = SVG.replace('</svg>', '<text x="20" y="80" font-size="8">New fact</text></svg>')
    assert not validate_repair(SVG, candidate).accepted
    assert typography_audit(measure(SVG), measure(candidate))["violations"]


PANEL = '<style>.panel{width:420px;height:240px;border:1px solid black}p,li,td{font-size:14px}h3{font-size:18px}</style><div class="panel"><h3>Reading notes</h3><p>Important supporting details</p><ul><li>Relevant qualification</li></ul><table><tr><td>Measured value 42</td></tr></table></div>'


def test_dense_original_roles_allow_modest_font_reduction(measure):
    before = measure(PANEL)
    after = measure(PANEL.replace('font-size:14px', 'font-size:12px'))
    roles = {item['typography']['role'] for item in before['text_geometry']}
    assert {'table_cell', 'supporting_copy', 'panel_heading'} <= roles
    audit = typography_audit(before, after)
    assert not audit['violations'] and audit['review_required']
    assert {item['minimum_effective_px'] for item in typography_constraints(before)
            if item['role'] in {'table_cell', 'supporting_copy'}} == {12}


def test_dense_original_roles_do_not_allow_unreadable_copy(measure):
    assert typography_audit(measure(PANEL), measure(PANEL.replace('font-size:14px', 'font-size:9px')))['violations']


def test_full_body_does_not_become_supporting_copy_after_relayout(measure):
    source = '<style>p{font-size:16px}</style><p>Primary explanation stays primary.</p>'
    before = measure(source)
    after = measure(source.replace('16px', '12px').replace('<p>', '<div style="width:400px;height:100px;border:1px solid"><p>') + '</div>')
    assert before['text_geometry'][0]['typography']['role'] == 'body'
    assert not validate_repair(source, source.replace('16px', '12px') + '<aside>new</aside>').accepted
    assert typography_audit(before, after)['violations']


def test_region_capacity_keeps_original_topology_and_real_overflow(measure):
    source = '<div style="display:grid;grid-template-columns:1fr 1fr;width:500px;height:80px;overflow:hidden"><p style="height:140px">Left panel content</p><p>Right panel</p></div>'
    before = measure(source)
    region = before['region_geometry'][0]
    assert region['content_height_px'] > region['rect']['h'] and region['overflow_y_px'] > 0
    feedback = repair_feedback(before, {'attempt': 1, 'validity': before, 'review': QUALITY}, 'spatial')
    assert 'CURRENT region capacity' in feedback and 'original_columns' in feedback
    assert 'overflow_y_px' in feedback


def test_style_advisories_do_not_mask_geometry_or_readability():
    validity = {'gradient_violation_count': 2}
    assert hard_issue_count(validity) == 2
    assert issue_counts(validity) == {'geometry': 0, 'readability': 0, 'style_advisory': 2, 'repair_blocking': 0, 'raw_total': 2}
    assert not needs_spatial({'validity': validity, 'review': QUALITY})
    for key in ('overflow_count', 'low_contrast_count'):
        assert needs_spatial({'validity': {**validity, key: 1}, 'review': QUALITY})
    records = probes.spatial_records(validity, QUALITY, 1)
    report = probes.summarize(records)
    assert report['status'] == 'passed' and len(report['advisories']) == 1
    assert report['issues'][0]['remediation'] == 'style_review'


def test_content_issue_cannot_claim_style_advisory_status():
    report = summarize_records([{'probe_id': 'E02', 'route': 'content', 'issues': [{'remediation': 'style_review'}]}], True)
    assert report['status'] == 'failed' and not report['advisories']


def test_compact_feedback_preserves_all_findings_without_raw_geometry():
    data = {'overflow_count': 1, 'low_contrast_count': 1, 'low_contrast_details': [{'selector': 'p', 'ratio': 2.4}],
            'graphic_geometry': [{'selector': 'panel', 'rect': {}}],
            'text_geometry': [{'selector': 'p', 'text': 'Critical qualifier', 'font_px': 14,
                               'rect': {'x': 10, 'y': 10, 'w': 100, 'h': 20}, 'typography': {'unused': 'large'}}]}
    feedback = compact_diagnostics(data)
    assert feedback['low_contrast_details'] == data['low_contrast_details']
    assert feedback['issue_counts']['repair_blocking'] == 2
    assert feedback['text_targets'][0]['text'] == 'Critical qualifier'
    assert 'graphic_geometry' not in feedback and 'typography' not in json.dumps(feedback)


def test_table_capacity_includes_last_row_and_header_competition(measure):
    source = '<style>table{width:300px;table-layout:fixed}th,td{font:14px Arial;padding:4px}</style><table><tr><th style="width:40px">Miles</th><th>Other column</th></tr><tr><td>42</td><td>Value</td></tr><tr><td>Projected 650k</td><td>0.18 target</td></tr></table>'
    before = measure(source)
    columns = before['table_capacity'][0]['columns']
    assert columns[0]['critical_text'] == 'Projected 650k'
    assert columns[0]['deficit_px'] > 0
    assert len(columns) == 2
    assert compact_diagnostics(before)['table_capacity'] == before['table_capacity']


def test_table_capacity_does_not_invent_columns_for_spans(measure):
    source = '<table><tr><th colspan="2">Group</th></tr><tr><td>First</td><td>Second</td></tr></table>'
    table = measure(source)['table_capacity'][0]
    assert table['requires_span_mapping'] and table['columns'] == []


def test_table_word_containment_uses_actual_glyph_ranges(measure):
    source = '<style>table{width:260px;table-layout:fixed}th{font:12px Arial;padding:7px 6px}</style><table><tr><th style="width:85px">DISENGAGEMENTS<br>/ 1K MI</th><th>GATE</th></tr></table>'
    before = measure(source)
    assert before['table_cell_overflow_count'] == 1
    assert before['table_cell_overflow_details'][0]['words'][0]['text'] == 'DISENGAGEMENTS'
    assert issue_counts(before)['geometry'] >= 1
    assert needs_spatial({'validity': before, 'review': QUALITY})
    wider = source.replace('width:85px', 'width:160px')
    assert measure(wider)['table_cell_overflow_count'] == 0


def test_legal_css_word_wrapping_does_not_trigger_table_containment(measure):
    source = '<style>table{width:100px;table-layout:fixed}td{font:12px Arial;overflow-wrap:anywhere;padding:4px}</style><table><tr><td>UnusuallyLongButLegallyWrappedLabel</td></tr></table>'
    assert measure(source)['table_cell_overflow_count'] == 0


def test_svg_floor_feedback_distinguishes_declaration_and_screen_pixels(measure):
    before = measure(SVG)
    limits = typography_constraints(before)
    assert limits[0]['minimum_effective_px'] == 10
    assert limits[0]['minimum_font_size_px_at_current_scale'] == 15
    assert limits[0]['current_effective_px'] == {'x': 12, 'y': 12}
    feedback = repair_feedback(before, {'attempt': 1, 'validity': before, 'review': QUALITY}, 'spatial')
    assert 'minimum_font_size_px_at_current_scale' in feedback and 'current_effective_px' in feedback


def test_typography_rejection_memory_retains_measured_sizes():
    from scripts.repair import rejection_memory
    finding = {'selector': 'text', 'minimum_effective_px': 10, 'after_px': 12,
               'after_effective_px': {'x': 9.55, 'y': 9.55}, 'reason': 'Below effective floor'}
    feedback = rejection_memory([{'attempt': 1, 'review_reasons': ['computed type compressed: ' + json.dumps([finding])]}])
    assert '9.55' in feedback and '"after_px": 12' in feedback


def test_uniform_svg_viewport_reflow_above_floor_requires_review_not_rejection(measure):
    before = measure(SVG)
    after = measure(SVG.replace('width="400"', 'width="360"'))
    audit = typography_audit(before, after)
    assert not audit['violations'] and audit['review_required']
    assert any('viewport' in warning['reason'] for warning in audit['warnings'])


def test_uniform_svg_resize_with_font_compensation_is_not_compression(measure):
    before = measure(SVG)
    after = measure(SVG.replace('width="400"', 'width="360"').replace('font-size="18"', 'font-size="20"'))
    audit = typography_audit(before, after)
    assert not audit['violations'] and audit['review_required']


@pytest.mark.parametrize('change', [lambda source: source.replace('<svg ', '<svg style="transform:scale(.9)" '),
                                    lambda source: source.replace('<svg ', '<svg preserveAspectRatio="none" ').replace('width="400"', 'width="360"')])
def test_svg_viewport_exception_does_not_allow_css_or_nonuniform_scaling(measure, change):
    assert typography_audit(measure(SVG), measure(change(SVG)))['violations']
