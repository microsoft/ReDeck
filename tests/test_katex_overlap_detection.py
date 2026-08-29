"""Test that KaTeX formulas extending beyond their container trigger overlap detection."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.modules.redeck.html_spatial_state import extract_html_slide_state


# Minimal two-column slide where left column has a wide KaTeX formula
# that visually extends into the right column's territory.
SLIDE_HTML_OVERLAP = """\
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.45/dist/katex.min.css">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; overflow: hidden; }
.slide { display: flex; width: 1280px; height: 720px; }
.left { width: 600px; padding: 40px; }
.right { width: 680px; padding: 40px; }
h2 { font-size: 28px; margin-bottom: 20px; }
p { font-size: 18px; line-height: 1.5; }
/* Force the formula container to NOT clip — formula will visually overflow */
.formula-box { overflow: visible; }
</style>
</head>
<body>
<div class="slide">
  <div class="left">
    <h2>Method Overview</h2>
    <div class="formula-box">
      <p>$$\\mathcal{L}_{\\text{total}} = \\alpha \\cdot \\mathcal{L}_{\\text{alignment}} + \\beta \\cdot \\mathcal{L}_{\\text{uniformity}} + \\gamma \\cdot \\mathcal{L}_{\\text{regularization}} + \\delta \\cdot \\mathcal{L}_{\\text{distillation}}$$</p>
    </div>
    <p>The loss function combines four terms for robust training.</p>
  </div>
  <div class="right">
    <h2>Results</h2>
    <p>Our method achieves state-of-the-art performance on all benchmarks with significant margins.</p>
  </div>
</div>
</body>
</html>
"""

# Control: no overlap — formula is short
SLIDE_HTML_NO_OVERLAP = """\
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.45/dist/katex.min.css">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: Arial; overflow: hidden; }
.slide { display: flex; width: 1280px; height: 720px; }
.left { width: 600px; padding: 40px; }
.right { width: 680px; padding: 40px; }
h2 { font-size: 28px; margin-bottom: 20px; }
p { font-size: 18px; line-height: 1.5; }
</style>
</head>
<body>
<div class="slide">
  <div class="left">
    <h2>Method</h2>
    <p>$$x = a + b$$</p>
    <p>Simple formulation.</p>
  </div>
  <div class="right">
    <h2>Results</h2>
    <p>Good results on benchmarks.</p>
  </div>
</div>
</body>
</html>
"""


def test_katex_cross_column_overlap():
    """Wide KaTeX formula crossing into right column should be detected as overlap."""
    state = extract_html_slide_state(1, SLIDE_HTML_OVERLAP)

    print(f"\n=== Overlap test ===")
    print(f"Blocks: {len(state.blocks)}")
    for b in state.blocks:
        vb = b._visual_bounds if hasattr(b, '_visual_bounds') else None
        print(f"  {b.block_id} | {b.shape_type:8s} | css=({b.x:.1f},{b.y:.1f},{b.w:.1f},{b.h:.1f}) | vis={vb} | {b.var_name} chars={b.text_chars}")
    print(f"Overlap pairs: {state.overlap_pairs}")
    print(f"OOB blocks: {state.oob_blocks}")
    print(f"Overflow blocks: {state.overflow_blocks}")

    # We expect at least one overlap pair involving the formula container
    # and the right column content
    if state.overlap_pairs:
        print("✅ KaTeX cross-column overlap DETECTED")
    else:
        # Check if visual bounds extended
        for b in state.blocks:
            if hasattr(b, '_visual_bounds'):
                vx, vy, vw, vh = b._visual_bounds
                if vx + vw > b.x + b.w + 0.1:
                    print(f"  {b.block_id} visual extends: css_right={b.x+b.w:.1f} visual_right={vx+vw:.1f}")
        print("❌ KaTeX cross-column overlap NOT detected")


def test_no_false_positive():
    """Short formula should NOT trigger overlap."""
    state = extract_html_slide_state(2, SLIDE_HTML_NO_OVERLAP)

    print(f"\n=== No-overlap control ===")
    print(f"Blocks: {len(state.blocks)}")
    print(f"Overlap pairs: {state.overlap_pairs}")

    # Filter out any parent-child overlaps — we only care about cross-column
    if not state.overlap_pairs:
        print("✅ No false positive overlap")
    else:
        print(f"⚠️  Unexpected overlaps: {state.overlap_pairs}")


def test_real_slide_6():
    """Test on actual slide 6 from the Booster run (known KaTeX overlap issue)."""
    slide_path = ROOT / "runs/example
    if not slide_path.exists():
        print("\n=== Slide 6 test SKIPPED (file not found) ===")
        return

    html = slide_path.read_text()
    state = extract_html_slide_state(6, html)

    print(f"\n=== Real slide 6 ===")
    print(f"Blocks: {len(state.blocks)}")
    for b in state.blocks:
        vb = b._visual_bounds if hasattr(b, '_visual_bounds') else None
        css_right = b.x + b.w
        vis_right = vb[0] + vb[2] if vb else css_right
        ext = f" +{vis_right - css_right:.1f}in" if vis_right > css_right + 0.1 else ""
        print(f"  {b.block_id} | {b.shape_type:8s} | right={css_right:.1f}{ext} | {b.var_name} chars={b.text_chars}")
    print(f"Overlap pairs: {state.overlap_pairs}")
    print(f"OOB blocks: {state.oob_blocks}")


if __name__ == "__main__":
    test_katex_cross_column_overlap()
    test_no_false_positive()
    test_real_slide_6()
