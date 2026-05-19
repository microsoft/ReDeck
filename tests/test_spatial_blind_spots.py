"""Test spatial detection blind spots: object-fit crop, text-overflow ellipsis, clip-path, transform scale."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.modules.redeck.html_spatial_state import extract_html_slide_state


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
