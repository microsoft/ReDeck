#!/usr/bin/env python3
"""
ReDeck Repair — Fix spatial issues in HTML slides using AgentRepair.

Uses ReDeck's spatial detection to find issues, then runs the AgentRepair
tool-calling loop (plan → apply_edits → verify_layout → submit) to fix them.

Usage:
    python scripts/redeck_repair.py slide_01.html
    python scripts/redeck_repair.py --dir ./slides/ --output-dir ./repaired/
    python scripts/redeck_repair.py slide.html --model gpt-4o
"""
import sys
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


def count_issues(state):
    """Count hard spatial defects."""
    return (
        len(state.overlap_pairs)
        + len(state.overflow_blocks)
        + len(state.oob_blocks)
        + len(state.clipped_blocks)
        + len(state.occlusion_pairs)
    )


def build_issues_from_state(state, slide_id: int) -> list[Issue]:
    """Convert spatial state violations into Issue objects for AgentRepair."""
    issues = []
    idx = 0

    for a_id, b_id, area in state.overlap_pairs:
        a_blk = next((b for b in state.blocks if b.block_id == a_id), None)
        b_blk = next((b for b in state.blocks if b.block_id == b_id), None)
        desc = f"Elements '{a_id}' and '{b_id}' overlap"
        if a_blk and b_blk:
            ax, ay, aw, ah = a_blk.bbox_px
            bx, by, bw, bh = b_blk.bbox_px
            desc += f". A at ({ax},{ay},{aw}x{ah}), B at ({bx},{by},{bw}x{bh})"
        issues.append(Issue(
            issue_id=f"spatial_{idx}", rubric_id="B03", issue_type="overlap",
            severity=Severity.MAJOR, confidence=Confidence.HIGH,
            affected_slides=[slide_id],
            evidence=IssueEvidence(description=desc),
            why_this_fails="Overlapping elements make text unreadable",
            planned_fix=f"Move {b_id} down or reduce height of {a_id}",
            verdict=Verdict.FAIL,
        ))
        idx += 1

    for bid in state.overflow_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        desc = f"Element '{bid}' has text overflow"
        fix = "Reduce font-size or increase container height"
        if blk:
            desc += (f" — scrollHeight={blk.scroll_h_px}px vs "
                     f"clientHeight={blk.client_h_px}px, "
                     f"overflow={blk.overflow_bottom_px}px vertical")
            fix = (f"Increase container height by {blk.overflow_bottom_px}px "
                   f"or reduce font-size")
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
        desc = f"Element '{bid}' extends beyond 1280x720px canvas"
        if blk:
            bx, by, bw, bh = blk.bbox_px
            desc += f" — bbox ({bx},{by},{bw}x{bh})"
        issues.append(Issue(
            issue_id=f"spatial_{idx}", rubric_id="B03",
            issue_type="overlap", severity=Severity.MAJOR,
            confidence=Confidence.HIGH, affected_slides=[slide_id],
            evidence=IssueEvidence(description=desc),
            why_this_fails="Content extends beyond visible slide area",
            planned_fix="Reduce size or reposition to fit within 1280x720px",
            verdict=Verdict.FAIL,
        ))
        idx += 1

    for bid in state.clipped_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        desc = f"Element '{bid}' is clipped by parent overflow:hidden"
        fix = "Increase parent container height or reduce content"
        if blk:
            desc += f" — {blk.clipped_bottom_px}px of content hidden"
            fix = (f"Increase parent height by {blk.clipped_bottom_px}px "
                   f"or reduce content above")
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

    return issues


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
    parser.add_argument("--model", default="gpt-4o", help="LLM model")
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
        state = extract_html_slide_state(sid, html)
        initial = count_issues(state)

        if initial == 0:
            shutil.copy2(hp, out_dir / hp.name)
            summary[hp.name] = {"initial": 0, "final": 0}
            print(f"✅ {hp.name}: clean, no repair needed")
            continue

        print(f"🔧 {hp.name}: {initial} issues, repairing...")
        issues = build_issues_from_state(state, sid)
        bp_slide.slide_id = sid

        try:
            repaired = agent.repair(
                slide_id=sid, code=html, all_issues=issues,
                bp_slide=bp_slide, evidence=evidence,
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
