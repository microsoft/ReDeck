#!/usr/bin/env python3
"""
ReDeck Repair — Fix spatial issues in HTML slides using AgentRepair.

Uses ReDeck's spatial detection to find issues, then runs the AgentRepair
tool-calling loop (plan → apply_edits → verify_layout → submit) to fix them.

Usage:
    python scripts/redeck_repair.py slide_01.html
    python scripts/redeck_repair.py --dir ./slides/ --output-dir ./repaired/
    python scripts/redeck_repair.py slide.html --model gpt-5.4
"""
import sys
import re
import json
import argparse
import logging
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm_client import LLMClient
from app.modules.redeck.html_spatial_state import extract_html_slide_state
from app.modules.redeck.agent_repair import AgentRepair
from app.schemas.issue import Issue, IssueEvidence
from app.schemas.common import Severity, Confidence, Verdict
from app.schemas.blueprint import BlueprintSlide
from app.schemas.evidence import EvidenceState

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)


def _is_svg_element(block):
    """Check if a block is an SVG internal element (not actionable by CSS edits)."""
    if not block:
        return False
    sel = (block.css_selector or "").lower()
    bid = (block.block_id or "").lower()
    svg_tags = {"svg", "g", "path", "rect", "text", "line", "circle",
                "ellipse", "polygon", "polyline", "tspan", "use", "col", "colgroup"}
    tag = sel.split(".")[-1].split("[")[0].split(":")[0].strip()
    return tag in svg_tags or "svg" in bid or "svg" in sel


def _is_container_element(block):
    """Check if a block is a structural/container element with no visual content of its own.
    These elements naturally overlap with their children or siblings and should not
    be reported as defects."""
    if not block:
        return False
    sel = (block.css_selector or "").lower()
    bid = (block.block_id or "").lower()
    # SVG containers, table structure elements, and generic SVG shapes
    container_tags = {"svg", "g", "col", "colgroup", "path", "rect",
                      "ellipse", "polygon", "polyline", "line", "circle", "use"}
    tag = sel.split(".")[-1].split("[")[0].split(":")[0].strip()
    return tag in container_tags or "svg" in bid


# Thresholds for filtering noise / false positives
MIN_OVERLAP_AREA_FRAC = 0.05   # ignore overlaps < 5% of smaller element
MIN_OOB_EXCESS_PX = 5          # ignore OOB ≤ 5px past canvas edge
MIN_CLIP_PX = 8                # ignore clips < 8px (sub-pixel rounding, minor font overflow)
MIN_OVERFLOW_PX = 8            # ignore overflows ≤ 8px


def count_issues(state):
    """Count hard spatial defects, filtering noise.

    Thin wrapper over the single source of truth
    (app.modules.redeck.html_spatial_state.count_significant_issue_total) so that
    this external scorer, the agent's submit gate, the stagnation trigger, and
    best-state tracking all agree byte-for-byte on what counts as an issue.
    The legacy inline implementation lived here and was duplicated (divergently)
    inside agent_repair.py — that divergence is the bug this consolidation fixes.
    """
    from app.modules.redeck.html_spatial_state import count_significant_issue_total
    return count_significant_issue_total(state)


def _count_issues_legacy(state):
    """Deprecated legacy implementation, retained only for the SSOT parity test.
    Do not call from production code — use count_issues (the SSOT wrapper)."""
    canvas_w, canvas_h = 1280, 720
    n = 0
    for a_id, b_id, area in state.overlap_pairs:
        a_blk = next((b for b in state.blocks if b.block_id == a_id), None)
        b_blk = next((b for b in state.blocks if b.block_id == b_id), None)
        # Skip if either side is a structural/container element (SVG, col, etc.)
        if _is_container_element(a_blk) or _is_container_element(b_blk):
            continue
        if area < MIN_OVERLAP_AREA_FRAC:
            continue
        n += 1
    for bid in state.overflow_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if not blk:
            continue
        if blk.overflow_bottom_px <= MIN_OVERFLOW_PX:
            continue
        # Skip non-text elements (decorative blocks, pseudo-element overflow)
        if not blk.text_lines and not (isinstance(blk.text_chars, str) and blk.text_chars.strip()):
            if isinstance(blk.text_chars, int) and blk.text_chars == 0:
                continue
        if _is_container_element(blk):
            continue
        n += 1
    for bid in state.oob_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if blk:
            bx, by, bw, bh = blk.bbox_px
            right_excess = max(0, bx + bw - canvas_w)
            bottom_excess = max(0, by + bh - canvas_h)
            if right_excess <= MIN_OOB_EXCESS_PX and bottom_excess <= MIN_OOB_EXCESS_PX:
                continue
        n += 1
    for bid in state.clipped_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if not blk:
            continue
        if blk.clipped_bottom_px < MIN_CLIP_PX:
            continue
        # Skip SVG elements (path/rect/g) — structural, not content
        if _is_container_element(blk):
            continue
        # Skip chart-internal elements with minor clips (labels, axis text)
        if (getattr(blk, 'shape_type', None) == 'chart'
                and blk.clipped_bottom_px <= 15
                and (blk.text_chars or 0) <= 20):
            continue
        # Skip decorative punctuation-only elements with minor clips (e.g. "...", "→", "•")
        # These are structural/decorative glyphs, not real content truncation.
        # Only skip if text is purely punctuation/symbols — never skip alphanumeric content.
        import re as _re
        _text_joined = " ".join((blk.text_lines or []))
        if ((blk.text_chars or 0) <= 5
                and blk.clipped_bottom_px <= 10
                and blk.text_lines
                and not _re.search(r'[a-zA-Z0-9]', _text_joined)):
            continue
        # Note: we do NOT skip "false clips" (scroll_h <= client_h) because
        # overflow:hidden causes scrollHeight to be clamped to clientHeight,
        # making scroll==client even when content IS clipped. The
        # clipped_bottom_px field (already checked > MIN_CLIP_PX above)
        # is a more reliable signal from visual bounds comparison.
        n += 1
    # Occlusion: skip SVG/container elements occluding others (structural layering)
    for front, back in state.occlusion_pairs:
        front_blk = next((b for b in state.blocks if b.block_id == front), None)
        if _is_container_element(front_blk):
            continue
        n += 1
    # Canvas-edge content truncation: elements whose bbox reaches canvas bottom
    # but have content (scrollHeight) extending beyond what fits in the visible
    # portion. This catches cases where child elements are entirely off-canvas.
    seen_clipped = set(state.clipped_blocks)  # avoid double-counting
    for blk in state.blocks:
        if blk.block_id in seen_clipped:
            continue
        if _is_container_element(blk):
            continue
        bx, by, bw, bh = blk.bbox_px
        bottom_px = by + bh
        if bottom_px < canvas_h - 2:  # not at canvas edge
            continue
        # Element touches canvas bottom — check if it has more content
        visible_h = max(1, canvas_h - by)  # how much of element is in canvas
        scroll_h = blk.scroll_h_px or 0
        excess = scroll_h - visible_h
        # Also check font-size vs visible height — descenders cut by canvas
        font_px = blk.font_size_px or 0
        font_excess = font_px * 1.2 - visible_h
        effective_excess = max(excess, font_excess)
        if effective_excess >= MIN_CLIP_PX and blk.text_lines:
            n += 1
    return n


def build_issues_from_state(state, slide_id: int) -> list[Issue]:
    """Convert spatial state violations into Issue objects for AgentRepair."""
    issues = []
    idx = 0
    canvas_w, canvas_h = 1280, 720  # standard slide canvas

    for a_id, b_id, area in state.overlap_pairs:
        a_blk = next((b for b in state.blocks if b.block_id == a_id), None)
        b_blk = next((b for b in state.blocks if b.block_id == b_id), None)
        # Skip if either side is a structural/container element (SVG, col, etc.)
        if _is_container_element(a_blk) or _is_container_element(b_blk):
            continue
        # Skip tiny overlaps (< 5% of smaller element)
        if area < MIN_OVERLAP_AREA_FRAC:
            continue
        desc = f"Elements '{a_id}' and '{b_id}' overlap"
        fix = f"Move {b_id} away from {a_id} to eliminate overlap"
        # If one side is SVG, tell agent to move the non-SVG element
        a_svg = _is_svg_element(a_blk)
        b_svg = _is_svg_element(b_blk)
        if a_svg and not b_svg:
            fix = f"Move {b_id} away from SVG element {a_id} (do NOT edit SVG internals)"
        elif b_svg and not a_svg:
            fix = f"Move {a_id} away from SVG element {b_id} (do NOT edit SVG internals)"
        if a_blk and b_blk:
            ax, ay, aw, ah = a_blk.bbox_px
            bx, by, bw, bh = b_blk.bbox_px
            # Calculate exact overlap amount
            ox = max(0, min(ax+aw, bx+bw) - max(ax, bx))
            oy = max(0, min(ay+ah, by+bh) - max(ay, by))
            desc += (f". A at ({ax},{ay},{aw}x{ah}), B at ({bx},{by},{bw}x{bh}). "
                     f"Overlap region: {ox}x{oy}px")
            if by < ay + ah:
                fix = (f"Use the overlap geometry as evidence, not as a fixed pixel command. "
                       f"If this is an isolated collision, move the smaller/local element just enough "
                       f"to create readable separation. If that move crowds another element, restructure "
                       f"the shared parent region: preserve every visible string, reading order, and "
                       f"element role while giving the affected items explicit tracks/gaps that fit.")
            else:
                fix = (f"Use the overlap geometry as evidence, not as a fixed pixel command. "
                       f"If this is isolated, move the local element just enough to create readable "
                       f"separation. If moving causes new overlaps, restructure the shared region while "
                       f"preserving all visible strings, reading order, and element roles.")
        issues.append(Issue(
            issue_id=f"spatial_{idx}", rubric_id="B03", issue_type="overlap",
            severity=Severity.MAJOR, confidence=Confidence.HIGH,
            affected_slides=[slide_id],
            evidence=IssueEvidence(description=desc),
            why_this_fails="Overlapping elements make text unreadable",
            planned_fix=fix,
            verdict=Verdict.FAIL,
        ))
        idx += 1

    for bid in state.overflow_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if not blk:
            continue
        # Skip minor overflows
        if blk.overflow_bottom_px <= MIN_OVERFLOW_PX:
            continue
        # Skip non-text elements (decorative blocks, pseudo-element overflow)
        if not blk.text_lines and not (isinstance(blk.text_chars, str) and blk.text_chars.strip()):
            if isinstance(blk.text_chars, int) and blk.text_chars == 0:
                continue
        if _is_container_element(blk):
            continue
        desc = f"Element '{bid}' has text overflow"
        fix = "Reduce font-size or increase container height"
        if blk:
            overflow_px = int(blk.overflow_bottom_px)
            desc += (f" — scrollHeight={blk.scroll_h_px}px vs "
                     f"clientHeight={blk.client_h_px}px, "
                     f"overflow={overflow_px}px vertical")
            fix = (f"The {overflow_px}px overflow identifies the visible fit deficit; "
                   f"do not treat it as a literal pixel recipe. If the element is "
                   f"isolated, give its parent real visible space or rebalance nearby "
                   f"tracks/padding. If several siblings in the same body/lower region "
                   f"also overflow, use a regional/body reflow instead of repeatedly "
                   f"shrinking fonts or hiding content.")
        issues.append(Issue(
            issue_id=f"spatial_{idx}", rubric_id="B04",
            issue_type="text_overflow", severity=Severity.MAJOR,
            confidence=Confidence.HIGH, affected_slides=[slide_id],
            evidence=IssueEvidence(description=desc),
            why_this_fails="Overflowing text is hidden from view",
            planned_fix=fix, verdict=Verdict.FAIL,
        ))
        idx += 1

    for bid in state.oob_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        # Skip minor OOB (≤ 5px past canvas edge)
        if blk:
            bx, by, bw, bh = blk.bbox_px
            right_excess = max(0, int(bx + bw - canvas_w))
            bottom_excess = max(0, int(by + bh - canvas_h))
            if right_excess <= MIN_OOB_EXCESS_PX and bottom_excess <= MIN_OOB_EXCESS_PX:
                continue
        desc = f"Element '{bid}' extends beyond {canvas_w}x{canvas_h}px canvas"
        fix = f"Reposition to fit within {canvas_w}x{canvas_h}px"
        if blk:
            bx, by, bw, bh = blk.bbox_px
            right_excess = max(0, int(bx + bw - canvas_w))
            bottom_excess = max(0, int(by + bh - canvas_h))
            desc += f" — bbox ({bx},{by},{bw}x{bh})"
            fixes = []
            if right_excess > 0:
                desc += f". Right edge exceeds canvas by {right_excess}px"
                fixes.append(
                    "right edge is outside the canvas; if isolated, shift/rebalance "
                    "the local region, otherwise reflow the owning grid/track"
                )
            if bottom_excess > 0:
                desc += f". Bottom edge exceeds canvas by {bottom_excess}px"
                if by > 680:  # element starts very near bottom
                    fixes.append(
                        f"element starts at y={by}px near the canvas bottom. This "
                        f"usually indicates lower-region or body-track pressure; "
                        f"change the owning region's layout rather than moving footer/source "
                        f"chrome or globally shrinking text")
                else:
                    fixes.append(
                        "bottom edge is outside the canvas; if isolated, move the "
                        "local region or rebalance its height, otherwise reflow siblings"
                    )
            fix = "Use the bbox overflow as evidence: " + " AND ".join(fixes) if fixes else fix
            if blk.css_selector:
                fix += f". CSS selector: {blk.css_selector[:60]}"
        issues.append(Issue(
            issue_id=f"spatial_{idx}", rubric_id="B03",
            issue_type="out_of_bounds", severity=Severity.MAJOR,
            confidence=Confidence.HIGH, affected_slides=[slide_id],
            evidence=IssueEvidence(description=desc),
            why_this_fails="Content extends beyond visible slide area",
            planned_fix=fix,
            verdict=Verdict.FAIL,
        ))
        idx += 1

    for bid in state.clipped_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if not blk:
            continue
        # Skip minor clips (< threshold)
        if blk.clipped_bottom_px < MIN_CLIP_PX:
            continue
        # Skip SVG elements
        if _is_container_element(blk):
            continue
        # Skip chart-internal elements with minor clips (labels, axis text)
        # These are fixed-layout SVG elements inside charts where small clips
        # don't affect information delivery and can't be fixed by CSS adjustments
        if (getattr(blk, 'shape_type', None) == 'chart'
                and blk.clipped_bottom_px <= 15
                and (blk.text_chars or 0) <= 20):
            continue
        # Skip decorative punctuation-only elements with minor clips (e.g. "...", "→", "•")
        # These are structural/decorative glyphs, not real content truncation.
        # Only skip if text is purely punctuation/symbols — never skip alphanumeric content.
        import re as _re
        _text_joined = " ".join((blk.text_lines or []))
        if ((blk.text_chars or 0) <= 5
                and blk.clipped_bottom_px <= 10
                and blk.text_lines
                and not _re.search(r'[a-zA-Z0-9]', _text_joined)):
            continue
        # Note: we do NOT skip based on scroll_h vs client_h because
        # overflow:hidden clamps scrollHeight to clientHeight, masking real clips.
        # clipped_bottom_px (already checked > MIN_CLIP_PX) is the reliable signal.
        desc = f"Element '{bid}' is clipped by parent overflow:hidden"
        fix = "Increase parent container height or reduce content"
        if blk:
            clip_px = int(blk.clipped_bottom_px)
            desc += f" — {clip_px}px of content hidden"
            # Compute element bottom in px to detect near-canvas-edge clips
            elem_bottom_px = (blk.y + blk.h) * 96  # inches to px
            near_canvas_bottom = elem_bottom_px > 680  # within 40px of 720px edge
            if near_canvas_bottom:
                # Count how many other blocks are also clipped near canvas bottom
                # to detect "whole bottom section overflows" pattern
                other_near_bottom_clips = sum(
                    1 for b2id in state.clipped_blocks
                    if b2id != bid
                    for b2 in [next((b for b in state.blocks if b.block_id == b2id), None)]
                    if b2 and b2.clipped_bottom_px > MIN_CLIP_PX
                    and (b2.y + b2.h) * 96 > 680
                )
                fix = (f"Element near canvas bottom edge (y+h={elem_bottom_px:.0f}px). "
                       f"The slide is 720px fixed, so solve the owning body region rather "
                       f"than treating the canvas edge as spare space. ")
                if other_near_bottom_clips > 0:
                    fix += (f"There are {other_near_bottom_clips + 1} elements clipped near "
                            f"the bottom. Treat this as shared lower/body pressure: "
                            f"reflow the body cluster, regroup semantic units, or change "
                            f"grid/flex tracks so each affected table/card/label has real "
                            f"visible space. Typography and padding tightening may support "
                            f"that reflow, but should not be the main repair. ")
                else:
                    fix += (f"If this is isolated, give the parent more real visible space "
                            f"or rebalance its neighboring tracks. Avoid hiding content or "
                            f"using overflow windows as the final repair. ")
                fix += f"CSS selector: {blk.css_selector[:60] if blk.css_selector else 'unknown'}"
            else:
                fix = (f"The {clip_px}px clip is evidence that the parent/track is too "
                       f"tight. Give the content real visible space through local parent "
                       f"geometry or sibling reflow; use font/padding reductions only as "
                       f"supporting fit adjustments. "
                       f"CSS selector: {blk.css_selector[:60] if blk.css_selector else 'unknown'}")
        issues.append(Issue(
            issue_id=f"spatial_{idx}", rubric_id="B04",
            issue_type="text_overflow", severity=Severity.MAJOR,
            confidence=Confidence.HIGH, affected_slides=[slide_id],
            evidence=IssueEvidence(description=desc),
            why_this_fails="Clipped content is invisible to the viewer",
            planned_fix=fix, verdict=Verdict.FAIL,
        ))
        idx += 1

    for front, back in state.occlusion_pairs:
        # Skip SVG/container elements occluding others (structural layering)
        front_blk = next((b for b in state.blocks if b.block_id == front), None)
        if _is_container_element(front_blk):
            continue
        issues.append(Issue(
            issue_id=f"spatial_{idx}", rubric_id="B03",
            issue_type="overlap", severity=Severity.MAJOR,
            confidence=Confidence.HIGH, affected_slides=[slide_id],
            evidence=IssueEvidence(
                description=f"Element '{front}' fully occludes '{back}'"),
            why_this_fails="One element completely hides another",
            planned_fix=f"Reposition {front} or adjust z-index",
            verdict=Verdict.FAIL,
        ))
        idx += 1

    # Canvas-edge content truncation: elements at canvas bottom whose scroll
    # content extends beyond the visible portion (child elements off-canvas)
    # Also detect font-size vs height mismatch at canvas edge (descenders cut)
    seen_clipped = set(state.clipped_blocks)
    for blk in state.blocks:
        if blk.block_id in seen_clipped:
            continue
        if _is_container_element(blk):
            continue
        bx, by, bw, bh = blk.bbox_px
        bottom_px = by + bh
        if bottom_px < canvas_h - 2:
            continue
        if not blk.text_lines:
            continue

        visible_h = max(1, canvas_h - by)
        scroll_h = blk.scroll_h_px or 0
        excess = scroll_h - visible_h

        # Also check font-size vs visible height — if font is significantly
        # larger than visible height, text descenders are cut off by canvas
        font_px = blk.font_size_px or 0
        font_excess = font_px * 1.2 - visible_h  # line-height ~1.2× font-size

        effective_excess = max(excess, font_excess)
        if effective_excess >= MIN_CLIP_PX:
            eff_int = int(effective_excess)
            if font_excess > excess:
                desc = (f"Element '{blk.block_id}' at canvas bottom edge — "
                        f"font-size {int(font_px)}px in {int(visible_h)}px visible space, "
                        f"text descenders truncated by ~{eff_int}px")
            else:
                desc = (f"Element '{blk.block_id}' at canvas bottom edge has content "
                        f"truncated — {eff_int}px of scroll content below canvas "
                        f"(visible={int(visible_h)}px, scroll={int(scroll_h)}px)")
            fix = (f"Element at y={int(by)}px has content extending below the "
                   f"visible canvas. Use this as evidence of bottom-region fit "
                   f"pressure, not as a literal move-up/shrink-font command. If "
                   f"isolated, give this element/parent real visible space; if "
                   f"other lower elements are also clipped or out of bounds, reflow "
                   f"the owning body region so the semantic units fit without hidden "
                   f"content. CSS selector: {blk.css_selector[:60] if blk.css_selector else 'unknown'}")
            issues.append(Issue(
                issue_id=f"spatial_{idx}", rubric_id="B03",
                issue_type="out_of_bounds", severity=Severity.MAJOR,
                confidence=Confidence.HIGH, affected_slides=[slide_id],
                evidence=IssueEvidence(description=desc),
                why_this_fails="Content extends below visible canvas area",
                planned_fix=fix, verdict=Verdict.FAIL,
            ))
            idx += 1

    return issues


def _rescale_slide_if_needed(html: str) -> str:
    """Rescale slides from 1536x864 to 1280x720 if needed.

    Many image2slide HTML files use 1536x864 canvas but redeck's spatial
    detection uses 1280x720 viewport. Fix by wrapping content in a CSS
    transform that scales everything down proportionally.
    """
    import re
    m = re.search(r'\.slide\s*\{[^}]*width:\s*1536px[^}]*height:\s*864px', html)
    if not m:
        return html

    # Use CSS transform to scale the entire slide
    # Scale: 1280/1536 = 0.8333
    scale_css = """
    .slide {
        transform: scale(0.8333) !important;
        transform-origin: top left !important;
    }
    """
    # Insert before </style>
    if '</style>' in html:
        html = html.replace('</style>', scale_css + '\n</style>', 1)
        print(f"   📐 Added CSS transform scale(0.8333) to rescale 1536→1280")
    return html


class _MinimalCompiler:
    """Stub to satisfy AgentRepair's codegen_compiler dependency."""
    def __init__(self):
        self.slide_codes = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return None


def main():
    parser = argparse.ArgumentParser(
        description="ReDeck Repair — fix spatial issues in HTML slides"
    )
    parser.add_argument("files", nargs="*", help="HTML slide files to repair")
    parser.add_argument("--dir", help="Directory of slide_*.html files")
    parser.add_argument("--output-dir", "-o", help="Output directory (default: <input>_repaired)")
    parser.add_argument("--model", default="gpt-5.4", help="LLM model")
    parser.add_argument("--screenshot", action="store_true", help="Render screenshots")
    args = parser.parse_args()

    # Collect input files
    paths = []
    input_dir = None
    if args.dir:
        input_dir = Path(args.dir)
        paths.extend(sorted(input_dir.glob("slide_*.html")))
    for f in (args.files or []):
        p = Path(f)
        if p.is_file():
            paths.append(p)
        else:
            print(f"Warning: {f} not found", file=sys.stderr)

    if not paths:
        parser.error("No HTML files specified. Use positional args or --dir")

    # Output directory
    if args.output_dir:
        out_dir = Path(args.output_dir)
    elif input_dir:
        out_dir = input_dir.parent / (input_dir.name + "_repaired")
    else:
        out_dir = paths[0].parent / "repaired"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Initialize
    llm = LLMClient()
    agent = AgentRepair(llm=llm, model=args.model)
    compiler = _MinimalCompiler()
    bp_slide = BlueprintSlide(
        slide_id=0, role="body",
        primary_proposition="", narrative_position="body",
    )
    evidence = EvidenceState()

    summary = {}
    for hp in paths:
        try:
            sid = int(hp.stem.split("_")[1])
        except (IndexError, ValueError):
            sid = 1

        html = hp.read_text()

        # Pre-process: rescale 1536x864 slides to 1280x720 before repair
        html = _rescale_slide_if_needed(html)

        state = extract_html_slide_state(sid, html)
        initial = count_issues(state)

        if initial == 0:
            shutil.copy2(hp, out_dir / hp.name)
            summary[hp.name] = {"initial": 0, "final": 0}
            print(f"✅ {hp.name}: clean, no repair needed")
            continue

        print(f"🔧 {hp.name}: {initial} issues, repairing...")
        issues = build_issues_from_state(state, sid)

        # Create fresh agent per slide to avoid cross-slide state contamination
        agent = AgentRepair(llm=llm, model=args.model)

        try:
            repaired = agent.repair(
                slide_id=sid, code=html, all_issues=issues,
                bp_slide=None, evidence=evidence,
                codegen_compiler=compiler, case_dir=str(hp.parent),
            )
        except Exception as e:
            print(f"   ⚠️  AgentRepair failed: {e}", file=sys.stderr)
            repaired = None

        if repaired:
            final_state = extract_html_slide_state(sid, repaired)
            final = count_issues(final_state)
            (out_dir / hp.name).write_text(repaired)
            summary[hp.name] = {"initial": initial, "final": final}
            print(f"   {initial} → {final} issues")
        else:
            shutil.copy2(hp, out_dir / hp.name)
            summary[hp.name] = {"initial": initial, "final": initial}
            print(f"   No repair applied, kept original")

    # Screenshots
    if args.screenshot:
        print("\nRendering screenshots...")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            png_dir = out_dir / "screenshots"
            png_dir.mkdir(exist_ok=True)
            for hp in sorted(out_dir.glob("slide_*.html")):
                page.goto(f"file://{hp.resolve()}")
                page.wait_for_timeout(500)
                page.screenshot(path=str(png_dir / f"{hp.stem}.png"))
            browser.close()

    # Summary
    (out_dir / "repair_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n{'='*50}")
    total_before = sum(s["initial"] for s in summary.values())
    total_after = sum(s["final"] for s in summary.values())
    for name, s in summary.items():
        if s["initial"] > 0:
            print(f"  {name}: {s['initial']} → {s['final']}")
    print(f"  TOTAL: {total_before} → {total_after} "
          f"({(total_before-total_after)/total_before*100:.0f}% fixed)"
          if total_before > 0 else "  All clean!")
    print(f"\nOutput: {out_dir}")


if __name__ == "__main__":
    main()
