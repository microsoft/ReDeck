"""Spatial State — data classes and constants for slide geometry.

Provides ContentBlock, SlideState, AlignmentIssue data classes and
slide dimension constants used by html_spatial_state.py (Playwright-based
DOM extraction) and formatting functions.

All PPTX code-parsing and char-based estimation logic has been removed.
Only HTML/Playwright-based spatial analysis is supported.
"""

import logging
from dataclasses import dataclass, field

from ...schemas.issue_types import SlideDimensions

logger = logging.getLogger(__name__)

# Slide dimensions (inches) — imported from single source of truth
SLIDE_WIDTH = SlideDimensions.WIDTH_IN
SLIDE_HEIGHT = SlideDimensions.HEIGHT_IN
USABLE_LEFT = SlideDimensions.USABLE_LEFT_IN
USABLE_RIGHT = SlideDimensions.USABLE_RIGHT_IN
USABLE_TOP = SlideDimensions.USABLE_TOP_IN
USABLE_BOTTOM = SlideDimensions.USABLE_BOTTOM_IN


@dataclass
class ContentBlock:
    """A single shape/element on the slide."""
    block_id: str           # stable ID: "blk_01", "blk_02"
    var_name: str           # tag name (HTML) or code variable (legacy)
    shape_type: str         # textbox, shape, picture, table, chart, title
    css_selector: str = ""  # CSS selector to locate in code: "#id" or ".class" or "tag"
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    text_chars: int = 0     # total chars of text content
    text_capacity: int = 0  # kept for schema compat; 0 = not estimated
    utilization: float = 0.0  # kept for schema compat; 0.0 = not estimated
    font_size_pt: float = 16.0
    code_line_start: int = 0
    code_line_end: int = 0
    text_lines: list[str] = field(default_factory=list)
    # Playwright overflow data (accurate, from rendering engine)
    is_overflowing: bool = False
    overflow_bottom_px: int = 0
    overflow_right_px: int = 0
    # Contrast ratio (WCAG) — foreground vs background
    contrast_ratio: float = 0.0    # 0 = not computed (e.g. image)
    fg_color: str = ""             # e.g. "rgb(255,255,255)"
    bg_color: str = ""             # e.g. "rgb(0,51,102)"
    # Rendered line count (from getClientRects)
    rendered_lines: int = 0
    # overflow:hidden clipping detection
    is_clipped: bool = False       # content clipped by overflow:hidden
    clipped_bottom_px: int = 0
    # Image loading status
    img_broken: bool = False       # True if <img> failed to load
    img_src: str = ""              # src attribute
    # z-index for occlusion analysis
    z_index: int = 0
    # Raw px data — for agent CSS editing (no unit conversion needed)
    bbox_px: tuple[int, int, int, int] = (0, 0, 0, 0)  # (x, y, w, h) in CSS px
    client_w_px: int = 0       # clientWidth (visible content area)
    client_h_px: int = 0       # clientHeight (visible content area)
    scroll_w_px: int = 0       # scrollWidth (full content width)
    scroll_h_px: int = 0       # scrollHeight (full content height)
    font_size_px: float = 0.0  # CSS font-size in px (not pt)
    # Blind-spot detection fields
    is_ellipsized: bool = False        # text-overflow:ellipsis truncation
    has_clip_path: bool = False        # CSS clip-path active
    effective_font_size_px: float = 0.0  # font-size * transform scale factor
    img_crop_pct: float = 0.0         # % of image content cropped by object-fit:cover
    dom_path: str = ""                # DOM path for parent-child relationship detection


@dataclass
class AlignmentIssue:
    """A detected alignment deviation between visually adjacent elements."""
    block_a: str
    block_b: str
    edge: str           # "left", "right", "top", "bottom", "center_x", "center_y"
    deviation: float    # deviation in inches
    suggestion: str     # actionable fix suggestion


@dataclass
class SlideState:
    """Structured spatial state for one slide."""
    slide_id: int
    blocks: list[ContentBlock] = field(default_factory=list)
    total_area: float = 0.0
    used_area: float = 0.0
    free_area: float = 0.0
    overlap_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    coord_overlap_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    overflow_blocks: list[str] = field(default_factory=list)
    oob_blocks: list[str] = field(default_factory=list)
    alignment_issues: list[AlignmentIssue] = field(default_factory=list)
    # New: low-contrast blocks (WCAG AA requires ≥4.5:1 for normal text, ≥3:1 for large)
    low_contrast_blocks: list[str] = field(default_factory=list)
    # New: clipped blocks (content hidden by overflow:hidden)
    clipped_blocks: list[str] = field(default_factory=list)
    # New: broken images
    broken_images: list[str] = field(default_factory=list)
    # New: z-index occlusion pairs (front_id, back_id) where front fully covers back
    occlusion_pairs: list[tuple[str, str]] = field(default_factory=list)
    # New: viewport exceedances — elements (incl. empty divs) that exceed canvas bounds
    viewport_exceedances: list[dict] = field(default_factory=list)


def format_spatial_state(state: SlideState) -> str:
    """Format SlideState as LLM-readable text for repair agent prompt."""
    lines = [
        f"## Slide {state.slide_id} Spatial State",
        f"Slide: {SLIDE_WIDTH}\" x {SLIDE_HEIGHT}\" "
        f"(usable: {USABLE_LEFT:.2f}\"-{USABLE_RIGHT:.2f}\" x "
        f"{USABLE_TOP:.2f}\"-{USABLE_BOTTOM:.2f}\")",
        "",
        "Blocks:",
    ]

    for b in state.blocks:
        status = "OK"
        if b.block_id in state.overflow_blocks:
            # Use Playwright overflow data if available
            ovf_info = ""
            if b.overflow_bottom_px > 0 or b.overflow_right_px > 0:
                parts = []
                if b.overflow_bottom_px > 0:
                    parts.append(f"{b.overflow_bottom_px}px tall")
                if b.overflow_right_px > 0:
                    parts.append(f"{b.overflow_right_px}px wide")
                ovf_info = f" ({', '.join(parts)} beyond container)"
            status = f"OVERFLOW{ovf_info}"
        if b.block_id in state.oob_blocks:
            status = "OOB"

        text_info = ""
        if b.text_chars > 0:
            text_info = f" | {b.text_chars} chars"

        lines.append(
            f"  {b.block_id}  {b.var_name:20s} [{b.shape_type:7s}]  "
            f"x={b.x:.2f}  y={b.y:.2f}  w={b.w:.2f}  h={b.h:.2f}"
            f"{text_info}  {status}"
        )

    lines.append("")

    if state.overlap_pairs:
        overlap_strs = [f"{a} x {b} ({area:.2f} sq.in.)" for a, b, area in state.overlap_pairs]
        lines.append(f"Overlaps: {'; '.join(overlap_strs)}")
    else:
        lines.append("Overlaps: none")

    if state.overflow_blocks:
        for blk_id in state.overflow_blocks:
            blk = next((b for b in state.blocks if b.block_id == blk_id), None)
            if blk:
                parts = []
                if blk.overflow_bottom_px > 0:
                    parts.append(f"{blk.overflow_bottom_px}px below")
                if blk.overflow_right_px > 0:
                    parts.append(f"{blk.overflow_right_px}px right")
                overflow_detail = ", ".join(parts) if parts else "content exceeds container"
                lines.append(
                    f"Overflow: {blk_id} ({blk.var_name}) — {overflow_detail}"
                )
    else:
        lines.append("Overflow: none")

    if state.oob_blocks:
        lines.append(f"Out-of-bounds: {', '.join(state.oob_blocks)}")
    else:
        lines.append("Out-of-bounds: none")

    if state.low_contrast_blocks:
        for blk_id in state.low_contrast_blocks:
            blk = next((b for b in state.blocks if b.block_id == blk_id), None)
            if blk:
                lines.append(
                    f"Low contrast: {blk_id} ({blk.var_name}) — "
                    f"ratio {blk.contrast_ratio:.1f}:1, fg={blk.fg_color}, bg={blk.bg_color}"
                )

    if state.clipped_blocks:
        for blk_id in state.clipped_blocks:
            blk = next((b for b in state.blocks if b.block_id == blk_id), None)
            if blk:
                lines.append(
                    f"Clipped: {blk_id} ({blk.var_name}) — "
                    f"{blk.clipped_bottom_px}px hidden by overflow:hidden"
                )

    if state.broken_images:
        for blk_id in state.broken_images:
            blk = next((b for b in state.blocks if b.block_id == blk_id), None)
            if blk:
                lines.append(f"Broken image: {blk_id} — src={blk.img_src}")

    if state.occlusion_pairs:
        for front_id, back_id in state.occlusion_pairs:
            lines.append(f"Occluded: {back_id} hidden behind {front_id}")

    lines.append(f"Free area: {state.free_area:.1f} sq.in. ({state.free_area/max(state.total_area, 0.01):.0%} of usable)")

    return "\n".join(lines)


def format_checkpoint_result(state: SlideState) -> str:
    """Format spatial state as checkpoint verification feedback.

    Returns detailed per-block violation info with actionable fix suggestions.
    Uses Playwright-provided overflow data (no estimation).
    """
    violations = []

    # Overlaps
    block_map = {b.block_id: b for b in state.blocks}
    for a_id, b_id, area in state.overlap_pairs:
        a = block_map.get(a_id)
        b = block_map.get(b_id)
        if a and b:
            ax, ay, aw, ah = a.bbox_px
            bx, by, bw, bh = b.bbox_px
            ovl_top = max(ay, by)
            ovl_bottom = min(ay + ah, by + bh)
            ovl_v_px = max(0, ovl_bottom - ovl_top)

            violations.append(
                f"  [OVERLAP] {a_id} ({a.var_name}) ↔ {b_id} ({b.var_name})\n"
                f"    A: ({ax}, {ay}, {aw}×{ah}) px   B: ({bx}, {by}, {bw}×{bh}) px\n"
                f"    vertical overlap: {ovl_v_px}px"
            )

    # Overflow — use Playwright data
    for blk_id in state.overflow_blocks:
        blk = block_map.get(blk_id)
        if blk:
            bx, by, bw, bh = blk.bbox_px
            violations.append(
                f"  [OVERFLOW] {blk_id} ({blk.var_name})\n"
                f"    scrollHeight: {blk.scroll_h_px}px | clientHeight: {blk.client_h_px}px | "
                f"overflow: {blk.overflow_bottom_px}px vertical\n"
                f"    scrollWidth: {blk.scroll_w_px}px | clientWidth: {blk.client_w_px}px | "
                f"overflow: {blk.overflow_right_px}px horizontal\n"
                f"    font-size: {blk.font_size_px}px | bbox: ({bx}, {by}, {bw}×{bh}) px"
            )

    # Out-of-bounds
    for blk_id in state.oob_blocks:
        blk = block_map.get(blk_id)
        if blk:
            bx, by, bw, bh = blk.bbox_px
            parts = []
            if bx + bw > SlideDimensions.VIEWPORT_W + 5:
                parts.append(f"right {bx+bw}px > {SlideDimensions.VIEWPORT_W}px")
            if by + bh > SlideDimensions.VIEWPORT_H + 5:
                parts.append(f"bottom {by+bh}px > {SlideDimensions.VIEWPORT_H}px")
            if bx < -5:
                parts.append(f"left {bx}px < 0")
            if by < -5:
                parts.append(f"top {by}px < 0")
            violations.append(
                f"  [OOB] {blk_id} ({blk.var_name}): bbox ({bx}, {by}, {bw}×{bh}) px — {'; '.join(parts)}"
            )

    if not violations:
        return "## Checkpoint Verification Result\n\nStatus: ALL CLEAN - no violations found.\n"

    clean_blocks = [
        b.block_id for b in state.blocks
        if b.block_id not in state.overflow_blocks
        and b.block_id not in state.oob_blocks
        and not any(b.block_id in (a, c) for a, c, _ in state.overlap_pairs)
    ]

    result = [
        "## Checkpoint Verification Result",
        f"\nStatus: {len(violations)} violation(s) found\n",
        "Violations:",
    ]
    result.extend(violations)
    result.append("")
    if clean_blocks:
        result.append(f"Clean blocks (do NOT touch): {', '.join(clean_blocks)}")

    return "\n".join(result)
