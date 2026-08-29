"""Test spatial detection blind spots: object-fit crop, text-overflow ellipsis, clip-path, transform scale."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.modules.redeck.html_spatial_state import (
    count_significant_issues,
    extract_html_slide_state,
    format_html_compact_state,
    measure_space_occupancy,
    run_deterministic_checks,
)


# ── Test 1: object-fit:cover crops image content ──

SLIDE_OBJFIT_COVER = """\
<!DOCTYPE html>
<html>
<head>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; }
</style>
</head>
<body>
<div style="position: absolute; left: 60px; top: 120px; width: 400px; height: 100px; overflow: hidden;">
    <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='400' height='400'%3E%3Crect fill='%23ccc' width='400' height='400'/%3E%3C/svg%3E"
         style="width: 400px; height: 100px; object-fit: cover;">
</div>
</body>
</html>
"""


def test_object_fit_cover_crop():
    """object-fit:cover with aspect ratio mismatch should flag as clipped."""
    state = extract_html_slide_state(1, SLIDE_OBJFIT_COVER)

    img_blocks = [b for b in state.blocks if b.shape_type == "picture"]
    assert len(img_blocks) >= 1, f"Expected at least 1 picture block, got {len(img_blocks)}"

    img = img_blocks[0]
    print(f"\n[object-fit:cover] clipped={img.is_clipped} crop_pct={img.img_crop_pct}")
    # 400x400 natural in 400x100 box with cover → crops 75% vertically
    assert img.img_crop_pct > 0.5, f"Expected crop_pct > 0.5, got {img.img_crop_pct}"
    assert img.is_clipped, "Expected is_clipped=True for heavily cropped image"


SLIDE_OBJFIT_CONTAIN_LETTERBOX = """\
<!DOCTYPE html>
<html>
<head>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; }
</style>
</head>
<body>
<img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='100' viewBox='0 0 800 100'%3E%3Crect fill='%23ddd' width='800' height='100'/%3E%3Cpath d='M20 70 L200 40 L380 62 L560 22 L780 45' stroke='%23266' stroke-width='8' fill='none'/%3E%3C/svg%3E"
     style="position:absolute; left:100px; top:100px; width:400px; height:250px; object-fit:contain; object-position:center center;">
</body>
</html>
"""


def test_object_fit_contain_reports_rendered_content_and_letterbox():
    """object-fit:contain should expose actual bitmap rect, not just img bbox."""
    state = extract_html_slide_state(1, SLIDE_OBJFIT_CONTAIN_LETTERBOX)

    img_blocks = [b for b in state.blocks if b.shape_type == "picture"]
    assert len(img_blocks) >= 1, f"Expected at least 1 picture block, got {len(img_blocks)}"
    img = img_blocks[0]

    assert img.img_natural_w_px == 800
    assert img.img_natural_h_px == 100
    assert img.img_object_fit == "contain"
    cx, cy, cw, ch = img.img_rendered_content_bbox_px
    assert (cx, cw) == (100, 400)
    assert 145 <= cy <= 205
    assert 45 <= ch <= 55
    assert img.img_letterbox_top_px >= 90
    assert img.img_letterbox_bottom_px >= 90

    report = format_html_compact_state(state)
    assert "rendered image content" in report
    assert "IMAGE LETTERBOX MEASUREMENT" in report
    assert "IMAGE ASPECT MEASUREMENT" in report
    assert "prefer a layout reflow of existing content" in report
    assert "Keep caption/source compact" in report

    occupancy = measure_space_occupancy(state.blocks, cols=4, rows=4)
    # The bottom half of the tall <img> box should not count as occupied when
    # the contained bitmap is only a shallow horizontal strip.
    assert occupancy["quadrant_fill"]["BL"] == 0


# ── Test 2: text-overflow:ellipsis truncation ──

SLIDE_ELLIPSIS = """\
<!DOCTYPE html>
<html>
<head>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; }
</style>
</head>
<body>
<p style="position: absolute; left: 60px; top: 120px; width: 200px;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          font-size: 16px;">
    This is a very long text that should definitely be truncated with an ellipsis because it exceeds the container width significantly
</p>
</body>
</html>
"""


def test_text_overflow_ellipsis():
    """text-overflow:ellipsis should flag as clipped."""
    state = extract_html_slide_state(1, SLIDE_ELLIPSIS)

    text_blocks = [b for b in state.blocks if b.text_chars > 10]
    assert len(text_blocks) >= 1, f"Expected at least 1 text block, got {len(text_blocks)}"

    blk = text_blocks[0]
    print(f"\n[ellipsis] clipped={blk.is_clipped} ellipsized={blk.is_ellipsized}")
    assert blk.is_clipped, "Expected is_clipped=True for ellipsized text"
    assert blk.is_ellipsized, "Expected is_ellipsized=True"


# ── Test 3: clip-path ──

SLIDE_CLIP_PATH = """\
<!DOCTYPE html>
<html>
<head>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; }
</style>
</head>
<body>
<p style="position: absolute; left: 60px; top: 120px; width: 300px;
          clip-path: inset(0 0 50% 0); font-size: 18px;">
    This text has its bottom half clipped away by clip-path
</p>
</body>
</html>
"""


def test_clip_path():
    """clip-path should flag as clipped."""
    state = extract_html_slide_state(1, SLIDE_CLIP_PATH)

    text_blocks = [b for b in state.blocks if b.text_chars > 5]
    assert len(text_blocks) >= 1, f"Expected at least 1 text block, got {len(text_blocks)}"

    blk = text_blocks[0]
    print(f"\n[clip-path] clipped={blk.is_clipped} has_clip_path={blk.has_clip_path}")
    assert blk.has_clip_path, "Expected has_clip_path=True"
    assert blk.is_clipped, "Expected is_clipped=True for clip-path element"


# ── Test 4: transform:scale makes text too small ──

SLIDE_TRANSFORM_SCALE = """\
<!DOCTYPE html>
<html>
<head>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; }
</style>
</head>
<body>
<p style="position: absolute; left: 60px; top: 120px; font-size: 20px;
          transform: scale(0.4); transform-origin: top left;">
    This text looks tiny due to scale transform
</p>
</body>
</html>
"""


def test_transform_scale():
    """transform:scale(0.4) on 20px text → effectiveFontSize ≈ 8px."""
    state = extract_html_slide_state(1, SLIDE_TRANSFORM_SCALE)

    text_blocks = [b for b in state.blocks if b.text_chars > 5]
    assert len(text_blocks) >= 1, f"Expected at least 1 text block, got {len(text_blocks)}"

    blk = text_blocks[0]
    print(f"\n[transform:scale] font_size_px={blk.font_size_px} effective={blk.effective_font_size_px}")
    assert blk.effective_font_size_px < 10, f"Expected effective_font_size < 10, got {blk.effective_font_size_px}"
    assert blk.effective_font_size_px > 6, f"Expected effective_font_size > 6, got {blk.effective_font_size_px}"


# ── Test 5: Negative control — normal content ──

SLIDE_NORMAL = """\
<!DOCTYPE html>
<html>
<head>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; }
</style>
</head>
<body>
<h2 style="position: absolute; left: 60px; top: 30px; font-size: 28px;">Normal Slide</h2>
<p style="position: absolute; left: 60px; top: 120px; width: 500px; font-size: 18px;">
    This is normal text content that fits within its container without any issues.
</p>
</body>
</html>
"""


SLIDE_CLIPPED_SVG_SHAPES = """\
<!DOCTYPE html>
<html>
<head>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; }
</style>
</head>
<body>
<div style="position: absolute; left: 60px; top: 120px; width: 500px; height: 180px; overflow: hidden;">
  <svg class="visual-object" viewBox="0 0 500 320" style="width: 500px; height: 320px;">
    <rect x="0" y="0" width="500" height="320" fill="#eeeeee"></rect>
    <rect x="40" y="220" width="120" height="70" fill="#336699"></rect>
    <line x1="30" y1="260" x2="470" y2="260" stroke="#222" stroke-width="4"></line>
  </svg>
</div>
</body>
</html>
"""


def test_clipped_svg_shapes_are_not_counted_as_text_clipping():
    """A cropped SVG chart container is visual clipping, not clipped text."""
    state = extract_html_slide_state(1, SLIDE_CLIPPED_SVG_SHAPES)
    issues = count_significant_issues(state)

    assert issues["clipped"] == []
    assert issues["text_overflow"] == []


def test_external_svg_asset_text_overflow_is_reported(tmp_path):
    """SVG loaded via <img> should still expose internal text/rect overflow."""
    asset_dir = tmp_path / "turn_01" / "generated_assets"
    asset_dir.mkdir(parents=True)
    svg_path = asset_dir / "overflow.svg"
    svg_path.write_text(
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
      <img src="../generated_assets/overflow.svg" style="position:absolute;left:80px;top:90px;width:360px;height:180px;object-fit:contain">
    </body></html>
    """

    state = extract_html_slide_state(1, html, asset_base_dirs=[asset_dir])

    assert len(state.svg_asset_issues) == 1
    issue = state.svg_asset_issues[0]
    assert issue["label"] == "Parietal-occipital propagation"
    assert issue["asset_name"] == "overflow.svg"
    compact = format_html_compact_state(state)
    assert "SVG ASSET TEXT OVERFLOW" in compact
    assert "overflow.svg" in compact
    significant = count_significant_issues(state)
    assert significant["svg_text_overflow"] == [issue["id"]]

    det_issues = run_deterministic_checks(state, 1)
    assert any(
        item.issue_type == "svg_visual_defect"
        and item.rubric_id == "B20"
        and item.source_probe_id == "geom_svg_asset_text_fit"
        for item in det_issues
    )


def test_external_svg_asset_wrapped_tspan_label_is_clean(tmp_path):
    asset_dir = tmp_path / "turn_01" / "generated_assets"
    asset_dir.mkdir(parents=True)
    svg_path = asset_dir / "wrapped.svg"
    svg_path.write_text(
        """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 90">
          <g>
            <rect x="20" y="20" width="120" height="50" fill="#eef"/>
            <text text-anchor="middle" font-size="13">
              <tspan x="80" y="40">Parietal-</tspan>
              <tspan x="80" y="56">occipital</tspan>
            </text>
          </g>
        </svg>
        """,
        encoding="utf-8",
    )
    html = """
    <!doctype html><html><body style="margin:0;width:1280px;height:720px">
      <img src="../generated_assets/wrapped.svg" style="position:absolute;left:80px;top:90px;width:360px;height:180px;object-fit:contain">
    </body></html>
    """

    state = extract_html_slide_state(1, html, asset_base_dirs=[asset_dir])

    assert state.svg_asset_issues == []
    assert count_significant_issues(state)["svg_text_overflow"] == []


def test_normal_no_blind_spots():
    """Normal content should not trigger any blind-spot flags."""
    state = extract_html_slide_state(1, SLIDE_NORMAL)

    for b in state.blocks:
        assert not b.is_ellipsized, f"Block {b.block_id} should not be ellipsized"
        assert not b.has_clip_path, f"Block {b.block_id} should not have clip-path"
        assert b.img_crop_pct == 0, f"Block {b.block_id} should have 0 img_crop_pct"
        if b.text_chars > 0:
            assert not b.is_clipped, f"Block {b.block_id} should not be clipped"

    print(f"\n[normal] {len(state.blocks)} blocks, all clean")


if __name__ == "__main__":
    test_object_fit_cover_crop()
    test_text_overflow_ellipsis()
    test_clip_path()
    test_transform_scale()
    test_normal_no_blind_spots()
    print("\n✅ All blind-spot tests passed!")
