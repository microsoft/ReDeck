"""Slide Manifest — structured slide analysis for constraint-aware refinement.

This module provides the foundation for repair dispatch:

1. SlideManifest: rich structured per-slide representation combining
   spatial state, text budgets, evidence bindings, and mutability annotations
2. TextBudget: per-block capacity analysis telling the LLM exactly how
   much text can fit BEFORE generation (not as post-hoc rejection)
3. triage_slide(): typed action decision (keep/text_fix/re_layout/regenerate)
   routing each slide to the appropriate repair strategy

The manifest separates concerns:
- LLM handles semantic decisions (what to include, how to phrase)
- External systems handle spatial control (where to place, how to size)
"""

import logging
from dataclasses import dataclass, field

from ...schemas.issue import Issue
from ...schemas.blueprint import BlueprintSlide
from ...schemas.evidence import EvidenceState
from .spatial_state import (
    ContentBlock,
    SlideState,
    AlignmentIssue,
    SLIDE_WIDTH,
    SLIDE_HEIGHT,
    USABLE_LEFT,
    USABLE_RIGHT,
    USABLE_TOP,
    USABLE_BOTTOM,
)

logger = logging.getLogger(__name__)


# Issue types that cannot be solved by single-slide repair.
# These require cross-slide coordination or fundamentally different
# visual assets (charts, images) that text/layout repair cannot provide.
from ...schemas.issue_types import UNSOLVABLE_TYPES as UNSOLVABLE_ISSUE_TYPES

# Minimum T0 issues per slide to justify regeneration.
# Constraint-aware regeneration is safe, so threshold is low.
# text_fix_only has NO threshold (always safe).
MIN_ISSUES_FOR_REPAIR = 3

# Content issue families — these are fixable by TEXT_FIX with positive ROI
CONTENT_ISSUE_FAMILIES = {"A", "C", "D", "E"}

# Spatial issue family — fixable by geometry changes only
SPATIAL_ISSUE_FAMILY = "B"


@dataclass
class TextBudget:
    """Per-block text capacity analysis.

    Tells the LLM exactly how much space is available BEFORE generation,
    so it can make length-neutral corrections without post-hoc rejection.
    """
    block_id: str
    var_name: str
    current_chars: int       # how many chars currently in this block
    max_chars: int           # maximum chars that fit at current font/size
    remaining_chars: int     # max_chars - current_chars (can be negative = overflow)
    utilization: float       # current_chars / max_chars
    status: str              # "ok" | "tight" | "overflow"
    max_additional_lines: int  # how many more lines can fit vertically
    neighbor_gap_below: float  # inches of vertical space to nearest block below


@dataclass
class VerticalSlot:
    """An occupied vertical interval on the slide."""
    block_id: str
    y_top: float
    y_bottom: float       # effective bottom (accounts for overflow)
    gap_to_next: float    # gap in inches to the next slot below (-1 if last)


@dataclass
class SlideManifest:
    """Rich structured representation of a slide for constraint-aware repair.

    Combines spatial state (from spatial_state.py, unchanged), text budgets,
    evidence bindings, mutability annotations, and repair decision.
    """
    slide_id: int

    # Semantic layer
    role: str = ""                                    # from blueprint: intro, method, result, etc.
    semantic_goal: str = ""                           # primary proposition

    # Spatial layer (from existing spatial_state.py — reuse unchanged)
    state: SlideState | None = None
    blocks: list[ContentBlock] = field(default_factory=list)
    overlap_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    overflow_blocks: list[str] = field(default_factory=list)
    oob_blocks: list[str] = field(default_factory=list)
    alignment_issues: list[AlignmentIssue] = field(default_factory=list)

    # Budget layer
    block_budgets: dict[str, TextBudget] = field(default_factory=dict)
    vertical_slots: list[VerticalSlot] = field(default_factory=list)

    # Mutability layer
    frozen_blocks: set[str] = field(default_factory=set)   # blocks that must NOT be modified
    mutable_blocks: set[str] = field(default_factory=set)  # blocks that CAN be modified

    # Decision layer
    repair_decision: str = "keep"    # "keep" | "text_fix_only" | "re_layout" | "regenerate"
    repair_reason: str = ""

    # Issue analysis
    total_issues: int = 0
    actionable_issues: int = 0
    content_issues: int = 0       # C/D/E family
    spatial_issues: int = 0       # B family
    high_churn_issues: int = 0    # filtered out


def build_manifest(
    slide_id: int,
    code: str,
    issues: list[Issue],
    bp_slide: BlueprintSlide | None = None,
) -> SlideManifest:
    """Build a rich slide manifest from code, issues, and blueprint.

    Combines:
    1. Spatial state extraction (reuses spatial_state.py)
    2. Per-block text budget computation
    3. Vertical slot analysis (gap constraints)
    4. Issue classification and mutability analysis
    5. Repair triage decision

    Args:
        slide_id: The slide number
        code: Current python-pptx code for this slide
        issues: All issues affecting this slide
        bp_slide: Blueprint slide (for semantic context)

    Returns:
        Complete SlideManifest with repair decision
    """
    manifest = SlideManifest(slide_id=slide_id)

    # 1. Semantic layer
    if bp_slide:
        manifest.role = bp_slide.role or ""
        manifest.semantic_goal = bp_slide.primary_proposition or ""

    # 2. Spatial layer (Playwright-based HTML extraction)
    from .html_spatial_state import extract_html_slide_state
    state = extract_html_slide_state(slide_id, code)
    manifest.state = state
    manifest.blocks = state.blocks
    manifest.overlap_pairs = state.overlap_pairs
    manifest.overflow_blocks = state.overflow_blocks
    manifest.oob_blocks = state.oob_blocks
    manifest.alignment_issues = state.alignment_issues or []

    # 3. Budget layer
    manifest.block_budgets = _compute_block_budgets(state)
    manifest.vertical_slots = _compute_vertical_slots(state)

    # 4. Issue classification
    _classify_issues(manifest, issues)

    # 5. Mutability analysis
    _compute_mutability(manifest, issues)

    # 6. Repair triage
    manifest.repair_decision, manifest.repair_reason = triage_slide(manifest, issues)

    return manifest


def _compute_block_budgets(state: SlideState) -> dict[str, TextBudget]:
    """Compute per-block text capacity budgets.

    For each block, determines:
    - How much text is currently in it
    - How much text can fit
    - How much room remains
    - Whether it's tight or overflowing
    - How much vertical gap exists to the next element below
    """
    budgets = {}
    sorted_blocks = sorted(state.blocks, key=lambda b: b.y)

    for i, block in enumerate(sorted_blocks):
        # Use Playwright overflow data instead of estimated utilization
        if block.is_overflowing:
            status = "overflow"
            remaining = 0
        else:
            remaining = max(0, block.text_capacity - block.text_chars) if block.text_capacity > 0 else 0
            status = "ok"

        # Compute gap to nearest block below (same x-range)
        gap_below = _compute_gap_below(block, sorted_blocks[i + 1:])

        # Estimate additional lines from remaining gap (approximate)
        line_height_px = max(block.font_size_pt / 0.75 * 1.4, 16)  # rough px
        line_height_in = line_height_px / 96  # px to inches approx
        expandable = min(gap_below - 0.10, 1.0) if gap_below > 0.15 else 0
        max_additional_lines = max(0, int(expandable / max(line_height_in, 0.1))) if block.h > 0 else 0

        budgets[block.block_id] = TextBudget(
            block_id=block.block_id,
            var_name=block.var_name,
            current_chars=block.text_chars,
            max_chars=block.text_capacity,
            remaining_chars=remaining,
            utilization=1.0 if block.is_overflowing else 0.0,
            status=status,
            max_additional_lines=max_additional_lines,
            neighbor_gap_below=gap_below,
        )

    return budgets


def _compute_gap_below(block: ContentBlock, blocks_below: list[ContentBlock]) -> float:
    """Compute vertical gap between a block and the nearest block below it.

    Uses actual block dimensions from Playwright (no estimation).
    """
    block_bottom = block.y + block.h

    min_gap = USABLE_BOTTOM - block_bottom  # default: gap to slide bottom

    for b in blocks_below:
        # Check horizontal overlap
        x_overlap = max(0, min(block.x + block.w, b.x + b.w) - max(block.x, b.x))
        if x_overlap > 0.1:  # significant horizontal overlap
            gap = b.y - block_bottom
            if gap < min_gap:
                min_gap = gap

    return max(0, min_gap)


def _compute_vertical_slots(state: SlideState) -> list[VerticalSlot]:
    """Compute ordered vertical intervals for all blocks.

    Returns sorted list of VerticalSlots showing occupied intervals
    and gaps between them.
    """
    if not state.blocks:
        return []

    sorted_blocks = sorted(state.blocks, key=lambda b: b.y)
    slots = []

    for i, block in enumerate(sorted_blocks):
        y_bottom = block.y + block.h

        # Gap to next block
        if i + 1 < len(sorted_blocks):
            gap = sorted_blocks[i + 1].y - y_bottom
        else:
            gap = USABLE_BOTTOM - y_bottom

        slots.append(VerticalSlot(
            block_id=block.block_id,
            y_top=block.y,
            y_bottom=y_bottom,
            gap_to_next=max(0, gap),
        ))

    return slots


def _classify_issues(manifest: SlideManifest, issues: list[Issue]) -> None:
    """Classify issues into content/spatial/high-churn categories."""
    for issue in issues:
        if issue.status.value != "open":
            continue

        manifest.total_issues += 1
        itype = issue.issue_type
        fam = issue.rubric_id[0].upper() if issue.rubric_id else "?"

        if itype in UNSOLVABLE_ISSUE_TYPES:
            manifest.high_churn_issues += 1
        else:
            manifest.actionable_issues += 1
            if fam in CONTENT_ISSUE_FAMILIES:
                manifest.content_issues += 1
            elif fam == SPATIAL_ISSUE_FAMILY:
                manifest.spatial_issues += 1


def _compute_mutability(manifest: SlideManifest, issues: list[Issue]) -> None:
    """Determine which blocks are mutable vs frozen.

    A block is mutable if at least one issue references it.
    All other blocks are frozen (must not be modified to prevent
    collateral damage).
    """
    # Collect block IDs referenced by issues
    issue_block_ids = set()
    for issue in issues:
        if issue.status.value != "open":
            continue
        # Check if issue mentions any block variable names
        desc = (issue.evidence.description or "") + " " + (issue.why_this_fails or "")
        for block in manifest.blocks:
            if block.var_name in desc or block.block_id in desc:
                issue_block_ids.add(block.block_id)

    # Also mark overflow/oob blocks as mutable (they need fixing)
    for blk_id in manifest.overflow_blocks:
        issue_block_ids.add(blk_id)
    for blk_id in manifest.oob_blocks:
        issue_block_ids.add(blk_id)

    # If an issue mentions block A overlapping block B, both are mutable
    for a_id, b_id, _ in manifest.overlap_pairs:
        issue_block_ids.add(a_id)
        issue_block_ids.add(b_id)

    manifest.mutable_blocks = issue_block_ids
    manifest.frozen_blocks = {
        b.block_id for b in manifest.blocks
    } - issue_block_ids


def is_containment_overlap(
    block_a: ContentBlock, block_b: ContentBlock, tolerance: float = 0.10,
) -> bool:
    """Check if one block intentionally contains the other (parent-child pattern).

    Returns True if:
    - A's bounding box fully encloses B (A is parent container, B is child element)
    - B's bounding box fully encloses A (B is parent container, A is child element)
    - A and B are at the same position (decorative overlay, border shape)

    These are NOT real spatial conflicts — they are intentional layout patterns
    like "card shape containing bullet text" or "border shape overlaying content".

    Analysis shows 73% of all overlaps across 10 cases are containment patterns.
    """
    # A contains B
    a_contains_b = (
        block_a.x <= block_b.x + tolerance
        and block_a.y <= block_b.y + tolerance
        and block_a.x + block_a.w >= block_b.x + block_b.w - tolerance
        and block_a.y + block_a.h >= block_b.y + block_b.h - tolerance
    )
    # B contains A
    b_contains_a = (
        block_b.x <= block_a.x + tolerance
        and block_b.y <= block_a.y + tolerance
        and block_b.x + block_b.w >= block_a.x + block_a.w - tolerance
        and block_b.y + block_b.h >= block_a.y + block_a.h - tolerance
    )
    # Same position (decorative overlay, border shape)
    same_pos = (
        abs(block_a.x - block_b.x) < 0.15
        and abs(block_a.y - block_b.y) < 0.15
        and abs(block_a.w - block_b.w) < 0.3
        and abs(block_a.h - block_b.h) < 0.3
    )
    return a_contains_b or b_contains_a or same_pos


def filter_containment_overlaps(
    slide_id: int,
    code: str,
    issues: list[Issue],
    state: SlideState | None = None,
) -> list[Issue]:
    """Filter out issues caused by containment overlap false positives.

    The evaluator flags ALL overlapping shapes as issues, but many are
    intentional parent-child patterns (card containing bullets, border
    overlaying content). This function removes those false positives
    before sending issues to the repair LLM.

    Returns a filtered list of issues (only real issues).
    """
    if state is None:
        from .html_spatial_state import extract_html_slide_state
        state = extract_html_slide_state(slide_id, code)

    # Build block map for overlap pair lookup
    block_map = {b.block_id: b for b in state.blocks}

    # Identify which overlap pairs are containment (false positives)
    containment_pairs: set[tuple[str, str]] = set()
    real_overlap_pairs: set[tuple[str, str]] = set()

    for a_id, b_id, _area in state.overlap_pairs:
        a = block_map.get(a_id)
        b = block_map.get(b_id)
        if a and b and is_containment_overlap(a, b):
            containment_pairs.add((a_id, b_id))
        else:
            real_overlap_pairs.add((a_id, b_id))

    if containment_pairs:
        logger.info(
            "Slide %d: %d/%d overlaps are containment (filtered), %d real",
            slide_id,
            len(containment_pairs),
            len(state.overlap_pairs),
            len(real_overlap_pairs),
        )

    # Filter issues: keep all non-overlap issues, and only real overlap issues
    filtered = []
    for issue in issues:
        if issue.status.value != "open":
            continue

        # Keep non-overlap issues as-is
        if issue.issue_type != "overlap":
            filtered.append(issue)
            continue

        # For overlap issues: check if the issue references only containment pairs
        # The issue description may mention block IDs or just describe the overlap
        # Conservatively: if ALL overlap pairs on this slide are containment,
        # skip the overlap issue. If any are real, keep it.
        if real_overlap_pairs:
            filtered.append(issue)
        # else: all overlaps are containment → skip this overlap issue

    return filtered


def triage_slide(manifest: SlideManifest, issues: list[Issue]) -> tuple[str, str]:
    """Decide repair action type for a slide.

    v5 redesign: simplified to binary keep/repair.

    Returns (action, reason) where action is one of:
    - "keep": Don't touch (only unsolvable issues or no actionable issues)
    - "repair": Send to LLM for unified code-diff repair
    """
    open_issues = [i for i in issues if i.status.value == "open"]

    if not open_issues:
        return "keep", "no open issues"

    # Filter unsolvable issue types
    actionable = [
        i for i in open_issues
        if i.issue_type not in UNSOLVABLE_ISSUE_TYPES
    ]

    if not actionable:
        return "keep", f"all {len(open_issues)} issues are unsolvable types"

    return "repair", f"{len(actionable)} actionable issues"


def format_manifest_summary(manifest: SlideManifest) -> str:
    """Format manifest as human-readable summary for logging."""
    lines = [
        f"Slide {manifest.slide_id} Manifest:",
        f"  Role: {manifest.role}",
        f"  Issues: {manifest.total_issues} total, "
        f"{manifest.actionable_issues} actionable, "
        f"{manifest.high_churn_issues} filtered",
        f"  Content/Spatial: {manifest.content_issues}C / {manifest.spatial_issues}S",
        f"  Blocks: {len(manifest.blocks)} total, "
        f"{len(manifest.mutable_blocks)} mutable, "
        f"{len(manifest.frozen_blocks)} frozen",
        f"  Overlaps: {len(manifest.overlap_pairs)}",
        f"  Overflows: {len(manifest.overflow_blocks)}",
        f"  Alignment issues: {len(manifest.alignment_issues)}",
        f"  Decision: {manifest.repair_decision} ({manifest.repair_reason})",
    ]

    # Budget summary for text blocks
    tight_or_overflow = [
        b for b in manifest.block_budgets.values()
        if b.status in ("tight", "overflow")
    ]
    if tight_or_overflow:
        lines.append("  Budget warnings:")
        for b in tight_or_overflow:
            lines.append(
                f"    {b.block_id} ({b.var_name}): "
                f"{b.current_chars}/{b.max_chars} chars "
                f"({b.utilization:.0%}), {b.remaining_chars} remaining "
                f"[{b.status.upper()}]"
            )

    return "\n".join(lines)


def format_budget_constraints(manifest: SlideManifest) -> str:
    """Format text budgets as LLM prompt constraints.

    This is the KEY innovation: budget constraints enter the prompt BEFORE
    generation, so the LLM knows exactly how much text can fit.
    Previously, this was only post-hoc rejection (length guard, overflow check).
    """
    lines = ["## Text Budget Constraints (MUST obey)\n"]
    has_constraints = False

    for block in manifest.blocks:
        budget = manifest.block_budgets.get(block.block_id)
        if not budget or budget.current_chars == 0:
            continue

        has_constraints = True

        if budget.status == "overflow":
            lines.append(
                f"- **{budget.block_id}** ({budget.var_name}): "
                f"OVERFLOW — {budget.current_chars} chars but only {budget.max_chars} fit. "
                f"You MUST remove at least {-budget.remaining_chars} chars. "
                f"Any replacement text must be SHORTER than original."
            )
        elif budget.status == "tight":
            lines.append(
                f"- **{budget.block_id}** ({budget.var_name}): "
                f"TIGHT — {budget.remaining_chars} chars remaining. "
                f"Replacement text must be same length or shorter."
            )
        else:
            lines.append(
                f"- **{budget.block_id}** ({budget.var_name}): "
                f"OK — {budget.remaining_chars} chars available. "
                f"Replacement text may be up to {budget.remaining_chars} chars longer."
            )

    if not has_constraints:
        return ""

    lines.append("")
    lines.append(
        "CRITICAL: Exceeding a block's text budget causes visual overflow, "
        "which makes text extend beyond the box boundary and visually collide "
        "with neighboring elements. This is the #1 cause of repair-introduced "
        "issues (93% of new overlaps). ALWAYS respect the budget."
    )
    return "\n".join(lines)


def format_constraint_spec(manifest: SlideManifest) -> str:
    """Format spatial constraints for constraint-spec regeneration.

    Generates the constraint specification that the codegen LLM must satisfy
    when regenerating a slide. Each block gets explicit position bounds and
    text capacity limits.
    """
    lines = ["## Spatial Constraints (MUST satisfy ALL)\n"]

    lines.append(f"Slide dimensions: {SLIDE_WIDTH}\" × {SLIDE_HEIGHT}\"")
    lines.append(
        f"Usable area: x=[{USABLE_LEFT:.2f}, {USABLE_RIGHT:.2f}], "
        f"y=[{USABLE_TOP:.2f}, {USABLE_BOTTOM:.2f}]"
    )
    lines.append("Minimum gap between shapes: 0.10\"")
    lines.append("")

    # Per-block constraints from vertical slots
    lines.append("### Block Position Constraints\n")
    for slot in manifest.vertical_slots:
        block = next((b for b in manifest.blocks if b.block_id == slot.block_id), None)
        if not block:
            continue

        budget = manifest.block_budgets.get(slot.block_id)
        max_chars = budget.max_chars if budget else 0

        lines.append(
            f"- **{slot.block_id}** ({block.var_name}, {block.shape_type}):"
        )
        lines.append(
            f"  Position: x={block.x:.2f}, y={slot.y_top:.2f}, "
            f"w={block.w:.2f}, h_max={slot.y_bottom - slot.y_top:.2f}"
        )
        if max_chars > 0:
            line_note = ""
            if "title" in slot.block_id.lower() and max_chars <= 50:
                line_note = " (MUST be single line — keep short)"
            lines.append(f"  Text budget: max {max_chars} chars at {block.font_size_pt:.0f}pt{line_note}")
        if slot.gap_to_next >= 0:
            lines.append(f"  Gap below: {slot.gap_to_next:.2f}\"")
        lines.append("")

    # Global constraints
    lines.append("### Global Constraints\n")
    lines.append("1. No block may overlap any other block (0.10\" minimum gap)")
    lines.append("2. All blocks must be within usable area")
    lines.append("3. Text must fit within block dimensions (no overflow)")
    lines.append(
        "4. Preserve visual balance: similar-sized blocks should have "
        "similar text density"
    )
    lines.append(
        "5. Use the FULL usable vertical space (y=0.25 to y=7.10). "
        "Content should be distributed evenly — avoid bunching all "
        "content in the top third with empty space below."
    )
    lines.append(
        "6. NEVER include meta-commentary about the slide itself. "
        "Every text element must contain concrete facts, data, or claims."
    )

    return "\n".join(lines)
