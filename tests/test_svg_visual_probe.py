"""Focused tests for the VLM-first SVG inspection path."""

import base64
from io import BytesIO
import json
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from app.modules.evaluators.probe_runner import ProbeRunner
from app.modules.evaluators.probe_planner_agent import ProbePlannerAgent
from app.modules.redeck.agent_repair import AgentRepair, AgentState
from app.modules.redeck.dispatcher import ReDeckWorker
from app.modules.redeck import dispatcher as dispatcher_module
from app.modules.redeck.repair_utils import (
    can_exempt_raw_figure_image_crop,
    html_image_css_crop_hints,
    issues_explicitly_request_image_crop,
)
from app.modules.redeck.html_spatial_state import (
    count_significant_issues,
    extract_html_slide_state,
    format_html_compact_state,
    significant_issue_regressions,
    stable_block_identity,
)
from app.modules.redeck.spatial_state import ContentBlock, SlideState
from app.orchestrator.eval_router import EvalRouter
from app.schemas.common import Confidence, IssueStatus, RepairAction, Severity
from app.schemas.evidence import EvidenceState
from app.schemas.extraction import SlideExtraction
from app.schemas.experiment_config import ExperimentConfig
from app.schemas.issue import FixDetail, Issue, IssueEvidence
from app.schemas.issue_types import PROBE_REGISTRY


SVG_HTML = """
<!doctype html><html><body style="margin:0;width:1280px;height:720px">
<h1>Diagram</h1>
<svg aria-label="simple flow" style="position:absolute;left:100px;top:120px"
     width="600" height="300" viewBox="0 0 600 300">
  <rect x="20" y="80" width="160" height="100" fill="#225588"/>
  <line x1="180" y1="130" x2="410" y2="130" stroke="#222" stroke-width="4"/>
  <rect x="410" y="80" width="160" height="100" fill="#882244"/>
  <text x="60" y="140" fill="white">Source</text>
  <text x="450" y="140" fill="white">Target</text>
</svg>
</body></html>
"""


def _extraction(slide_id: int) -> SlideExtraction:
    return SlideExtraction(
        slide_id=slide_id,
        slide_index=slide_id - 1,
        title=f"Slide {slide_id}",
        objects=[],
        total_text_length=0,
        total_objects=0,
    )


def test_extracts_generic_svg_region_inventory():
    state = extract_html_slide_state(1, SVG_HTML)

    assert len(state.svg_regions) == 1
    region = state.svg_regions[0]
    assert region["aria_label"] == "simple flow"
    assert region["primitive_count"] == 5
    assert region["connector_count"] == 1
    assert region["width"] == 600
    assert region["height"] == 300
    assert region["view_box"] == {"x": 0, "y": 0, "width": 600, "height": 300}
    assert region["view_box_source"] == "viewBox"
    metrics = {item["label"]: item for item in region["text_metrics"]}
    assert set(metrics) == {"Source", "Target"}
    assert metrics["Source"]["svg_bbox"]["x"] >= 60
    assert metrics["Source"]["nearest_rect"]["bbox"] == {
        "x": 20, "y": 80, "width": 160, "height": 100,
    }
    assert metrics["Source"]["nearest_rect"]["distance_px"] == 0
    assert metrics["Target"]["nearest_line"]["endpoints"] == {
        "x1": 180, "y1": 130, "x2": 410, "y2": 130,
    }
    assert region["stroke_text_candidates"] == []


def test_svg_region_inventory_surfaces_stroke_text_attention_candidates():
    crossing = SVG_HTML.replace(
        'x1="180" y1="130" x2="410" y2="130"',
        'x1="20" y1="130" x2="570" y2="130"',
    )

    state = extract_html_slide_state(1, crossing)

    candidates = state.svg_regions[0]["stroke_text_candidates"]
    assert {candidate["label"] for candidate in candidates} == {
        "Source", "Target",
    }
    assert all(candidate["stroke_tag"] == "line" for candidate in candidates)


def test_svg_region_text_metrics_expose_viewbox_escape_and_nearest_geometry():
    overflowing = SVG_HTML.replace(
        '<text x="450" y="140" fill="white">Target</text>',
        '<text x="590" y="140" fill="white">Target</text>',
    )

    state = extract_html_slide_state(1, overflowing)

    target = next(
        item for item in state.svg_regions[0]["text_metrics"]
        if item["label"] == "Target"
    )
    assert target["viewbox_edge_gaps"]["right"] < 0
    assert target["nearest_rect"]["bbox"] == {
        "x": 410, "y": 80, "width": 160, "height": 100,
    }
    assert target["nearest_line"]["endpoints"] == {
        "x1": 180, "y1": 130, "x2": 410, "y2": 130,
    }


def test_b20_probe_is_registered_as_vlm_spatial_probe():
    probe = PROBE_REGISTRY["B20"]
    assert probe.name == "svg_visual_defect"
    assert probe.requires_vision is True
    assert probe.requires_spatial is True
    assert probe.residual_categories == frozenset({"svg_text_overflow"})


def test_b20_prompt_requires_full_slide_reportability():
    prompt_path = (
        Path(__file__).parent.parent
        / "app/prompts/probes/B20_svg_visual_quality.md"
    )
    prompt = prompt_path.read_text()
    normalized_prompt = " ".join(prompt.split())

    assert "Reportability threshold" in prompt
    assert "clearly visible in the full-slide image" in prompt
    assert "magnified micro-gap" in prompt
    assert "Role inventory" in prompt
    assert "Ownership and accommodation" in prompt
    assert "Nested-boundary disambiguation" in prompt
    assert "Relationship tracing" in prompt
    assert "Layering legality" in prompt
    assert "Continuity conflicts" in prompt
    assert "Attachment-zone separation" in prompt
    assert "Glyph-field isolation" in prompt
    assert "Local competition" in prompt
    assert "Stress-zone audit" in prompt
    assert "Boundary-transition audit" in prompt
    assert "Minimum-clearance audit" in prompt
    assert "Alternative-reading test" in prompt
    assert "Calibration examples — non-exhaustive" in prompt
    assert "Do not search only for these objects" in normalized_prompt
    assert "Mandatory decision trace" in prompt
    assert '"narrowest_clearance"' in prompt
    assert '"nested_boundaries"' in prompt
    assert '"highest_role_convergence"' in prompt
    assert '"continuity_crossings"' in prompt
    assert '"attachment_zones"' in prompt
    assert "required even when `issues` is empty" in prompt
    assert "perceptual roles, not SVG tags" in prompt
    assert "actual shape, not only an axis-aligned bounding box" in normalized_prompt
    assert "topmost" in prompt
    assert "same pixels support another comparably plausible reading" in normalized_prompt
    assert "coordinate intersection is not a FAIL" in prompt
    assert "readable words, or traceable topology as a waiver" in normalized_prompt
    assert "Different colors alone do not resolve" in prompt

    # The normative contract must encode visual mechanisms. Concrete primitive
    # examples are allowed only in the explicitly non-exhaustive calibration
    # section, never as core rules or a preferred repair recipe.
    normative_prompt = prompt.split("## Calibration examples", 1)[0]
    for fixture_term in (
        "decorative halo", "parking band", "port gaps", "narrower chord",
        "unbroken enclosing", "circle or ellipse",
    ):
        assert fixture_term not in normative_prompt


def test_probe_runner_includes_each_rubric_once():
    runner = ProbeRunner(MagicMock(), ExperimentConfig(run_id="rubric_once"))
    prompt = runner._build_system_prompt(PROBE_REGISTRY["B20"])

    assert prompt.count("# B20: SVG Visual Integrity") == 1


def test_geometry_critic_is_an_independent_counterfactual_review():
    from app.orchestrator.eval_router import _SVG_GEOMETRY_CRITIC_PROMPT
    normalized_critic = " ".join(_SVG_GEOMETRY_CRITIC_PROMPT.split())

    assert "perceptual-ambiguity critic" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Structure without semantics" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Nested-boundary challenge" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Local interpretation" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Removal counterfactual" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Continuity collision" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Attachment-zone challenge" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Junction isolation" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Peer substitution" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "Materiality and falsification" in _SVG_GEOMETRY_CRITIC_PROMPT
    assert "state both" in normalized_critic
    assert "do not restate them" in _SVG_GEOMETRY_CRITIC_PROMPT

    for fixture_term in ("halo", "ring", "pill", "port gap", "circle"):
        assert not re.search(
            rf"\b{re.escape(fixture_term)}\b",
            _SVG_GEOMETRY_CRITIC_PROMPT.lower(),
        )


def test_html_repair_contract_uses_outcome_constraints_not_fixture_rules():
    prompt_path = (
        Path(__file__).parent.parent
        / "app/prompts/codegen/slide_html_repair.system.md"
    )
    prompt = prompt_path.read_text()

    assert "declare the visible role model" in prompt
    assert "Repair the perceptual failure, not a named primitive" in prompt
    assert "roles distinguishable" in prompt
    assert "relationships with clear source-to-target paths" in prompt
    assert "no technique or operation order is mandatory" in prompt
    assert "local competition is lower" in prompt
    assert "protected information and untouched regions have not regressed" in prompt
    assert "RELATION MAP" in prompt
    assert "there is no universal minimum move" in prompt
    assert "moves ≥80px" not in prompt
    assert "Create deliberate port gaps" not in prompt
    assert "narrower chord available" not in prompt
    assert "unbroken enclosing halo" not in prompt
    assert "M5" not in prompt
    assert "performance + efficiency" not in prompt


def test_deterministic_findings_are_framed_as_measurements():
    block = ContentBlock(
        block_id="low", var_name="span", shape_type="textbox",
        css_selector=".subtitle", text_lines=["Existing subtitle"],
        text_chars=17, font_size_px=13, font_size_pt=9.75,
        contrast_ratio=3.0, fg_color="rgb(120,120,120)",
        bg_color="rgb(255,255,255)", bbox_px=(20, 20, 200, 30),
    )
    state = SlideState(
        slide_id=1, blocks=[block], low_contrast_blocks=["low"],
    )

    compact = format_html_compact_state(state)

    assert "DETERMINISTIC FINDINGS" in compact
    assert "unchanged baseline findings are not additional repair tasks" in compact
    assert "ISSUES TO FIX" not in compact


def test_vlm_first_does_not_emit_deterministic_issues_by_default():
    config = ExperimentConfig(run_id="vlm_first")

    assert config.eval_mode.emit_deterministic_issues is False


def test_explicit_raw_figure_crop_is_a_target_not_a_regression():
    crop_issue = Issue(
        issue_id="b17", rubric_id="B17", issue_type="raw_figure",
        severity=Severity.MAJOR, affected_slides=[1],
        evidence=IssueEvidence(
            description="The image includes an uncropped source-page strip.",
        ),
        planned_fix="Crop the image to the actual photo content.",
    )
    generic_raw_figure = Issue(
        issue_id="b17b", rubric_id="B17", issue_type="raw_figure",
        severity=Severity.MINOR, affected_slides=[1],
        evidence=IssueEvidence(
            description="The figure needs a clearer annotation hierarchy.",
        ),
    )

    assert issues_explicitly_request_image_crop([crop_issue])
    assert not issues_explicitly_request_image_crop([generic_raw_figure])
    assert can_exempt_raw_figure_image_crop(
        [crop_issue],
        '<img src="real_excerpt.png" style="object-fit:contain">',
    )
    assert not can_exempt_raw_figure_image_crop(
        [crop_issue],
        '<style>.figure img{object-view-box:inset(0 34% 42% 0);object-fit:fill}</style>',
    )


def test_raw_figure_css_crop_hints_catch_windowing_patterns():
    html = """
    <style>
      .figure img {
        object-fit: cover;
        object-position: -120px top;
        transform: scale(1.2);
      }
      .alternate img { object-view-box: inset(0 34% 42% 0); }
    </style>
    <img src="source_pack/figures/fig.png" style="clip-path: inset(0 10% 0 0)">
    """

    hints = html_image_css_crop_hints(html)

    assert "object-view-box" in hints
    assert "object-fit cover/none" in hints
    assert "negative object-position" in hints
    assert "image transform scale" in hints
    assert "inline image clip" in hints


def test_verify_layout_surfaces_submit_gate_regressions(monkeypatch):
    before = SlideState(slide_id=1, blocks=[])
    overflow = ContentBlock(
        block_id="new_overflow", var_name="div", shape_type="textbox",
        css_selector=".labels", text_lines=["Dimension label"],
        text_chars=15, bbox_px=(900, 650, 260, 80),
        is_overflowing=True, overflow_bottom_px=20,
    )
    after = SlideState(
        slide_id=1, blocks=[overflow], overflow_blocks=["new_overflow"],
    )
    states = iter([after, before])
    monkeypatch.setattr(
        "app.modules.redeck.html_spatial_state.extract_html_slide_state",
        lambda *_args, **_kwargs: next(states),
    )
    agent = AgentRepair(llm=MagicMock())
    agent._current_issues = [Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[1],
    )]
    state = AgentState(
        original_code="<html>before</html>",
        current_code="<html>after</html>",
        checkpoints=["<html>before</html>"],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )

    output, _ = agent._tool_verify_layout(state)

    assert "new deterministic regression" in output
    assert "NEW TEXT_OVERFLOW" in output
    assert "Dimension label" in output


def test_verify_layout_surfaces_external_svg_asset_text_overflow(tmp_path):
    run_dir = tmp_path / "run"
    asset_dir = run_dir / "turn_00" / "generated_assets"
    asset_dir.mkdir(parents=True)
    (asset_dir / "summary.svg").write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 90">
          <g>
            <rect x="20" y="24" width="120" height="34" fill="#eef"/>
            <text x="80" y="46" text-anchor="middle" font-size="15">Parietal-occipital propagation</text>
          </g>
        </svg>
        """,
        encoding="utf-8",
    )
    html = """
    <!doctype html><html><body style="margin:0;width:1280px;height:720px">
      <img src="../generated_assets/summary.svg" style="position:absolute;left:80px;top:90px;width:360px;height:180px;object-fit:contain">
    </body></html>
    """
    agent = AgentRepair(llm=MagicMock())
    agent._current_issues = [Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[1],
    )]
    state = AgentState(
        original_code=html,
        current_code=html,
        checkpoints=[html],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=str(tmp_path),
        _run_dir=str(run_dir),
        _turn_index=0,
    )

    output, _ = agent._tool_verify_layout(state)

    assert "SVG ASSET TEXT OVERFLOW" in output
    assert "target-category deterministic measurement" in output
    assert "SVG_TEXT_OVERFLOW summary.svg" in output


def test_verify_layout_does_not_checkpoint_raw_figure_css_crop(monkeypatch):
    before = SlideState(slide_id=1, blocks=[])
    after = SlideState(slide_id=1, blocks=[])
    states = iter([after, before])
    monkeypatch.setattr(
        "app.modules.redeck.html_spatial_state.extract_html_slide_state",
        lambda *_args, **_kwargs: next(states),
    )
    agent = AgentRepair(llm=MagicMock())
    agent._current_issues = [Issue(
        issue_id="b17", rubric_id="B17", issue_type="raw_figure",
        severity=Severity.MAJOR, affected_slides=[1],
        planned_fix="Crop the dense paper figure to the relevant panel.",
    )]
    state = AgentState(
        original_code='<html><body><img src="fig.png"></body></html>',
        current_code=(
            '<html><head><style>'
            '.figure img{object-view-box:inset(0 34% 42% 0);object-fit:fill}'
            '</style></head><body><div class="figure"><img src="fig.png"></div></body></html>'
        ),
        checkpoints=['<html><body><img src="fig.png"></body></html>'],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )

    output, _ = agent._tool_verify_layout(state)

    assert "RAW-FIGURE CSS CROP WARNING" in output
    assert "object-view-box" in output
    assert state.last_verified_code is None


def test_crop_image_tool_writes_real_excerpt_asset(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (120, 90), (20, 40, 60)).save(source)
    run_dir = tmp_path / "run"
    agent = AgentRepair(llm=MagicMock())
    state = AgentState(
        original_code="<html></html>",
        current_code="<html></html>",
        checkpoints=["<html></html>"],
        slide_id=9,
        codegen_compiler=MagicMock(),
        case_dir=str(tmp_path),
    )
    state._run_dir = str(run_dir)
    state._turn_index = 3

    output, changed = agent._tool_crop_image({
        "src": str(source),
        "bbox_px": [10, 15, 70, 65],
        "output_name": "slide09_fig4_excerpt.png",
    }, state)

    out_path = run_dir / "turn_03" / "generated_assets" / "slide09_fig4_excerpt.png"
    assert not changed
    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.size == (60, 50)
    assert str(out_path) in output
    assert "object-fit: contain" in output

    pct_output, pct_changed = agent._tool_crop_image({
        "src": str(source),
        "bbox_pct": [0.25, 0.2, 0.75, 0.8],
        "output_name": "slide09_fig4_pct_excerpt.png",
    }, state)

    pct_out_path = run_dir / "turn_03" / "generated_assets" / "slide09_fig4_pct_excerpt.png"
    assert not pct_changed
    assert pct_out_path.exists()
    with Image.open(pct_out_path) as img:
        assert img.size == (60, 54)
    assert str(pct_out_path) in pct_output


def test_crop_image_resolves_wrong_run_prefixed_source_pack_path(tmp_path):
    case_dir = tmp_path / "case"
    source_dir = case_dir / "source_pack" / "figures"
    source_dir.mkdir(parents=True)
    source = source_dir / "fig_p7_fig4.png"
    Image.new("RGB", (100, 80), (80, 100, 120)).save(source)
    wrong_run_src = tmp_path / "run" / "source_pack" / "figures" / source.name

    agent = AgentRepair(llm=MagicMock())
    state = AgentState(
        original_code="<html></html>",
        current_code="<html><body><img src='missing.png'></body></html>",
        checkpoints=["<html></html>"],
        slide_id=9,
        codegen_compiler=MagicMock(),
        case_dir=str(case_dir),
    )

    output, changed = agent._tool_crop_image({
        "src": str(wrong_run_src),
        "bbox_px": [10, 10, 60, 60],
        "output_name": "resolved_crop.png",
    }, state)

    assert not changed
    assert "resolved_crop.png" in output
    assert str(source) in output
    assert (case_dir / "repair_assets" / "resolved_crop.png").exists()


def test_compose_image_grid_tool_writes_real_recomposed_asset(tmp_path):
    source = tmp_path / "source.png"
    img = Image.new("RGB", (220, 140), "white")
    for x in range(0, 100):
        for y in range(0, 50):
            img.putpixel((x, y), (200, 40, 40))
    for x in range(110, 220):
        for y in range(70, 140):
            img.putpixel((x, y), (40, 80, 200))
    img.save(source)

    run_dir = tmp_path / "run"
    agent = AgentRepair(llm=MagicMock())
    state = AgentState(
        original_code="<html></html>",
        current_code="<html></html>",
        checkpoints=["<html></html>"],
        slide_id=9,
        codegen_compiler=MagicMock(),
        case_dir=str(tmp_path),
    )
    state._run_dir = str(run_dir)
    state._turn_index = 2

    output, changed = agent._tool_compose_image_grid({
        "src": str(source),
        "bboxes_px": [[0, 0, 100, 50], [110, 70, 220, 140]],
        "layout": "vertical",
        "padding_px": 10,
        "gap_px": 6,
        "target_width_px": 320,
        "output_name": "slide09_fig4_recomposed.png",
    }, state)

    out_path = run_dir / "turn_02" / "generated_assets" / "slide09_fig4_recomposed.png"
    assert not changed
    assert out_path.exists()
    with Image.open(out_path) as composed:
        assert composed.size == (130, 146)
    assert "panels=2" in output
    assert "object-fit: contain" in output


def test_chart_generator_pillow_fallback_when_matplotlib_missing(monkeypatch, tmp_path):
    import builtins

    from app.modules.chart_generator import ChartGenerator

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError("blocked in test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out_path = tmp_path / "fallback_chart.png"
    result = ChartGenerator().generate_chart({
        "chart_type": "column_clustered",
        "title": "Accuracy",
        "categories": ["A", "B"],
        "series": [{"name": "score", "values": [0.7, 0.9]}],
    }, out_path)

    assert result == out_path
    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.size == (1600, 900)


def test_translucent_svg_panel_background_is_alpha_composited():
    html = """
    <html><body style="margin:0;width:1280px;height:720px;background:#102e35">
      <div style="position:absolute;left:80px;top:80px;width:600px;height:300px;
                  background:rgba(62,164,170,0.08)">
        <svg width="600" height="300">
          <text x="40" y="80" font-size="16" fill="#f5f8f7">
            High contrast chart label
          </text>
        </svg>
      </div>
    </body></html>
    """

    state = extract_html_slide_state(1, html)
    label = next(
        block for block in state.blocks
        if block.is_svg_text
        and block.text_lines == ["High contrast chart label"]
    )

    assert label.bg_color != "rgb(62,164,170)"
    assert label.contrast_ratio >= 4.5
    assert label.block_id not in state.low_contrast_blocks


def test_dom_residual_backstop_is_declared_by_issue_contract():
    assert PROBE_REGISTRY["B03"].residual_categories == frozenset({
        "overlap", "occlusion",
    })
    assert PROBE_REGISTRY["B04"].residual_categories == frozenset({
        "text_overflow", "svg_text_overflow", "clipped", "canvas_truncation",
    })
    assert PROBE_REGISTRY["B20"].residual_categories == frozenset({
        "svg_text_overflow",
    })

    agent = AgentRepair(llm=MagicMock())
    agent._current_issues = [Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[1],
    )]
    assert agent._targeted_residual_categories() == {"svg_text_overflow"}
    scoped = agent._scope_spatial_context(
        "SLIDE 1\nDETERMINISTIC FINDINGS (1):\n❌ OVERLAP: old noise\n"
        "📐 LAYOUT ANCHOR (1 elements):\n  svg: (100,120) 600×300px\n"
        "RELATION MAP\n  No candidate peers.\n"
        "SPACE MAP\n....",
        agent._current_issues,
    )
    assert "old noise" not in scoped
    assert "regression guards" in scoped
    assert "LAYOUT ANCHOR" in scoped
    assert "RELATION MAP" not in scoped
    assert "SPACE MAP" not in scoped

    inline_scoped = agent._scope_spatial_context(
        "SLIDE 1\nDETERMINISTIC FINDINGS (2):\n"
        "❌ OVERLAP: unrelated baseline noise\n"
        "❌ SVG TEXT OVERFLOW: \"(deep-water Atlantic)\"\n"
        "   scrollHeight: 25px | clientHeight: 15px | overflow: 10px vertical\n"
        "   scrollWidth: 99px | clientWidth: 99px | overflow: 0px horizontal\n"
        "   font-size: 10px | bbox: (1039, 288, 99×25) px\n"
        "📐 LAYOUT ANCHOR (1 elements):\n  text: (1039,288) 99×25px\n"
        "RELATION MAP\n  No candidate peers.\nSPACE MAP\n....",
        agent._current_issues,
    )
    assert "SVG TEXT-FIT TARGETS" in inline_scoped
    assert "10px vertical" in inline_scoped
    assert "0px horizontal" in inline_scoped
    assert "unrelated baseline noise" not in inline_scoped


def test_inline_svg_text_overflow_uses_svg_residual_category():
    from app.modules.redeck.html_spatial_state import count_significant_issues
    from app.modules.redeck.spatial_state import ContentBlock, SlideState

    label = ContentBlock(
        block_id="blk_31",
        var_name="text",
        shape_type="textbox",
        css_selector="text",
        text_chars=21,
        text_lines=["(deep-water Atlantic)"],
        is_svg_text=True,
        is_in_svg=True,
        overflow_bottom_px=10,
        overflow_right_px=0,
        bbox_px=(1039, 288, 99, 25),
        client_w_px=99,
        client_h_px=15,
        scroll_w_px=99,
        scroll_h_px=25,
        font_size_px=10,
    )
    state = SlideState(
        slide_id=1,
        blocks=[label],
        overflow_blocks=[label.block_id],
    )

    significant = count_significant_issues(state)

    assert significant["svg_text_overflow"] == [label.block_id]
    assert significant["text_overflow"] == []


def test_alignment_issue_keeps_neutral_geometry_and_distribution_only():
    issues = [Issue(
        issue_id="b13", rubric_id="B13",
        issue_type="alignment_inconsistency",
        severity=Severity.MAJOR, affected_slides=[1],
    )]
    compact = (
        "SLIDE 1\nDETERMINISTIC FINDINGS (1):\n"
        "❌ OVERLAP: unrelated baseline noise\n"
        "📐 LAYOUT ANCHOR (2 elements):\n"
        "  div .card-a: (80,170) 340×220px\n"
        "  div .card-b: (470,185) 340×220px\n"
        "RELATION MAP\n"
        "  R1 row peers: bottom spread=15px\n"
        "SPACE MAP\n|####....|\nCoverage: 50%"
    )

    scoped = AgentRepair._scope_spatial_context(compact, issues)

    assert "unrelated baseline noise" not in scoped
    assert "LAYOUT ANCHOR" in scoped
    assert ".card-a" in scoped
    assert "RELATION MAP" in scoped
    assert "hypotheses, not verdicts" in scoped
    assert "ALIGNMENT REVIEW" in scoped
    assert "SPACE MAP" in scoped
    assert "cannot prove edge alignment" in scoped


def test_content_issue_does_not_receive_visual_geometry_layers():
    issues = [Issue(
        issue_id="d01", rubric_id="D01", issue_type="incorrect_claim",
        severity=Severity.MAJOR, affected_slides=[1],
    )]
    compact = (
        "SLIDE 1\nDETERMINISTIC FINDINGS (1):\n"
        "❌ OVERLAP: unrelated baseline noise\n"
        "📐 LAYOUT ANCHOR (1 elements):\n  div: (80,170) 340×220px\n"
        "RELATION MAP\n  R1 row peers\n"
        "SPACE MAP\n|####....|"
    )

    scoped = AgentRepair._scope_spatial_context(compact, issues)

    assert "unrelated baseline noise" not in scoped
    assert "LAYOUT ANCHOR" not in scoped
    assert "RELATION MAP" not in scoped
    assert "SPACE MAP" not in scoped


def test_dom_owned_issue_keeps_complete_spatial_report():
    issues = [Issue(
        issue_id="b03", rubric_id="B03", issue_type="overlap",
        severity=Severity.MAJOR, affected_slides=[1],
    )]
    compact = (
        "SLIDE 1\nDETERMINISTIC FINDINGS (1):\n"
        "❌ OVERLAP: target pair\n"
        "📐 LAYOUT ANCHOR (2 elements):\n  div: (80,170) 340×220px\n"
        "RELATION MAP\n  R1 row peers\n"
        "SPACE MAP\n|####....|"
    )

    assert AgentRepair._scope_spatial_context(compact, issues) == compact


def test_b20_encodes_full_slide_then_enlarged_svg_crop(tmp_path):
    image_path = tmp_path / "slide.png"
    Image.new("RGB", (2560, 1440), "white").save(image_path)
    state = SimpleNamespace(svg_regions=[{
        "x": 100, "y": 120, "width": 600, "height": 300,
    }])

    encoded = ProbeRunner._encode_slide_images(
        [1], [_extraction(1)], [str(image_path)],
        probe_id="B20", spatial_signals={1: state},
    )

    assert len(encoded) == 3
    crop_bytes = base64.b64decode(encoded[1].split(",", 1)[1])
    with Image.open(BytesIO(crop_bytes)) as crop:
        assert max(crop.size) >= 1200
    detail_bytes = base64.b64decode(encoded[2].split(",", 1)[1])
    with Image.open(BytesIO(detail_bytes)) as detail:
        assert detail.width > detail.height


def test_router_runs_b20_only_for_slides_with_svg_regions():
    router = object.__new__(EvalRouter)
    router.svg_visual_probe = MagicMock()
    router.svg_visual_probe.run_probe.return_value = []
    states = {
        1: SimpleNamespace(svg_regions=[]),
        2: SimpleNamespace(svg_regions=[{
            "x": 10, "y": 10, "width": 200, "height": 100,
            "primitive_count": 20, "connector_count": 4,
        }]),
    }

    issues = router._run_svg_visual_probes(
        extractions=[_extraction(1), _extraction(2)],
        png_paths=["slide_01.png", "slide_02.png"],
        spatial_signals=states,
        previous_issues=None,
        modified_slides=None,
        turn_index=0,
        already_evaluated_slides=None,
    )

    assert issues == []
    assert router.svg_visual_probe.run_probe.call_count == 2
    for call in router.svg_visual_probe.run_probe.call_args_list:
        args, _ = call
        assert args[0] == "B20"
        assert args[1] == [2]
    assert router.svg_visual_probe.run_probe.call_args_list[1].kwargs["prompt_variant"] == "geometry_critic"


def test_visual_judge_does_not_receive_b20_previous_issues():
    ordinary = Issue(
        issue_id="b3", rubric_id="B03", issue_type="element_overlap",
        severity=Severity.MINOR, affected_slides=[2],
    )
    focused = Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MINOR, affected_slides=[2],
        source_probe_id="probe_B20",
    )

    assert EvalRouter._visual_judge_previous_issues([ordinary, focused]) == [ordinary]
    assert EvalRouter._visual_judge_previous_issues([focused]) is None


def test_generic_svg_issue_does_not_suppress_focused_b20_probe():
    generic = Issue(
        issue_id="generic", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MINOR, affected_slides=[3],
        source_probe_id="VisualJudge_B20",
    )
    primary = generic.model_copy(update={
        "issue_id": "primary",
        "affected_slides": [4],
        "source_probe_id": "probe_B20",
    })
    critic = generic.model_copy(update={
        "issue_id": "critic",
        "affected_slides": [5],
        "source_probe_id": "probe_B20_geometry_critic",
    })

    assert EvalRouter._svg_probe_evaluated_slides([generic, primary, critic]) == {4, 5}
    assert EvalRouter._retain_probe_owned_svg_issues(
        [generic, primary, critic]
    ) == [primary, critic]


def test_b20_parser_normalizes_null_fix_detail_strings():
    detail = ProbeRunner._parse_fix_detail({
        "correct_content": None,
        "source_ref": None,
        "target_location": "diagram endpoint",
        "action_type": 3,
    })

    assert detail.correct_content == ""
    assert detail.source_ref == ""
    assert detail.target_location == "diagram endpoint"
    assert detail.action_type == ""


def test_persisted_b20_does_not_escalate_to_full_slide_regen(monkeypatch):
    runner = object.__new__(ProbeRunner)
    previous = Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[8], persisted_turns=1,
        planned_fix="Reroute the connector.",
    )
    probe = PROBE_REGISTRY["B20"]
    monkeypatch.setattr(
        runner,
        "_format_prev_issues_for_triage",
        lambda *args, **kwargs: "",
    )
    monkeypatch.setattr(runner, "_build_user_content", lambda *args, **kwargs: "")
    runner.config = SimpleNamespace(
        models=SimpleNamespace(get_model=lambda *_: "gpt-5.5")
    )
    runner.llm = MagicMock()
    runner.llm.call_vision.return_value = json.dumps({
        "previous_issue_verdicts": [{
            "issue_id": "b20",
            "verdict": "PERSISTED",
            "reasoning": "The line still crosses the label.",
        }]
    })

    result = runner._triage_previous(
        probe, "prompt", [previous], [8], [_extraction(8)],
        ["slide_08.png"], None, "", None, None, None, 2,
    )

    assert result[0].persisted_turns == 2
    assert "NEEDS_REGEN" not in result[0].planned_fix
    triage_prompt = runner.llm.call_vision.call_args.kwargs["text_content"]
    assert "previous issue as a hypothesis" in triage_prompt
    assert "bounding-box intersection is only an attention hint" in triage_prompt
    assert "return RESOLVED even when metadata still lists a candidate" in triage_prompt


def test_primary_triages_history_but_critic_rechecks_fresh_pixels():
    router = object.__new__(EvalRouter)
    router.svg_visual_probe = MagicMock()
    router.svg_visual_probe.run_probe.side_effect = [[], []]
    generic = Issue(
        issue_id="generic", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MINOR, affected_slides=[6],
        source_probe_id="VisualJudge_B20",
    )
    primary = generic.model_copy(update={
        "issue_id": "primary", "source_probe_id": "probe_B20",
    })
    critic = generic.model_copy(update={
        "issue_id": "critic", "source_probe_id": "probe_B20_geometry_critic",
    })
    state = SimpleNamespace(svg_regions=[{
        "x": 10, "y": 10, "width": 200, "height": 100,
        "primitive_count": 20, "connector_count": 4,
    }])

    router._run_svg_visual_probes(
        extractions=[_extraction(6)],
        png_paths=["slide_06.png"],
        spatial_signals={6: state},
        previous_issues=[generic, primary, critic],
        modified_slides=None,
        turn_index=1,
    )

    calls = router.svg_visual_probe.run_probe.call_args_list
    assert calls[0].kwargs["previous_issues"] == [primary]
    assert calls[1].kwargs["previous_issues"] is None


def test_router_runs_geometry_critic_when_primary_finds_issue():
    router = object.__new__(EvalRouter)
    router.svg_visual_probe = MagicMock()
    primary = Issue(
        issue_id="primary", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MINOR, confidence=Confidence.HIGH,
        affected_slides=[4], evidence=IssueEvidence(description="Broken endpoint."),
        planned_fix="Attach the endpoint.",
    )
    router.svg_visual_probe.run_probe.side_effect = [[primary], []]
    state = SimpleNamespace(svg_regions=[{
        "x": 10, "y": 10, "width": 200, "height": 100,
        "primitive_count": 20, "connector_count": 4,
    }])

    issues = router._run_svg_visual_probes(
        extractions=[_extraction(4)],
        png_paths=["slide_04.png"],
        spatial_signals={4: state},
        previous_issues=None,
        modified_slides=None,
        turn_index=0,
        already_evaluated_slides=None,
    )

    assert issues == [primary]
    assert router.svg_visual_probe.run_probe.call_count == 2
    critic_suffix = router.svg_visual_probe.run_probe.call_args_list[1].kwargs[
        "system_prompt_suffix"
    ]
    assert "Broken endpoint." in critic_suffix


def test_geometry_critic_duplicate_target_is_suppressed():
    router = object.__new__(EvalRouter)
    primary = Issue(
        issue_id="primary", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MINOR, affected_slides=[4],
        evidence=IssueEvidence(description="A connector crosses the gauge."),
        fix_detail=FixDetail(target_location="right instrument gauge"),
    )
    critic = primary.model_copy(update={
        "issue_id": "critic",
        "source_probe_id": "probe_B20_geometry_critic",
    })

    assert router._merge_svg_probe_findings([primary], [critic]) == [primary]


def test_geometry_critic_additional_target_is_aggregated_per_slide():
    router = object.__new__(EvalRouter)
    primary = Issue(
        issue_id="primary", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MINOR, affected_slides=[4],
        evidence=IssueEvidence(description="A connector crosses an enclosure."),
        why_this_fails="The attachment zone is fused.",
        planned_fix="Separate the connector from the enclosure.",
    )
    critic = Issue(
        issue_id="critic", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MINOR, affected_slides=[4],
        evidence=IssueEvidence(description="A scaffold crosses the same focus."),
        why_this_fails="The supporting contour remains continuous.",
        planned_fix="Keep the scaffold visually behind the focus.",
        source_probe_id="probe_B20_geometry_critic",
    )

    merged = router._merge_svg_probe_findings([primary], [critic])

    assert merged == [primary]
    assert "Independent critic also confirmed" in primary.evidence.description
    assert "A scaffold crosses the same focus." in primary.evidence.description
    assert "Additional mechanism" in primary.why_this_fails
    assert "Also preserve this result" in primary.planned_fix


def test_geometry_critic_gets_distinct_identity_after_primary_resolution():
    router = object.__new__(EvalRouter)
    router.svg_visual_probe = MagicMock()
    resolved = Issue(
        issue_id="B20_slide4_00", rubric_id="B20",
        issue_type="svg_visual_defect", severity=Severity.MINOR,
        affected_slides=[4], status=IssueStatus.RESOLVED,
    )
    critic = Issue(
        issue_id="B20_slide4_00", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, confidence=Confidence.HIGH,
        affected_slides=[4], evidence=IssueEvidence(description="Doubled outline."),
        planned_fix="Remove the redundant path.",
    )
    router.svg_visual_probe.run_probe.side_effect = [[resolved], [critic]]
    state = SimpleNamespace(svg_regions=[{
        "x": 10, "y": 10, "width": 200, "height": 100,
        "primitive_count": 20, "connector_count": 4,
    }])

    issues = router._run_svg_visual_probes(
        extractions=[_extraction(4)],
        png_paths=["slide_04.png"],
        spatial_signals={4: state},
        previous_issues=None,
        modified_slides=None,
        turn_index=1,
        already_evaluated_slides=None,
    )

    assert issues == [resolved, critic]
    assert critic.source_probe_id == "probe_B20_geometry_critic"
    assert critic.issue_id == "B20_slide4_00_geometry_0"
    assert router.svg_visual_probe.run_probe.call_count == 2


def test_html_repair_preview_passes_source_to_renderer(tmp_path):
    backend = MagicMock()

    def render(html, output_path):
        assert html == SVG_HTML
        Image.new("RGB", (32, 18), "white").save(output_path)
        return True

    backend.render_html_to_png.side_effect = render
    agent = AgentRepair(llm=MagicMock())
    with patch(
        "app.render_backends.playwright_backend.PlaywrightRenderBackend",
        return_value=backend,
    ):
        encoded = agent._render_slide_to_base64(SVG_HTML, SimpleNamespace())

    assert encoded
    assert backend.render_html_to_png.call_args.args[0] == SVG_HTML


def test_render_preview_tool_returns_current_slide_image():
    agent = AgentRepair(
        llm=MagicMock(), repair_config={"enable_render_preview": True},
    )
    state = SimpleNamespace(current_code=SVG_HTML)
    with patch.object(agent, "_render_slide_to_base64", return_value="YWJj"):
        result, changed = agent._execute_tool(
            {"tool": "render_preview"}, state,
        )

    assert changed is False
    assert result[0]["type"] == "image_url"
    assert result[0]["image_url"]["url"] == "data:image/png;base64,YWJj"
    assert "graph roles remain unchanged" in result[1]["text"]


def test_svg_issue_brief_keeps_endpoint_evidence_and_fix_contract():
    unique_evidence_tail = "EVIDENCE_TAIL_MUST_REACH_REPAIR_AGENT"
    unique_fix_tail = "FIX_TAIL_MUST_REACH_REPAIR_AGENT"
    issue = Issue(
        issue_id="b20-long", rubric_id="B20",
        issue_type="svg_visual_defect", severity=Severity.MAJOR,
        affected_slides=[1],
        evidence=IssueEvidence(
            description="D" * 500 + unique_evidence_tail,
        ),
        planned_fix="F" * 500 + unique_fix_tail,
    )
    agent = AgentRepair(llm=MagicMock())

    message = agent._build_initial_message(
        code=SVG_HTML,
        all_issues=[issue],
        spatial_info="",
        evidence_text="",
        must_contain=[],
        must_not=[],
        content_checklist="",
        bp_slide=None,
        viz_data=None,
        adjacent_context="",
    )

    assert unique_evidence_tail in message
    assert unique_fix_tail in message
    assert "Graph-preservation requirement" in message


def test_missing_placeholder_issue_requires_replacement_not_duplicate_insert():
    issue = Issue(
        issue_id="c04-placeholder",
        rubric_id="C04",
        issue_type="missing_entity",
        severity=Severity.MAJOR,
        affected_slides=[9],
        evidence=IssueEvidence(
            description='Slide includes placeholder text: Add: "Interpretation basis..."',
        ),
        planned_fix="Replace the placeholder add-note with a normal bullet.",
        fix_detail=FixDetail(
            correct_content="Interpretation basis: physiological plausibility is assessed against clinical EEG knowledge.",
            target_location="under the Physiological plausibility section where the placeholder Add: line appears",
            action_type="replace_text",
        ),
    )
    agent = AgentRepair(llm=MagicMock())

    message = agent._build_initial_message(
        code=SVG_HTML,
        all_issues=[issue],
        spatial_info="",
        evidence_text="",
        must_contain=[],
        must_not=[],
        content_checklist="",
        bp_slide=None,
        viz_data=None,
        adjacent_context="",
    )

    assert "MANDATORY PLACEHOLDER REPLACE" in message
    assert "Do NOT add a second copy" in message
    assert "MANDATORY INSERT" not in message


def test_agent_brief_normalizes_editorial_correct_content():
    issue = Issue(
        issue_id="c03-editorial-prefix",
        rubric_id="C03",
        issue_type="missing_evidence",
        severity=Severity.MAJOR,
        affected_slides=[10],
        evidence=IssueEvidence(
            description="Slide needs the graph-quality evidence bullet.",
        ),
        planned_fix="Add the missing graph-quality evidence.",
        fix_detail=FixDetail(
            correct_content=(
                'Add evidence bullet: "Graph-quality evidence: '
                'ROC-AUC improves."'
            ),
        ),
    )
    agent = AgentRepair(llm=MagicMock())

    message = agent._build_initial_message(
        code=SVG_HTML,
        all_issues=[issue],
        spatial_info="",
        evidence_text="",
        must_contain=[],
        must_not=[],
        content_checklist="",
        bp_slide=None,
        viz_data=None,
        adjacent_context="",
    )

    assert 'Required content: "Graph-quality evidence: ROC-AUC improves."' in message
    assert "MANDATORY INCLUDE" in message
    assert "SOURCE-VERIFIED CONTENT" in message
    assert "Add evidence bullet" not in message


def test_dispatcher_enables_visual_context_for_svg_issue(monkeypatch, tmp_path):
    captured_configs = []

    class FakeRepair:
        def __init__(self, llm, model, repair_config=None):
            captured_configs.append(repair_config or {})

        def repair(self, *args, **kwargs):
            return None

    monkeypatch.setattr(dispatcher_module, "AgentRepair", FakeRepair)
    issue = Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, confidence=Confidence.HIGH,
        affected_slides=[1], evidence=IssueEvidence(description="Broken path."),
        planned_fix="Reconnect the path.",
    )
    compiler = SimpleNamespace(slide_codes={1: SVG_HTML})
    worker = ReDeckWorker(llm=MagicMock(), model="gpt-5.5")

    repaired = worker._repair_one_slide(
        slide_id=1,
        current_code=SVG_HTML,
        issues=[issue],
        bp_slide=None,
        evidence=EvidenceState(),
        codegen_compiler=compiler,
        case_dir=str(tmp_path),
    )

    assert repaired is False
    assert captured_configs == [{"enable_render_preview": True}]


def test_dispatcher_enables_visual_context_for_b_issue_on_svg_slide(
    monkeypatch, tmp_path,
):
    captured_configs = []

    class FakeRepair:
        def __init__(self, llm, model, repair_config=None):
            captured_configs.append(repair_config or {})

        def repair(self, *args, **kwargs):
            return None

    monkeypatch.setattr(dispatcher_module, "AgentRepair", FakeRepair)
    issue = Issue(
        issue_id="b4", rubric_id="B4", issue_type="text_overflow",
        severity=Severity.MAJOR, affected_slides=[1],
        evidence=IssueEvidence(description="SVG card text is clipped."),
        planned_fix="Increase the SVG text container height.",
    )
    worker = ReDeckWorker(llm=MagicMock(), model="gpt-5.5")

    repaired = worker._repair_one_slide(
        slide_id=1,
        current_code=SVG_HTML,
        issues=[issue],
        bp_slide=None,
        evidence=EvidenceState(),
        codegen_compiler=SimpleNamespace(slide_codes={1: SVG_HTML}),
        case_dir=str(tmp_path),
    )

    assert repaired is False
    assert captured_configs == [{"enable_render_preview": True}]


def test_validation_loop_ignores_keep_recommendations():
    from scripts.verify_svg_repair_loop import _run_visual_evaluation

    keep = Issue(
        issue_id="keep", rubric_id="B15",
        issue_type="container_contract_breach",
        severity=Severity.MINOR, affected_slides=[1],
        recommended_action=RepairAction.KEEP,
    )
    patchable = Issue(
        issue_id="patch", rubric_id="B20",
        issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[1],
        recommended_action=RepairAction.PATCH,
    )
    router = MagicMock()
    router.evaluate.return_value = [keep, patchable]

    result = _run_visual_evaluation(
        router, 1, _extraction(1), MagicMock(), SVG_HTML,
    )

    assert result == [patchable]


def test_dispatcher_repairs_all_slide_issues_in_one_current_state_pass(
    monkeypatch, tmp_path,
):
    calls = []

    class FakeRepair:
        def __init__(self, llm, model, repair_config=None):
            calls.append({"config": repair_config, "issues": None})

        def repair(self, slide_id, current_code, issues, *args, **kwargs):
            calls[-1]["issues"] = [issue.issue_id for issue in issues]
            return None

    monkeypatch.setattr(dispatcher_module, "AgentRepair", FakeRepair)
    overlap = Issue(
        issue_id="b3", rubric_id="B03", issue_type="overlap",
        severity=Severity.MAJOR, affected_slides=[8],
    )
    svg = Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[8],
    )
    worker = ReDeckWorker(llm=MagicMock(), model="gpt-5.5")

    repaired = worker._repair_one_slide(
        slide_id=8,
        current_code=SVG_HTML,
        issues=[overlap, svg],
        bp_slide=None,
        evidence=EvidenceState(),
        codegen_compiler=SimpleNamespace(slide_codes={8: SVG_HTML}),
        case_dir=str(tmp_path),
    )

    assert repaired is False
    assert calls == [{
        "config": {"enable_render_preview": True},
        "issues": ["b3", "b20"],
    }]


def test_dispatcher_rejects_text_changes_from_visual_only_repair(
    monkeypatch, tmp_path,
):
    class FakeRepair:
        def __init__(self, llm, model, repair_config=None):
            pass

        def repair(self, slide_id, current_code, issues, *args, **kwargs):
            return current_code.replace("Target", "Shortened")

    monkeypatch.setattr(dispatcher_module, "AgentRepair", FakeRepair)
    issue = Issue(
        issue_id="b4", rubric_id="B04", issue_type="text_overflow",
        severity=Severity.MAJOR, affected_slides=[1],
    )
    worker = ReDeckWorker(llm=MagicMock(), model="gpt-5.5")
    compiler = SimpleNamespace(slide_codes={1: SVG_HTML})

    repaired = worker._repair_one_slide(
        slide_id=1,
        current_code=SVG_HTML,
        issues=[issue],
        bp_slide=None,
        evidence=EvidenceState(),
        codegen_compiler=compiler,
        case_dir=str(tmp_path),
    )

    assert repaired is False
    assert compiler.slide_codes[1] == SVG_HTML


def test_dispatcher_does_not_exhaust_reused_id_with_new_visual_evidence(
    monkeypatch, tmp_path,
):
    old_issue = Issue(
        issue_id="B20_slide6_00", rubric_id="B20",
        issue_type="svg_visual_defect", severity=Severity.MAJOR,
        affected_slides=[6],
        evidence=IssueEvidence(description="Two horizontal arrows lack shafts."),
        planned_fix="Redraw both horizontal arrows.",
    )
    new_issue = old_issue.model_copy(deep=True)
    new_issue.evidence.description = "The GOVERN arc crosses the central arrow."
    new_issue.planned_fix = "Separate the arc from the central arrow."
    old_target = dispatcher_module._repair_issue_fingerprint(old_issue)
    (tmp_path / "slide_issue_id_history.json").write_text(
        json.dumps({"6": [[old_target], [old_target]]}),
        encoding="utf-8",
    )

    worker = ReDeckWorker(llm=MagicMock(), model="gpt-5.5")
    repair_one = MagicMock(return_value=False)
    monkeypatch.setattr(worker, "_repair_one_slide", repair_one)

    repaired = worker.repair_slides(
        codegen_compiler=SimpleNamespace(slide_codes={6: SVG_HTML}),
        issues=[new_issue],
        blueprint_slides=[],
        evidence=EvidenceState(),
        case_dir=str(tmp_path),
        run_dir=str(tmp_path),
        turn_index=2,
    )

    assert repaired == []
    repair_one.assert_called_once()


def test_probe_issue_ids_do_not_depend_on_response_order():
    runner = object.__new__(ProbeRunner)
    probe = PROBE_REGISTRY["B20"]
    first = {
        "rubric_id": "B20",
        "issue_type": "svg_visual_defect",
        "severity": "major",
        "confidence": "high",
        "affected_slides": [3],
        "evidence": "The GOVERN to MEASURE shaft points away from its target.",
        "fix_detail": {"target_location": "GOVERN to MEASURE connector"},
    }
    second = {
        "rubric_id": "B20",
        "issue_type": "svg_visual_defect",
        "severity": "minor",
        "confidence": "high",
        "affected_slides": [4],
        "evidence": "The Decision gate outline is doubled.",
        "fix_detail": {"target_location": "Decision gate outline"},
    }

    forward = runner._parse_probe_output(
        json.dumps({"issues": [first, second]}), probe, [3, 4], 0,
    )
    reverse = runner._parse_probe_output(
        json.dumps({"issues": [second, first]}), probe, [3, 4], 0,
    )

    assert {
        issue.fix_detail.target_location: issue.issue_id for issue in forward
    } == {
        issue.fix_detail.target_location: issue.issue_id for issue in reverse
    }


def test_semantic_dedup_keeps_distinct_same_slide_svg_target():
    previous = Issue(
        issue_id="old", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[6],
        fix_detail=FixDetail(target_location="GOVERN to MEASURE connector"),
    )
    reworded_same = Issue(
        issue_id="new-same", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[6],
        fix_detail=FixDetail(
            target_location="connector linking the GOVERN and MEASURE labels",
        ),
    )
    genuinely_new = Issue(
        issue_id="new-target", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[6],
        fix_detail=FixDetail(target_location="Decision gate right border"),
    )

    deduped = ProbeRunner._dedup_new_against_triaged(
        [reworded_same, genuinely_new], [previous],
    )

    assert [issue.issue_id for issue in deduped] == ["new-target"]


def test_ephemeral_block_refs_do_not_collapse_distinct_issue_targets():
    first = Issue(
        issue_id="first", rubric_id="B4", issue_type="text_overflow",
        severity=Severity.MAJOR, affected_slides=[3],
        evidence=IssueEvidence(
            object_refs=["blk_18"], description="Revenue label is clipped.",
        ),
        fix_detail=FixDetail(target_location="Revenue chart label"),
    )
    second = Issue(
        issue_id="second", rubric_id="B4", issue_type="text_overflow",
        severity=Severity.MAJOR, affected_slides=[3],
        evidence=IssueEvidence(
            object_refs=["blk_19"], description="Footer source is clipped.",
        ),
        fix_detail=FixDetail(target_location="Footer source line"),
    )

    from app.utils.issue_identity import issues_share_target

    assert not issues_share_target(first, second)


def test_issue_identity_survives_ephemeral_block_id_change():
    first = Issue(
        issue_id="first", rubric_id="B4", issue_type="text_overflow",
        severity=Severity.MAJOR, affected_slides=[3],
        evidence=IssueEvidence(object_refs=["blk_18"]),
        fix_detail=FixDetail(target_location="Revenue chart label"),
    )
    second = first.model_copy(deep=True, update={"issue_id": "second"})
    second.evidence.object_refs = ["blk_27"]

    from app.utils.issue_identity import issues_share_target, stable_issue_id

    assert issues_share_target(first, second)
    assert stable_issue_id(first, "B4") == stable_issue_id(second, "B4")


def test_probe_planner_does_not_suppress_mandatory_focused_b20():
    previous = Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[6], persisted_turns=2,
        source_probe_id="probe_B20",
    )
    planner = object.__new__(ProbePlannerAgent)
    planner._collected_issues = []
    planner._previous_issues = [previous]
    planner._turn_index = 3

    result = planner._finalize()

    assert result == []
    assert previous.persisted_turns == 2
    assert previous.status == IssueStatus.OPEN


def test_probe_planner_semantic_dedup_preserves_distinct_targets():
    first = Issue(
        issue_id="first", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[6],
        fix_detail=FixDetail(target_location="GOVERN to MEASURE connector"),
    )
    duplicate = first.model_copy(deep=True, update={"issue_id": "duplicate"})
    distinct = first.model_copy(deep=True, update={
        "issue_id": "distinct",
        "fix_detail": FixDetail(target_location="Decision gate right border"),
    })
    planner = object.__new__(ProbePlannerAgent)
    planner._collected_issues = [first, duplicate, distinct]

    assert planner._dedup_collected() == [first, distinct]


def test_repair_target_history_exhausts_reworded_same_target(
    monkeypatch, tmp_path,
):
    from app.utils.issue_identity import issue_target_descriptor

    old = Issue(
        issue_id="old", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[6],
        fix_detail=FixDetail(target_location="GOVERN to MEASURE connector"),
        planned_fix="Move the endpoint.",
    )
    current = Issue(
        issue_id="new-wording", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[6],
        fix_detail=FixDetail(
            target_location="connector linking the GOVERN and MEASURE labels",
        ),
        planned_fix="Use a clearer final tangent.",
    )
    descriptor = issue_target_descriptor(old)
    (tmp_path / "slide_issue_id_history.json").write_text(
        json.dumps({"6": [[descriptor], [descriptor]]}), encoding="utf-8",
    )
    worker = ReDeckWorker(llm=MagicMock(), model="gpt-5.5")
    repair_one = MagicMock(return_value=False)
    monkeypatch.setattr(worker, "_repair_one_slide", repair_one)

    worker.repair_slides(
        codegen_compiler=SimpleNamespace(slide_codes={6: SVG_HTML}),
        issues=[current], blueprint_slides=[], evidence=EvidenceState(),
        case_dir=str(tmp_path), run_dir=str(tmp_path), turn_index=2,
    )

    repair_one.assert_not_called()


def test_svg_scope_guard_allows_geometry_but_rejects_semantic_changes():
    from app.modules.redeck.repair_utils import validate_svg_repair_scope

    geometry_only = SVG_HTML.replace('x2="410"', 'x2="400"').replace(
        '<line ', '<path d="M 180 130 L 400 130" ',
    )
    ok, reason = validate_svg_repair_scope(SVG_HTML, geometry_only)
    assert ok, reason

    changed_text = SVG_HTML.replace("Target", "Destination")
    ok, reason = validate_svg_repair_scope(SVG_HTML, changed_text)
    assert not ok
    assert "visible text" in reason

    changed_outer_dom = SVG_HTML.replace("<h1>Diagram</h1>", "")
    ok, reason = validate_svg_repair_scope(SVG_HTML, changed_outer_dom)
    assert not ok
    assert "visible text" in reason or "outside SVG" in reason


def test_visual_scope_guard_preserves_text_media_and_accessibility():
    from app.modules.redeck.repair_utils import validate_visual_repair_scope

    visual_html = (
        '<section aria-label="Evidence"><style>.x{left:1px}</style>'
        '<img src="chart.png" alt="Growth chart"><p>Exact claim</p></section>'
    )
    style_only = visual_html.replace("left:1px", "left:9px")
    ok, reason = validate_visual_repair_scope(visual_html, style_only)
    assert ok, reason

    changed_text = style_only.replace("Exact claim", "Short claim")
    ok, reason = validate_visual_repair_scope(visual_html, changed_text)
    assert not ok
    assert "visible text" in reason

    changed_media = style_only.replace("chart.png", "other.png")
    ok, reason = validate_visual_repair_scope(visual_html, changed_media)
    assert not ok
    assert "media references" in reason

    ok, reason = validate_visual_repair_scope(
        visual_html,
        changed_media,
        allow_image_replacement=True,
    )
    assert ok, reason

    removed_media = style_only.replace(
        '<img src="chart.png" alt="Growth chart">', "",
    )
    ok, reason = validate_visual_repair_scope(
        visual_html,
        removed_media,
        allow_image_replacement=True,
    )
    assert not ok
    assert "media references" in reason or "visible text" in reason

    changed_a11y = style_only.replace("Growth chart", "Decorative image")
    ok, reason = validate_visual_repair_scope(
        visual_html,
        changed_a11y,
        allow_image_replacement=True,
    )
    assert not ok
    assert "accessibility" in reason

    case_only = visual_html.replace("Exact claim", "Exact Claim")
    ok, reason = validate_visual_repair_scope(
        visual_html,
        case_only,
        allow_text_case_change=True,
    )
    assert ok, reason

    reworded = visual_html.replace("Exact claim", "Different claim")
    ok, reason = validate_visual_repair_scope(
        visual_html,
        reworded,
        allow_text_case_change=True,
    )
    assert not ok
    assert "visible text" in reason

    punctuation_spacing = visual_html.replace("Exact claim", "Exact claim ; Note")
    punctuation_spacing_fixed = visual_html.replace(
        "Exact claim", "exact claim; Note",
    )
    ok, reason = validate_visual_repair_scope(
        punctuation_spacing,
        punctuation_spacing_fixed,
        allow_text_formatting_change=True,
    )
    assert ok, reason

    punctuation_changed = punctuation_spacing_fixed.replace("claim;", "claim:")
    ok, reason = validate_visual_repair_scope(
        punctuation_spacing,
        punctuation_changed,
        allow_text_formatting_change=True,
    )
    assert not ok
    assert "visible text" in reason

    number_changed = punctuation_spacing_fixed.replace("Note", "Note 2")
    ok, reason = validate_visual_repair_scope(
        punctuation_spacing,
        number_changed,
        allow_text_formatting_change=True,
    )
    assert not ok
    assert "visible text" in reason


def test_multi_action_response_executes_only_first_before_feedback():
    agent = AgentRepair(llm=MagicMock())
    response = "\n".join([
        '{"tool":"plan","steps":["fix","verify"]}',
        '{"tool":"apply_edits","edits":[]}',
        '{"tool":"verify_layout","reasoning":"inspect real result"}',
        '{"tool":"apply_edits","edits":[{"search":"a","replace":"b"}]}',
        '{"tool":"submit"}',
    ])

    first = agent._parse_action(response)

    assert first["tool"] == "plan"
    assert agent._pending_actions == []
    assert agent._multi_action_ignored_count == 4


def test_multi_action_queue_does_not_skip_malformed_edit():
    agent = AgentRepair(llm=MagicMock())
    response = "\n".join([
        '{"tool":"plan","plan":{"steps":["fix"]}}',
        '{"tool":"apply_edits","edits":[]} }',
        '{"tool":"verify_layout","reasoning":"inspect real result"}',
    ])

    first = agent._parse_action(response)

    assert first["tool"] == "plan"
    assert agent._pending_actions == []


def test_multi_action_queue_stops_at_multiline_malformed_edit():
    agent = AgentRepair(llm=MagicMock())
    response = """
{
  "tool": "plan",
  "plan": {"steps": ["fix"]}
}
{
  "tool": "apply_edits",
  "edits": [{"search": "old", "replace": "new"}],
}
{
  "tool": "verify_layout",
  "reasoning": "must not run without the edit"
}
"""

    first = agent._parse_action(response)

    assert first["tool"] == "plan"
    assert agent._pending_actions == []


def test_visual_and_repair_prompts_reject_painted_image_crops():
    root = Path(__file__).parents[1]
    judge_prompt = (
        root / "app/prompts/evaluator/visual_judge.system.md"
    ).read_text(encoding="utf-8")
    repair_prompt = (
        root / "app/prompts/codegen/slide_html_repair.system.md"
    ).read_text(encoding="utf-8")

    assert "conspicuous solid-color or" in judge_prompt
    assert "pseudo-element, matching-background strip" in repair_prompt
    assert "preserve all existing visible strings" in judge_prompt
    assert "recommend KEEP" in judge_prompt


def test_visual_repair_prompt_never_allows_text_trimming():
    prompt = (
        Path(__file__).parents[1]
        / "app/prompts/codegen/slide_html_repair.system.md"
    ).read_text(encoding="utf-8")

    assert "preserve every source-visible string and every information-bearing role" in prompt
    assert "DOM order is not frozen" in prompt
    assert "shorten text by removing TRAILING words" not in prompt


def test_overflow_hidden_image_crop_is_not_text_overflow_or_overlap(tmp_path):
    image_path = tmp_path / "wide.png"
    Image.new("RGB", (400, 240), "white").save(image_path)
    html = f"""
    <html><body style="margin:0;width:1280px;height:720px;overflow:hidden">
      <div class="background" style="position:absolute;left:900px;top:0;
           width:380px;height:720px;background:#3ea4aa"></div>
      <div class="crop" style="position:absolute;left:900px;top:100px;
           width:330px;height:300px;overflow:hidden;background:#102e35">
        <img src="{image_path}" style="width:374px;height:300px;
             display:block;transform:translateX(-44px)" />
      </div>
    </body></html>
    """

    state = extract_html_slide_state(1, html)
    issues = count_significant_issues(state)

    assert issues["text_overflow"] == []
    assert issues["overlap"] == []


def test_svg_dirty_detection_tracks_only_edits_that_can_affect_svg():
    html = """
    <html><head><style>
      :root { --line: #225588; }
      .footer { height: 40px; }
    </style></head><body>
      <svg><path d="M0 0 L10 10" stroke="var(--line)"/></svg>
      <div class="decoration"></div><footer class="footer">Source</footer>
    </body></html>
    """

    assert AgentRepair._edit_may_affect_svg({"edits": [{
        "search": 'd="M0 0 L10 10"',
        "replace": 'd="M0 0 L12 10"',
    }]}, html)
    assert AgentRepair._edit_may_affect_svg({"edits": [{
        "search": "--line: #225588",
        "replace": "--line: #113344",
    }]}, html)
    assert not AgentRepair._edit_may_affect_svg({"edits": [{
        "search": '<div class="decoration"></div>',
        "replace": "",
    }]}, html)
    assert not AgentRepair._edit_may_affect_svg({"edits": [{
        "search": ".footer { height: 40px; }",
        "replace": ".footer { height: 44px; }",
    }]}, html)


def test_svg_geometry_identity_survives_sibling_deletion():
    before = """
    <html><body><svg width="600" height="300" viewBox="0 0 600 300">
      <ellipse cx="300" cy="150" rx="250" ry="120" fill="none"/>
      <ellipse cx="300" cy="150" rx="100" ry="50" fill="#ddd"/>
      <foreignObject x="240" y="120" width="120" height="60">
        <div>Stable label</div>
      </foreignObject>
    </svg></body></html>
    """
    after = before.replace(
        '<ellipse cx="300" cy="150" rx="250" ry="120" fill="none"/>',
        "",
    )
    before_state = extract_html_slide_state(1, before)
    after_state = extract_html_slide_state(1, after)
    before_inner = next(
        block for block in before_state.blocks
        if "rx=100" in block.dom_path
    )
    after_inner = next(
        block for block in after_state.blocks
        if "rx=100" in block.dom_path
    )

    assert before_inner.block_id != after_inner.block_id
    assert stable_block_identity(
        before_state, before_inner.block_id,
    ) == stable_block_identity(after_state, after_inner.block_id)


def test_html_text_identity_survives_unrelated_sibling_deletion():
    before = """
    <html><body><main>
      <section class="decoration"></section>
      <section><div class="badge">Executive Summary</div></section>
      <section><div class="caption">Stable source caption</div></section>
    </main></body></html>
    """
    after = before.replace('<section class="decoration"></section>', "")
    before_state = extract_html_slide_state(1, before)
    after_state = extract_html_slide_state(1, after)

    for label in ("Executive Summary", "Stable source caption"):
        before_block = next(
            block for block in before_state.blocks
            if block.text_lines == [label]
        )
        after_block = next(
            block for block in after_state.blocks
            if block.text_lines == [label]
        )
        assert before_block.dom_path != after_block.dom_path
        assert stable_block_identity(
            before_state, before_block.block_id,
        ) == stable_block_identity(after_state, after_block.block_id)


def test_svg_primitive_overlap_is_owned_by_visual_probe():
    card = ContentBlock(
        block_id="card", var_name="rect", shape_type="chart",
        bbox_px=(40, 80, 360, 240), text_chars=0,
    )
    label = ContentBlock(
        block_id="label", var_name="li", shape_type="chart",
        bbox_px=(80, 120, 260, 32), text_lines=["Visible card label"],
        text_chars=18,
    )
    state = SlideState(
        slide_id=1, blocks=[card, label],
        overlap_pairs=[("card", "label", 1.0)],
    )

    assert count_significant_issues(state)["overlap"] == []


def test_foreign_object_overlap_is_owned_by_visual_probe():
    left = ContentBlock(
        block_id="left", var_name="div", shape_type="chart",
        bbox_px=(40, 80, 240, 120), text_lines=["Left node"],
        text_chars=9, is_in_svg=True,
    )
    right = ContentBlock(
        block_id="right", var_name="div", shape_type="chart",
        bbox_px=(250, 80, 240, 120), text_lines=["Right node"],
        text_chars=10, is_in_svg=True,
    )
    state = SlideState(
        slide_id=1, blocks=[left, right],
        overlap_pairs=[("left", "right", 0.125)],
    )

    assert count_significant_issues(state)["overlap"] == []


def test_svg_semantic_identity_survives_geometry_repair():
    before = """
    <html><body><svg width="600" height="300" viewBox="0 0 600 300">
      <path d="M0 20 C100 0 200 0 300 20" fill="none"/>
      <foreignObject x="120" y="5" width="180" height="38">
        <div>Governance informs later functions</div>
      </foreignObject>
    </svg></body></html>
    """
    after = before.replace(
        'x="120" y="5" width="180" height="38"',
        'x="130" y="38" width="200" height="32"',
    )
    before_state = extract_html_slide_state(1, before)
    after_state = extract_html_slide_state(1, after)
    before_label = next(
        block for block in before_state.blocks
        if block.var_name.lower() == "foreignobject"
    )
    after_label = next(
        block for block in after_state.blocks
        if block.var_name.lower() == "foreignobject"
    )

    assert stable_block_identity(
        before_state, before_label.block_id,
    ) == stable_block_identity(after_state, after_label.block_id)


def test_regression_guard_ignores_overlap_to_occlusion_category_churn():
    before_blocks = [
        ContentBlock(
            block_id="before_a", var_name="span", shape_type="textbox",
            dom_path="html[0]/body[0]/span#source", text_lines=["Source"],
            text_chars=6, bbox_px=(10, 10, 100, 40),
        ),
        ContentBlock(
            block_id="before_b", var_name="span", shape_type="textbox",
            dom_path="html[0]/body[0]/span#target", text_lines=["Target"],
            text_chars=6, bbox_px=(80, 10, 100, 40),
        ),
    ]
    after_blocks = [
        ContentBlock(
            block_id="after_a", var_name="span", shape_type="textbox",
            dom_path="html[0]/body[0]/span#source", text_lines=["Source"],
            text_chars=6, bbox_px=(12, 10, 100, 40),
        ),
        ContentBlock(
            block_id="after_b", var_name="span", shape_type="textbox",
            dom_path="html[0]/body[0]/span#target", text_lines=["Target"],
            text_chars=6, bbox_px=(82, 10, 100, 40),
        ),
    ]
    before = SlideState(
        slide_id=1, blocks=before_blocks,
        overlap_pairs=[("before_a", "before_b", 0.25)],
    )
    after = SlideState(
        slide_id=1, blocks=after_blocks,
        occlusion_pairs=[("after_a", "after_b")],
    )

    assert significant_issue_regressions(before, after) == {}


def test_regression_guard_reports_a_new_physical_interaction():
    stable = ContentBlock(
        block_id="stable", var_name="span", shape_type="textbox",
        dom_path="html[0]/body[0]/span#stable", text_lines=["Stable"],
        text_chars=6, bbox_px=(10, 10, 100, 40),
    )
    old_peer = ContentBlock(
        block_id="old", var_name="span", shape_type="textbox",
        dom_path="html[0]/body[0]/span#old", text_lines=["Old"],
        text_chars=3, bbox_px=(80, 10, 100, 40),
    )
    new_peer = ContentBlock(
        block_id="new", var_name="span", shape_type="textbox",
        dom_path="html[0]/body[0]/span#new", text_lines=["New"],
        text_chars=3, bbox_px=(80, 10, 100, 40),
    )
    before = SlideState(
        slide_id=1, blocks=[stable, old_peer],
        overlap_pairs=[("stable", "old", 0.25)],
    )
    after = SlideState(
        slide_id=1, blocks=[stable, new_peer],
        occlusion_pairs=[("stable", "new")],
    )

    regressions = significant_issue_regressions(before, after)

    assert regressions == {
        "interaction": [("occlusion", ("stable", "new"))],
    }


def test_regression_guard_reports_new_interaction_despite_lower_total():
    anchor = ContentBlock(
        block_id="anchor", var_name="span", shape_type="textbox",
        dom_path="html[0]/body[0]/span#anchor", text_lines=["Anchor"],
        text_chars=6, bbox_px=(10, 10, 100, 40),
    )
    old_a = ContentBlock(
        block_id="old_a", var_name="span", shape_type="textbox",
        dom_path="html[0]/body[0]/span#old-a", text_lines=["Old A"],
        text_chars=5, bbox_px=(80, 10, 100, 40),
    )
    old_b = ContentBlock(
        block_id="old_b", var_name="span", shape_type="textbox",
        dom_path="html[0]/body[0]/span#old-b", text_lines=["Old B"],
        text_chars=5, bbox_px=(80, 50, 100, 40),
    )
    new_peer = ContentBlock(
        block_id="new_peer", var_name="span", shape_type="textbox",
        dom_path="html[0]/body[0]/span#new-peer", text_lines=["New peer"],
        text_chars=8, bbox_px=(80, 10, 100, 40),
    )
    before = SlideState(
        slide_id=1, blocks=[anchor, old_a, old_b],
        overlap_pairs=[
            ("anchor", "old_a", 0.25),
            ("anchor", "old_b", 0.25),
        ],
    )
    after = SlideState(
        slide_id=1, blocks=[anchor, old_a, old_b, new_peer],
        overlap_pairs=[("anchor", "new_peer", 0.25)],
    )

    regressions = significant_issue_regressions(before, after)

    assert regressions == {
        "interaction": [("overlap", ("anchor", "new_peer"))],
    }


def test_regression_guard_reports_new_clipped_identity_despite_lower_total():
    def clipped(block_id: str, dom_id: str) -> ContentBlock:
        return ContentBlock(
            block_id=block_id,
            var_name="div",
            shape_type="textbox",
            dom_path=f"html[0]/body[0]/div#{dom_id}",
            text_lines=[dom_id],
            text_chars=len(dom_id),
            bbox_px=(20, 20, 200, 40),
            is_clipped=True,
            clipped_bottom_px=18,
        )

    before_blocks = [
        clipped("before_a", "old-a"),
        clipped("before_b", "old-b"),
        clipped("before_c", "old-c"),
    ]
    after_blocks = [
        clipped("after_a", "old-a"),
        clipped("after_new", "new-region"),
    ]
    before = SlideState(
        slide_id=1,
        blocks=before_blocks,
        clipped_blocks=[block.block_id for block in before_blocks],
    )
    after = SlideState(
        slide_id=1,
        blocks=after_blocks,
        clipped_blocks=[block.block_id for block in after_blocks],
    )

    regressions = significant_issue_regressions(before, after)

    assert regressions == {
        "content_fit": [("clipped", "after_new")],
    }


def test_regression_guard_matches_same_dom_node_after_support_copy_compression():
    before_block = ContentBlock(
        block_id="before_note",
        var_name="div",
        shape_type="textbox",
        css_selector=".m-note",
        css_classes=("m-note",),
        dom_path="html/body/div.bottom/div.grid-card[2]/div.metric-list/div.metric[3]/div.m-note",
        text_lines=[
            "Community acceptance and curtailment can delay projects."
        ],
        text_chars=59,
        bbox_px=(360, 620, 240, 44),
        is_clipped=True,
        clipped_bottom_px=18,
    )
    after_block = ContentBlock(
        block_id="after_note",
        var_name="div",
        shape_type="textbox",
        css_selector=".m-note",
        css_classes=("m-note",),
        dom_path="html/body/div.bottom/div.grid-card[2]/div.metric-list/div.metric[3]/div.m-note",
        text_lines=["Acceptance and curtailment can delay projects."],
        text_chars=47,
        bbox_px=(360, 610, 240, 36),
        is_clipped=True,
        clipped_bottom_px=10,
    )
    before = SlideState(
        slide_id=1,
        blocks=[before_block],
        clipped_blocks=["before_note"],
    )
    after = SlideState(
        slide_id=1,
        blocks=[after_block],
        clipped_blocks=["after_note"],
    )

    assert significant_issue_regressions(before, after) == {}


def test_foreign_object_html_text_remains_a_clipping_defect():
    clipped_list_item = ContentBlock(
        block_id="html_li", var_name="li", shape_type="textbox",
        text_lines=["third-party controls"], text_chars=20,
        bbox_px=(100, 480, 266, 34), is_in_svg=True,
        is_clipped=True, clipped_bottom_px=32,
    )
    clipped_svg_path = ContentBlock(
        block_id="svg_path", var_name="path", shape_type="shape",
        bbox_px=(100, 480, 266, 34), is_in_svg=True,
        is_clipped=True, clipped_bottom_px=32,
    )
    state = SlideState(
        slide_id=1,
        blocks=[clipped_list_item, clipped_svg_path],
        clipped_blocks=["html_li", "svg_path"],
    )

    significant = count_significant_issues(state)

    assert significant["clipped"] == ["html_li"]


def test_vlm_owned_issue_uses_latest_nonregressing_checkpoint():
    changed_html = SVG_HTML.replace("#225588", "#225589")
    agent = AgentRepair(llm=MagicMock())
    agent._current_issues = [Issue(
        issue_id="b20", rubric_id="B20", issue_type="svg_visual_defect",
        severity=Severity.MAJOR, affected_slides=[1],
    )]
    state = AgentState(
        original_code=SVG_HTML,
        current_code=changed_html,
        checkpoints=[SVG_HTML],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
    )

    agent._tool_verify_layout(state)

    assert state.last_verified_code == changed_html
    assert state.best_verified_code is None
    assert state.best_verified_issues is None
