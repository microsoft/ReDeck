"""Spatial helper functions extracted from AgentRepair.

These were originally @staticmethod methods on the AgentRepair class.
They are pure functions that operate on spatial state data.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from .spatial_state import (
    SLIDE_WIDTH,
    SLIDE_HEIGHT,
    USABLE_LEFT,
    USABLE_RIGHT,
    USABLE_TOP,
    USABLE_BOTTOM,
)

if TYPE_CHECKING:
    from ...schemas.issue import Issue


def build_ascii_grid(spatial_state) -> str:
    """Build an ASCII grid showing element positions on the slide.

    Creates a 40×15 character grid (each cell ≈ 0.33" × 0.5") where
    each element gets a unique label character. This helps the model
    intuitively see spatial distribution and balance.
    """
    if not spatial_state or not spatial_state.blocks:
        return ""

    COLS, ROWS = 40, 15
    col_scale = COLS / 13.333  # chars per inch horizontally
    row_scale = ROWS / 7.5    # chars per inch vertically

    # Assign unique characters to blocks
    label_chars = "ABCDEFGHJKLMNPQRSTUVWXYZ123456789"
    block_labels: dict[str, str] = {}
    used_chars: set[str] = set()

    for i, b in enumerate(spatial_state.blocks):
        # Try first char of var_name, then fallback to sequential
        char = b.var_name[0].upper() if b.var_name else '?'
        if char in used_chars and i < len(label_chars):
            char = label_chars[i]
        used_chars.add(char)
        block_labels[b.var_name] = char

    # Initialize grid with empty
    grid = [['·' for _ in range(COLS)] for _ in range(ROWS)]
    legend = []

    # Draw blocks in reverse order (so topmost in Z-order appears)
    for b in reversed(spatial_state.blocks):
        char = block_labels.get(b.var_name, '?')
        # Map to grid coordinates
        c0 = max(0, min(COLS - 1, int(b.x * col_scale)))
        r0 = max(0, min(ROWS - 1, int(b.y * row_scale)))
        c1 = max(c0 + 1, min(COLS, int((b.x + b.w) * col_scale)))
        r1 = max(r0 + 1, min(ROWS, int((b.y + b.h) * row_scale)))

        for r in range(r0, r1):
            for c in range(c0, c1):
                grid[r][c] = char

    # Build legend in order
    for b in spatial_state.blocks:
        char = block_labels.get(b.var_name, '?')
        text = (b.text_lines[0][:30] if b.text_lines else "")
        legend.append(
            f"  {char} = {b.var_name} ({b.w:.1f}\"×{b.h:.1f}\") "
            f"{text}"
        )

    lines = [
        "## ASCII Slide Layout\n",
        "Each cell ≈ 0.33\" × 0.5\". Letters identify elements.\n",
    ]
    # Draw grid with border
    lines.append("  +" + "-" * COLS + "+")
    for row in grid:
        lines.append("  |" + "".join(row) + "|")
    lines.append("  +" + "-" * COLS + "+")
    lines.append("")
    lines.append("Legend:")
    lines.extend(legend)
    lines.append("")
    return "\n".join(lines)


def build_pairwise_relations(spatial_state, code: str) -> str:
    """Build pairwise spatial + visual relations between elements.

    Instead of raw coordinates, describes relationships that are
    immediately actionable:
    - ABOVE/BELOW with gap size
    - LEFT_OF/RIGHT_OF with gap size
    - OVERLAPS with overlap amount
    - Relative visual weight comparisons (LOUDER/QUIETER)

    LLMs process relational triples well, making this potentially
    more effective than coordinate tables.
    """
    if not spatial_state or not spatial_state.blocks:
        return ""

    blocks = [b for b in spatial_state.blocks if b.w > 0.3 and b.h > 0.1]
    if len(blocks) < 2:
        return ""

    # Extract fill colors for brightness
    fill_colors: dict[str, float] = {}
    for m in re.finditer(
        r'(\w+)\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    ):
        r, g, b_val = int(m.group(2)), int(m.group(3)), int(m.group(4))
        brightness = (0.299 * r + 0.587 * g + 0.114 * b_val) / 255
        fill_colors[m.group(1)] = brightness

    # Also resolve theme-based colors
    theme_dict: dict[str, float] = {}
    for m in re.finditer(
        r'"(\w+)"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    ):
        r, g, b_val = int(m.group(2)), int(m.group(3)), int(m.group(4))
        theme_dict[m.group(1)] = (0.299 * r + 0.587 * g + 0.114 * b_val) / 255
    for m in re.finditer(
        r'(\w+)\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
        code,
    ):
        key = m.group(2)
        if key in theme_dict:
            fill_colors[m.group(1)] = theme_dict[key]

    lines = ["## Spatial Relations Between Elements\n"]

    for i, a in enumerate(blocks):
        for b_blk in blocks[i+1:]:
            rels = []

            # Vertical relation
            a_bottom = a.y + a.h
            b_bottom = b_blk.y + b_blk.h
            if a_bottom <= b_blk.y:
                gap = b_blk.y - a_bottom
                rels.append(f"ABOVE (gap={gap:.2f}\")")
            elif b_bottom <= a.y:
                gap = a.y - b_bottom
                rels.append(f"BELOW (gap={gap:.2f}\")")
            else:
                # Vertical overlap
                overlap = min(a_bottom, b_bottom) - max(a.y, b_blk.y)
                if overlap > 0.05:
                    rels.append(f"V_OVERLAP={overlap:.2f}\"")

            # Horizontal relation
            a_right = a.x + a.w
            b_right = b_blk.x + b_blk.w
            if a_right <= b_blk.x + 0.1:
                gap = b_blk.x - a_right
                rels.append(f"LEFT_OF (gap={gap:.2f}\")")
            elif b_right <= a.x + 0.1:
                gap = a.x - b_right
                rels.append(f"RIGHT_OF (gap={gap:.2f}\")")

            # Size comparison
            a_area = a.w * a.h
            b_area = b_blk.w * b_blk.h
            if a_area > 0 and b_area > 0:
                ratio = max(a_area, b_area) / min(a_area, b_area)
                if ratio > 2:
                    bigger = a.var_name if a_area > b_area else b_blk.var_name
                    rels.append(f"{bigger} is {ratio:.1f}x larger")

            # Visual weight comparison
            a_bright = fill_colors.get(a.var_name, 0.9)
            b_bright = fill_colors.get(b_blk.var_name, 0.9)
            a_font = a.font_size_pt if a.font_size_pt > 0 else 14
            b_font = b_blk.font_size_pt if b_blk.font_size_pt > 0 else 14
            a_weight = a_area * (1 - a_bright) * (a_font / 16)
            b_weight = b_area * (1 - b_bright) * (b_font / 16)
            if a_weight > 0 and b_weight > 0:
                weight_ratio = max(a_weight, b_weight) / min(a_weight, b_weight)
                if weight_ratio > 2:
                    louder = a.var_name if a_weight > b_weight else b_blk.var_name
                    rels.append(f"{louder} is {weight_ratio:.1f}x more dominant visually")

            if rels:
                lines.append(
                    f"  {a.var_name} → {b_blk.var_name}: "
                    + ", ".join(rels)
                )

    lines.append("")
    return "\n".join(lines)


def build_vertical_strip(spatial_state) -> str:
    """Build a vertical strip projection of the slide layout.

    Shows what occupies each vertical band, making density
    distribution immediately obvious. This is a 1D projection
    that collapses the horizontal dimension.

    Example:
      y=0.0-0.8: [title_box] 30pt ██████████████████████ (full width)
      y=0.8-1.3: ──── empty ────
      y=1.3-1.9: [hero] 20pt ██████████████████████ (full width, ORANGE)
      y=2.0-6.0: [left_panel] 16pt ██████████  [right_panel] 16pt ██████████
      y=6.1-7.0: [takeaway] 18pt ██████████████████████ (full width)
    """
    if not spatial_state or not spatial_state.blocks:
        return ""

    blocks = [b for b in spatial_state.blocks if b.w > 0.3 and b.h > 0.1]
    if not blocks:
        return ""

    # Collect all y-boundary events
    events: list[tuple[float, str, object]] = []
    for b in blocks:
        events.append((b.y, 'start', b))
        events.append((b.y + b.h, 'end', b))

    # Sort by y position
    events.sort(key=lambda e: (e[0], 0 if e[1] == 'start' else 1))

    # Build bands
    active: set[str] = set()
    block_map = {b.var_name: b for b in blocks}
    bands: list[tuple[float, float, list[str]]] = []
    prev_y = 0.0

    # Discretize at each event boundary
    y_points = sorted(set(e[0] for e in events))
    for y in y_points:
        if y > prev_y + 0.05 and active:
            bands.append((prev_y, y, sorted(active)))
        elif y > prev_y + 0.2 and not active:
            bands.append((prev_y, y, []))
        # Process events at this y
        for ev_y, ev_type, ev_block in events:
            if abs(ev_y - y) < 0.01:
                if ev_type == 'start':
                    active.add(ev_block.var_name)
                else:
                    active.discard(ev_block.var_name)
        prev_y = y

    # Final band
    if active and prev_y < 7.5:
        bands.append((prev_y, 7.5, sorted(active)))

    if not bands:
        return ""

    BAR_WIDTH = 30
    lines = [
        "## Vertical Layout Strip\n",
        "Shows what occupies each vertical band (top to bottom).\n",
    ]

    for y0, y1, vars_in_band in bands:
        height = y1 - y0
        if not vars_in_band:
            lines.append(f"  y={y0:.1f}-{y1:.1f}: ──── empty ({height:.1f}\") ────")
            continue

        # Build bar for each element in this band
        parts = []
        for vn in vars_in_band:
            b = block_map.get(vn)
            if not b:
                continue
            # Width proportion
            w_frac = min(1.0, b.w / 13.333)
            bar_len = max(1, int(w_frac * BAR_WIDTH))
            bar = "█" * bar_len
            font_str = f"{b.font_size_pt:.0f}pt" if b.font_size_pt > 0 else ""
            text_hint = (b.text_lines[0][:20] if b.text_lines else "")
            parts.append(f"[{vn}] {font_str} {bar} {text_hint}")

        if len(parts) == 1:
            lines.append(f"  y={y0:.1f}-{y1:.1f} ({height:.1f}\"): {parts[0]}")
        else:
            lines.append(f"  y={y0:.1f}-{y1:.1f} ({height:.1f}\"):")
            for p in parts:
                lines.append(f"    {p}")

    lines.append("")
    return "\n".join(lines)


def build_elements_json(code: str, spatial_state) -> str:
    """Build a structured JSON array of slide elements.

    Each element maps directly to a code variable, with:
    - var_name: the Python variable name (for apply_edits)
    - shape_type: textbox/shape/picture/chart
    - position: {x, y, w, h} in inches
    - bottom/right edge (computed)
    - fill_color: {r, g, b} or null
    - fill_brightness: 0-1 (0=black, 1=white)
    - font_size_pt: dominant font size
    - text_preview: first line of text content
    - visual_weight: area × (1-brightness) × (font/16)
    - area_pct: % of usable slide area

    Designed for LLM consumption: JSON is the most native
    structured format for language models, requiring zero
    format-specific parsing. The var_name field directly maps
    to code identifiers for apply_edits.
    """
    if not spatial_state or not spatial_state.blocks:
        return ""

    usable_area = (USABLE_RIGHT - USABLE_LEFT) * (USABLE_BOTTOM - USABLE_TOP)

    # Extract fill colors
    fill_colors: dict[str, tuple[int, int, int]] = {}
    for m in re.finditer(
        r'(\w+)\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    ):
        fill_colors[m.group(1)] = (
            int(m.group(2)), int(m.group(3)), int(m.group(4)),
        )
    theme_dict: dict[str, tuple[int, int, int]] = {}
    for m in re.finditer(
        r'"(\w+)"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    ):
        theme_dict[m.group(1)] = (
            int(m.group(2)), int(m.group(3)), int(m.group(4)),
        )
    for m in re.finditer(
        r'(\w+)\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
        code,
    ):
        key = m.group(2)
        if key in theme_dict:
            fill_colors[m.group(1)] = theme_dict[key]

    elements = []
    for b in spatial_state.blocks:
        if b.w < 0.2 and b.h < 0.1:
            continue

        area = b.w * b.h
        pct = area / usable_area * 100

        fill_rgb = None
        brightness = 0.95
        if b.var_name in fill_colors:
            r, g, bb = fill_colors[b.var_name]
            fill_rgb = {"r": r, "g": g, "b": bb}
            brightness = (0.299 * r + 0.587 * g + 0.114 * bb) / 255

        font_pt = b.font_size_pt if b.font_size_pt > 0 else 14
        vw = area * max(0.1, 1.0 - brightness) * (font_pt / 16.0)

        text_preview = ""
        if b.text_lines:
            text_preview = b.text_lines[0][:60]

        elem = {
            "var_name": b.var_name,
            "shape_type": b.shape_type,
            "x": round(b.x, 2),
            "y": round(b.y, 2),
            "w": round(b.w, 2),
            "h": round(b.h, 2),
            "right": round(b.x + b.w, 2),
            "bottom": round(b.y + b.h, 2),
            "area_pct": round(pct, 1),
            "fill_color": fill_rgb,
            "brightness": round(brightness, 2),
            "font_pt": int(font_pt),
            "visual_weight": round(vw, 2),
            "text": text_preview,
        }
        elements.append(elem)

    # Sort by visual weight descending
    elements.sort(key=lambda e: e["visual_weight"], reverse=True)

    # Compute summary stats
    max_vw = elements[0]["visual_weight"] if elements else 1
    total_vw = sum(e["visual_weight"] for e in elements) or 1
    dominance_ratio = max_vw / max(0.01,
        elements[len(elements)//2]["visual_weight"]
        if len(elements) > 1 else 1
    )

    result = {
        "slide_bounds": {"w": 13.333, "h": 7.5},
        "usable_area": {
            "x_min": USABLE_LEFT, "x_max": USABLE_RIGHT,
            "y_min": USABLE_TOP, "y_max": USABLE_BOTTOM,
        },
        "dominance_ratio": round(dominance_ratio, 1),
        "elements": elements,
    }

    return (
        "## Slide Elements (JSON)\n\n"
        "Each element maps to a code variable. Use var_name in "
        "apply_edits search strings. Visual weight = area × darkness "
        "× font_scale — higher = more visually dominant.\n\n"
        f"```json\n{json.dumps(result, indent=2)}\n```\n"
    )


def find_available_slot(
    spatial_state,
) -> tuple[float, float, float, float] | None:
    """Find the largest empty rectangular region on the slide.

    Scans the vertical space between existing elements to find
    where a new chart could be placed without overlapping anything.

    Returns (x, y, width, height) or None.
    """
    blocks = [
        b for b in spatial_state.blocks
        if b.w > 0.3 and b.h > 0.2
    ]
    if not blocks:
        return (USABLE_LEFT, 1.5, 12.0, 5.0)

    # Sort by y-position
    sorted_blocks = sorted(blocks, key=lambda b: b.y)

    # Find vertical gaps between elements
    gaps: list[tuple[float, float]] = []

    # Gap from usable top to first element
    first_y = sorted_blocks[0].y
    if first_y - USABLE_TOP > 0.5:
        gaps.append((USABLE_TOP, first_y - 0.1))

    # Gaps between consecutive elements
    for i in range(len(sorted_blocks) - 1):
        bottom_i = sorted_blocks[i].y + sorted_blocks[i].h
        top_next = sorted_blocks[i + 1].y
        gap_h = top_next - bottom_i
        if gap_h > 0.5:
            gaps.append((bottom_i + 0.1, top_next - 0.1))

    # Gap from last element to usable bottom
    last_bottom = max(b.y + b.h for b in sorted_blocks)
    if USABLE_BOTTOM - last_bottom > 0.5:
        gaps.append((last_bottom + 0.1, USABLE_BOTTOM))

    if not gaps:
        # No vertical gaps — suggest bottom of slide
        return (
            USABLE_LEFT, last_bottom + 0.15,
            USABLE_RIGHT - USABLE_LEFT,
            max(1.0, USABLE_BOTTOM - last_bottom - 0.15),
        )

    # Pick the largest gap
    best_gap = max(gaps, key=lambda g: g[1] - g[0])
    gap_h = best_gap[1] - best_gap[0]

    return (
        USABLE_LEFT, best_gap[0],
        USABLE_RIGHT - USABLE_LEFT,
        min(gap_h, 4.0),  # cap at 4" tall
    )


def compute_spatial_context(spatial_state) -> str:
    """Compute quantitative spatial distribution for B2/B8 issues.

    Returns a compact summary of how elements are distributed on the
    slide, giving the LLM the spatial facts it needs to reason about
    layout changes.
    """
    blocks = [
        b for b in spatial_state.blocks
        if b.w > 0.5 and b.h > 0.3
    ]
    if len(blocks) < 2:
        return ""

    slide_mid_y = 3.75
    top = [b for b in blocks if b.y + b.h / 2 < slide_mid_y]
    bottom = [b for b in blocks if b.y + b.h / 2 >= slide_mid_y]
    top_area = sum(b.w * b.h for b in top)
    bottom_area = sum(b.w * b.h for b in bottom)
    total = top_area + bottom_area

    if total < 0.1:
        return ""

    top_pct = top_area / total * 100
    bottom_pct = bottom_area / total * 100

    # Also check left vs right
    slide_mid_x = 6.67  # middle of 13.33"
    left = [b for b in blocks if b.x + b.w / 2 < slide_mid_x]
    right = [b for b in blocks if b.x + b.w / 2 >= slide_mid_x]
    left_area = sum(b.w * b.h for b in left)
    right_area = sum(b.w * b.h for b in right)

    # Find the bottom-most element boundary
    max_y_bottom = max(b.y + b.h for b in blocks)
    empty_below = 7.20 - max_y_bottom  # distance to usable bottom

    lines = [
        f"   SPATIAL CONTEXT: "
        f"top-half {len(top)} elements ({top_pct:.0f}%), "
        f"bottom-half {len(bottom)} elements ({bottom_pct:.0f}%)"
    ]

    if empty_below > 1.5:
        lines.append(
            f"   → {empty_below:.1f}\" empty below last element "
            f"(y={max_y_bottom:.1f}\"→7.20\")"
        )

    if abs(left_area - right_area) > total * 0.3:
        lines.append(
            f"   → Left/right imbalance: "
            f"left {len(left)} ({left_area/(total+0.01)*100:.0f}%) "
            f"vs right {len(right)} ({right_area/(total+0.01)*100:.0f}%)"
        )

    return "\n".join(lines)


def compute_coverage_pct(spatial_state) -> float:
    """Compute content area coverage as % of slide canvas."""
    blocks = [b for b in spatial_state.blocks if b.w > 0.3 and b.h > 0.2]
    if not blocks:
        return 0.0
    canvas_area = 13.333 * 7.5  # inches
    min_x = min(b.x for b in blocks)
    min_y = min(b.y for b in blocks)
    max_x = max(b.x + b.w for b in blocks)
    max_y = max(b.y + b.h for b in blocks)
    union_area = (max_x - min_x) * (max_y - min_y)
    return (union_area / canvas_area) * 100


def format_spatial_issue_with_px(
    issue: "Issue",
    spatial_state,
) -> str:
    """Add px bounding-box context for spatial issues on HTML slides.

    Converts the inch-based spatial state back to CSS px so the agent
    sees coordinates it can directly use in style edits.
    """
    from .html_spatial_state import VIEWPORT_W, VIEWPORT_H
    from ...schemas.issue_types import SlideDimensions

    inch_to_px_x = VIEWPORT_W / SLIDE_WIDTH
    inch_to_px_y = VIEWPORT_H / SLIDE_HEIGHT

    def _blk_px(b) -> str:
        lx = round(b.x * inch_to_px_x)
        ty = round(b.y * inch_to_px_y)
        bw = round(b.w * inch_to_px_x)
        bh = round(b.h * inch_to_px_y)
        label = b.var_name or b.block_id
        return (
            f"{label}({b.block_id}) at "
            f"(left:{lx}px, top:{ty}px, "
            f"width:{bw}px, height:{bh}px)"
        )

    blk_map = {b.block_id: b for b in spatial_state.blocks}
    lines: list[str] = []

    if issue.issue_type == "overlap":
        for a_id, b_id, ratio in spatial_state.overlap_pairs:
            a, b = blk_map.get(a_id), blk_map.get(b_id)
            if a and b:
                lines.append(
                    f"   CSS bbox: {_blk_px(a)} overlaps "
                    f"{_blk_px(b)} ({ratio:.0%} intersection)"
                )

    elif issue.issue_type == "text_overflow":
        for bid in spatial_state.overflow_blocks:
            blk = blk_map.get(bid)
            if blk:
                lines.append(
                    f"   CSS bbox: {_blk_px(blk)} — text overflows "
                    f"container ({blk.overflow_bottom_px}px bottom, {blk.overflow_right_px}px right)"
                )

    elif issue.issue_type == "out_of_bounds":
        for bid in spatial_state.oob_blocks:
            blk = blk_map.get(bid)
            if blk:
                lines.append(
                    f"   CSS bbox: {_blk_px(blk)} — extends "
                    f"outside slide ({SlideDimensions.VIEWPORT_W}×{SlideDimensions.VIEWPORT_H}px viewport)"
                )

    return "\n".join(lines) if lines else ""


def extract_palette_note(code: str, is_html: bool) -> str:
    """Extract color values from slide code to remind agent of deck palette."""
    import re as _re
    colors = set()
    if is_html:
        # Extract rgb(...) and hex colors from CSS
        for m in _re.finditer(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', code):
            colors.add(m.group(0))
        for m in _re.finditer(r'#[0-9a-fA-F]{6}\b', code):
            colors.add(m.group(0))
    else:
        # Extract RGBColor values
        for m in _re.finditer(r'RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', code):
            colors.add(m.group(0))
    if not colors:
        return ""
    palette_list = ", ".join(sorted(colors)[:12])  # limit to 12 most common
    return (
        f"**DECK COLOR PALETTE** (extracted from this slide's code): "
        f"{palette_list}\n"
        f"You MUST stay within this palette. When fixing contrast, adjust "
        f"lightness/saturation of existing colors — do NOT introduce new "
        f"hues (e.g., do not change green→blue or orange→brown).\n"
    )


def annotate_issue_locations(
    issue: "Issue",
    code: str,
    code_lines: list[str],
) -> str:
    """Find specific code locations referenced by an issue.

    For content issues (fabricated, incorrect_claim, etc.), find the
    exact lines containing the problematic text and annotate them.
    For layout issues (B-series), identify the shape variables and
    their current dimensions.

    Returns annotation string or empty string.
    """
    from .repair_utils import extract_table_row_specs_from_correct_content

    desc = (
        issue.evidence.description
        or issue.why_this_fails
        or ""
    )
    fix = issue.planned_fix or ""
    itype = issue.issue_type

    lines_out = []

    # --- Content issues: find quoted strings from description in code ---
    if itype in {
        "fabricated", "incorrect_claim", "numeric_error",
        "entity_error", "unfaithful_compression",
        "unsupported_causality", "chart_misinterpretation",
    }:
        # Extract quoted strings from description
        quoted = re.findall(r'"([^"]{5,})"', desc)
        quoted += re.findall(r"'([^']{5,})'", desc)
        if quoted:
            found_any = False
            for q in quoted[:6]:
                q_lower = q.lower()
                for line_no, line in enumerate(code_lines, 1):
                    if q_lower in line.lower():
                        lines_out.append(
                            f"   → Line {line_no}: {line.strip()[:100]}"
                        )
                        found_any = True
            if found_any:
                lines_out.insert(0, "   Code locations with this content:")
        lines_out.append(
            "   ⚠️ MINIMAL REWRITE: Replace ONLY the incorrect phrases with "
            "source-verified text. Do NOT rephrase surrounding sentences that "
            "are already correct. Preserve the slide's structure and density."
        )
        lines_out.append(
            "   ⚠️ VISUAL STRUCTURE: If the incorrect text is inside a metric "
            "card, table cell, or chart label, replace ONLY the value (number/"
            "keyword). Do NOT convert visual elements into sentences. A metric "
            "card with '7.03' should become a metric card with the correct "
            "number, NOT a paragraph of text."
        )
        # Detect if the fabricated content is inside a metric card or data
        # element — if so, force search_source before editing
        is_data_element = False
        for q in re.findall(r'"([^"]{3,})"', desc)[:4]:
            for line in code_lines:
                if q.lower() in line.lower():
                    # Check if the line is inside a metric card / table cell
                    if any(kw in line.lower() for kw in [
                        'metric', 'number', 'score', 'accuracy',
                    ]) or re.search(r'>\s*[\d.]+\s*<', line):
                        is_data_element = True
                        break
            if is_data_element:
                break
        if is_data_element:
            lines_out.append(
                "   🔍 MANDATORY: This appears to be a numeric data element "
                "(metric card / table cell). You MUST call search_source or "
                "lookup_table FIRST to find the correct number from the paper "
                "BEFORE making any edits. Replace the number with the correct "
                "number — do NOT replace it with descriptive text or labels."
            )

        # --- Generate ready-made search/replace for content fixes ---
        # Find the exact code text that matches the problematic claim
        # and pair it with the fix text, so the agent can copy-paste.
        if fix and quoted:
            fix_quoted = re.findall(r'"([^"]{8,})"', fix)
            if fix_quoted:
                is_html_code = "<!DOCTYPE" in code or ("<html" in code and "<body" in code)
                # Try to find which code line contains the problematic text
                for q in quoted[:3]:
                    q_lower = q.lower()
                    for line_no, line in enumerate(code_lines, 1):
                        if q_lower in line.lower():
                            if is_html_code:
                                # For HTML: find text between tags
                                tag_match = re.search(
                                    r'(>[^<]*?)(' + re.escape(q) + r')([^<]*<)',
                                    line, re.IGNORECASE,
                                )
                                if tag_match:
                                    old_text = q
                                    lines_out.append(
                                        f'   📋 READY-MADE FIX: '
                                        f'{{"search": "{old_text[:100]}", '
                                        f'"replace": "{fix_quoted[0][:100]}"}}'
                                    )
                                    break
                            else:
                                # For pptx: find .text = "..." assignments
                                text_match = re.search(
                                    r'(\.text\s*=\s*["\'])(.+?)(["\'])',
                                    line,
                                )
                                if text_match:
                                    old_text = text_match.group(2)
                                    lines_out.append(
                                        f'   📋 READY-MADE FIX: '
                                        f'{{"search": "{old_text[:100]}", '
                                        f'"replace": "{fix_quoted[0][:100]}"}}'
                                    )
                                    break
                                dict_match = re.search(
                                    r'("text"\s*:\s*")([^"]+)(")',
                                    line,
                                )
                                if dict_match:
                                    old_text = dict_match.group(2)
                                    lines_out.append(
                                        f'   📋 READY-MADE FIX: '
                                        f'{{"search": "{old_text[:100]}", '
                                        f'"replace": "{fix_quoted[0][:100]}"}}'
                                    )
                                    break
                    else:
                        continue
                    break  # only need one match

        # --- Detect problematic data in chart/viz JSON or add_series ---
        # Extract numbers from the issue description
        desc_numbers = re.findall(r'\b(\d+\.?\d*)\b', desc)
        desc_numbers = [n for n in desc_numbers if len(n) >= 2]

        chart_data_lines = []
        image_lines = []
        is_html_code = "<!DOCTYPE" in code or ("<html" in code and "<body" in code)
        for line_no, line in enumerate(code_lines, 1):
            if is_html_code:
                # HTML: embedded images
                if '<img' in line:
                    image_lines.append((line_no, line.strip()[:120]))
            else:
                # pptx: Chart data in JSON strings or add_series calls
                if any(kw in line for kw in [
                    'viz_data_str', 'add_series', '"values"',
                    'chart_data.categories', '"categories"',
                ]):
                    for n in desc_numbers[:5]:
                        if n in line:
                            chart_data_lines.append(
                                (line_no, line.strip()[:120])
                            )
                            break
                # Embedded images
                if 'add_picture' in line:
                    image_lines.append((line_no, line.strip()[:120]))

        if chart_data_lines:
            lines_out.append(
                "   ⚠ FABRICATED DATA IN CHART — the problematic "
                "values appear in chart data, not just text! You MUST "
                "either (a) edit the chart data values, or (b) "
                "delete_shape the chart and replace it:"
            )
            for ln, lt in chart_data_lines:
                lines_out.append(f"   → Line {ln}: {lt}")

        if image_lines and itype in {"fabricated", "numeric_error",
                                     "untraceable"}:
            # Find the variable name for delete_shape suggestion
            pic_var_names = re.findall(
                r'(\w+)\s*=\s*slide\.shapes\.add_picture\(',
                code,
            )
            lines_out.append(
                "   ⚠ FABRICATED DATA IN EMBEDDED IMAGE — you CANNOT "
                "edit text inside a PNG. The fabricated values are "
                "rendered inside the image. You MUST:"
            )
            lines_out.append(
                "   1. Delete the image (and its container card/shape)"
            )
            lines_out.append(
                "   2. Add a text box with correct information from "
                "the source evidence"
            )
            for ln, lt in image_lines:
                lines_out.append(f"   → Line {ln}: {lt}")
            if pic_var_names:
                lines_out.append(
                    f'   → Suggested: {{"tool": "delete_shape", '
                    f'"var_name": "{pic_var_names[0]}"}}'
                )
                # Also look for the container card
                for b in code_lines:
                    if pic_var_names[0] in b:
                        break

    # --- Missing content: show where content COULD be added ---
    elif itype in {"missing_evidence", "missing_point",
                   "missing_conclusion", "missing_entity"}:
        fd = getattr(issue, "fix_detail", None)
        row_specs = extract_table_row_specs_from_correct_content(
            getattr(fd, "correct_content", "") if fd else "",
        )
        action_type = (getattr(fd, "action_type", "") or "").lower() if fd else ""
        target = (getattr(fd, "target_location", "") or "").lower() if fd else ""
        if row_specs and (action_type == "add_data_row" or "table" in target or "row" in target):
            table_lines = []
            for line_no, line in enumerate(code_lines, 1):
                if any(token in line.lower() for token in ("<table", "<tbody", "<tr", "</tbody>", "</table>")):
                    table_lines.append((line_no, line.strip()[:100]))
            if table_lines:
                lines_out.append("   Existing table locations (candidates for row insertion):")
                for ln, lt in table_lines[-8:]:
                    lines_out.append(f"   -> Line {ln}: {lt}")
            rows_text = "; ".join(row_specs)
            lines_out.append(
                "   TABLE ROW INSERTION: add the missing source rows as "
                f"real <tr>/<td> cells ({rows_text[:260]}). Do NOT add "
                "a paragraph, footer note, or visible editorial instruction."
            )
            return "\n".join(lines_out) if lines_out else ""

        # Find text assignments to suggest insertion points
        text_lines = []
        for line_no, line in enumerate(code_lines, 1):
            if '.text' in line and '=' in line:
                text_lines.append((line_no, line.strip()[:80]))
        if text_lines:
            lines_out.append(
                f"   Existing text locations (candidates for edit/insertion):"
            )
            for ln, lt in text_lines[-5:]:
                lines_out.append(f"   → Line {ln}: {lt}")
        lines_out.append(
            "   CONTENT FIT STRATEGY: make the missing content visible "
            "without blindly appending text. On crowded slides, merge it "
            "into the closest same-topic sentence/list item and preserve "
            "existing source-backed numbers, model names, and claims. "
            "Only insert a new paragraph/bullet when there is clear space. "
            "Do not use titles, page headers, full-width bottom bars, "
            "footers, or source notes as spare space for long content."
        )

    # --- Layout issues: identify shapes and their dimensions ---
    elif itype in {
        "density_imbalance", "text_visual_imbalance",
        "layout_inappropriate", "text_overflow",
    }:
        # Extract shape mentions from description
        desc_lower = desc.lower()

        # Find shapes with their dimensions
        shape_lines = []
        for line_no, line in enumerate(code_lines, 1):
            if any(kw in line for kw in [
                'add_textbox(', 'add_shape(', 'add_picture(',
            ]):
                # Extract Inches values
                inches_vals = re.findall(r'Inches\(([\d.]+)\)', line)
                if len(inches_vals) >= 4:
                    x, y, w, h = [float(v) for v in inches_vals[:4]]
                    shape_lines.append(
                        f"   → Line {line_no}: x={x:.1f} y={y:.1f} "
                        f"w={w:.1f} h={h:.1f}  {line.strip()[:60]}"
                    )
        if shape_lines:
            lines_out.append("   Shape dimensions in code:")
            lines_out.extend(shape_lines[:8])

    return "\n".join(lines_out) if lines_out else ""
