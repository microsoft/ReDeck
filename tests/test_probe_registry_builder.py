"""Tests for heading-aware probe registry extraction."""

import json
from pathlib import Path

from PIL import Image

from scripts.build_probe_registry import parse_probe_md
from app.modules.evaluators.probe_runner import ProbeRunner
from app.schemas.experiment_config import ExperimentConfig
from app.schemas.extraction import ExtractedObject, SlideExtraction
from app.schemas.issue_types import PROBE_REGISTRY


def _parse(tmp_path: Path, markdown: str) -> list[dict]:
    path = tmp_path / "probe.md"
    path.write_text(markdown, encoding="utf-8")
    return parse_probe_md(path)


def test_nested_do_not_flag_is_not_collected(tmp_path):
    checks = _parse(tmp_path, """
## Dimension
### Fail if
1. Actual defect
### Do not flag
1. Intentional hierarchy
""")

    assert [check["text"] for check in checks] == ["Actual defect"]


def test_multiple_fail_if_subtype_sections_are_collected(tmp_path):
    checks = _parse(tmp_path, """
## Fail if - alignment
1. First defect
## Notes
Ignore this.
## Fail if - spacing
1. Second defect
""")

    assert [check["text"] for check in checks] == [
        "First defect",
        "Second defect",
    ]


def test_b13_collects_spatial_contract_failures_without_exemptions():
    probe_path = (
        Path(__file__).parent.parent
        / "app" / "prompts" / "probes" / "B13_spatial_coherence.md"
    )
    texts = [check["text"] for check in parse_probe_md(probe_path)]

    assert "Repeating peer items have visibly uneven gaps that are not explained by hierarchy, content length, or grouping structure." in texts
    assert "A related element is orphaned from its logical group because it is farther from its group than comparable group members are, lacks their shared anchor, or sits outside the group boundary/proximity cue." in texts
    assert "Different logical levels using different alignment (title centered, body left-aligned)" not in texts
    assert "Single element positioned at a corner" not in texts
    assert "Deliberate indentation for hierarchy" not in texts


def test_multiline_fail_if_item_is_joined(tmp_path):
    checks = _parse(tmp_path, """
## Fail if
1. A large blank region interrupts reading order or makes a multi-part idea look
   visibly incomplete.
2. A second complete item.
""")

    assert [check["text"] for check in checks] == [
        "A large blank region interrupts reading order or makes a multi-part idea look visibly incomplete.",
        "A second complete item.",
    ]


def test_multiline_severity_item_is_joined(tmp_path):
    checks = _parse(tmp_path, """
## Severity
- critical: primary content is hidden enough that
  the slide cannot be interpreted.
- major: local content is impaired.
""")

    assert [check["text"] for check in checks] == [
        "primary content is hidden enough that the slide cannot be interpreted.",
        "local content is impaired.",
    ]


def test_b09_registry_items_are_complete():
    probe_path = (
        Path(__file__).parent.parent
        / "app" / "prompts" / "probes" / "B09_density_imbalance.md"
    )
    texts = [check["text"] for check in parse_probe_md(probe_path)]

    assert "Substantive content is clustered in a corner, edge, or narrow band while a contiguous blank region of comparable or larger visual weight has no framing, counterweight, directional role, or hierarchy function." in texts
    assert "Enlarging the element within its region would improve inspection and hierarchy without causing overlap, clipping, or loss of visible content." in texts


def test_b09_owns_clean_chart_layout_imbalance_not_b17():
    probe_path = (
        Path(__file__).parent.parent
        / "app"
        / "prompts"
        / "probes"
        / "B09_density_imbalance.md"
    )
    text = probe_path.read_text(encoding="utf-8")

    assert "clean figure/chart remains credible evidence" in text
    assert "evaluate the slide-body" in text
    assert "composition here rather than as B17" in text
    assert "Source figure itself cannot support" in text
    assert "complete embedded wide/shallow image" in text
    assert "height growth as the main fix" in text
    assert "Raw academic figure too small" not in text


def test_visual_probe_fix_plan_gate_uses_whitespace_experience_not_hard_percentages():
    preamble_path = (
        Path(__file__).parent.parent
        / "app"
        / "prompts"
        / "probes"
        / "_shared"
        / "visual_preamble.md"
    )
    text = preamble_path.read_text(encoding="utf-8")

    assert "intended layout relationship" in text
    assert "do not invent rigid numeric thresholds" in text
    assert "layout-skeleton problem" in text
    assert "complete wide/shallow chart or figure" in text
    assert "give proportional sizes" not in text
    assert "use % of slide area" not in text


def test_visual_probe_input_marks_embedded_wide_images_as_indivisible(tmp_path):
    image_path = tmp_path / "wide_chart.png"
    Image.new("RGB", (800, 200), "white").save(image_path)
    extraction = SlideExtraction(
        slide_id=1,
        slide_index=0,
        title="Wide chart slide",
        objects=[
            ExtractedObject(
                object_id="img_1",
                shape_name="figure",
                object_type="picture",
                bbox_emu=[0, 0, 8000000, 3000000],
                has_image=True,
                image_path=str(image_path),
            )
        ],
        total_objects=1,
    )
    runner = ProbeRunner(llm=object(), config=ExperimentConfig(run_id="probe_inventory"))

    payload = json.loads(
        runner._build_visual_content(PROBE_REGISTRY["B09"], [1], [extraction], None)
    )

    image_obj = payload["slide_info"][0]["object_inventory"][0]
    assert image_obj["embedded_image_asset"] is True
    assert image_obj["internal_content_editable"] is False
    assert image_obj["natural_width_px"] == 800
    assert image_obj["natural_height_px"] == 200
    assert image_obj["natural_aspect_ratio"] == 4.0
    assert "wide_shallow_image" in image_obj["image_shape_note"]


def test_b02_figure_skeleton_fix_plan_preserves_wide_shallow_assets():
    probe_path = (
        Path(__file__).parent.parent
        / "app"
        / "prompts"
        / "probes"
        / "B02_layout_inappropriate.md"
    )
    text = probe_path.read_text(encoding="utf-8")

    assert "complete embedded wide/shallow asset" in text
    assert "simply increasing the" in text
    assert "image height" in text
    assert "lower/adjacent support region" in text


def test_b17_does_not_overflag_clean_paper_charts():
    probe_path = (
        Path(__file__).parent.parent
        / "app"
        / "prompts"
        / "probes"
        / "B17_raw_figure.md"
    )
    text = probe_path.read_text(encoding="utf-8")
    checks = [check["text"] for check in parse_probe_md(probe_path)]

    assert "not a general \"make academic figures look like native slide graphics\"" in text
    assert "the chart uses a dense paper style" in text
    assert "do not report B17" in text
    assert "undersized-but-clean figure slot" in text
    assert "A clean quantitative chart/plot" in text
    assert any(
        check.startswith("The slide asks the viewer to compare or locate specific panels")
        for check in checks
    )
    assert not any("Dense academic formatting" in check for check in checks)


def test_selected_atomic_check_focus_contains_only_requested_conditions():
    focus = ProbeRunner._format_selected_check_focus("B09", ["B09.1", "B09.8"])

    assert "B09.1:" in focus
    assert "B09.8:" in focus
    assert "B09.2:" not in focus
    assert "evaluate only the conditions below" in focus
