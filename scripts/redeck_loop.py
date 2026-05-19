#!/usr/bin/env python3
"""
ReDeck Loop — Iterative evaluate → repair → re-evaluate workflow.

Runs the full judge-repair loop:
  Turn 0: Spatial check + (optional) LLM judges → issues
  Turn 1: Repair → Spatial check + judges → diff issues
  Turn 2: Repair → Spatial check + judges → diff issues
  ... until convergence or max turns

Usage:
    # Spatial-only loop (no LLM, fast)
    python scripts/redeck_loop.py --dir ./slides/ --spatial-only

    # Full evaluation loop
    python scripts/redeck_loop.py --dir ./slides/ --paper paper.md --max-turns 3

    # With output directory for repaired slides
    python scripts/redeck_loop.py --dir ./slides/ --output-dir ./repaired/ --max-turns 3
"""
import sys
import json
import argparse
import logging
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.redeck.html_spatial_state import extract_html_slide_state
from app.modules.redeck.agent_repair import AgentRepair
from app.backends.html_codegen.html_codegen_compiler import HtmlCodeGenCompiler
from app.llm_client import LLMClient
from app.schemas.issue import Issue, IssueEvidence
from app.schemas.common import Severity, Confidence, Verdict
from app.schemas.blueprint import BlueprintSlide
from app.schemas.evidence import EvidenceState

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def count_spatial_issues(state) -> int:
    return (
        len(state.overlap_pairs)
        + len(state.overflow_blocks)
        + len(state.oob_blocks)
        + len(state.clipped_blocks)
        + len(state.occlusion_pairs)
    )


def build_issues_from_state(state, slide_id: int) -> list[Issue]:
    """Convert spatial state into Issue objects for AgentRepair."""
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
            issue_type="out_of_bounds", severity=Severity.MAJOR,
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



def run_loop(
    slide_codes: dict[int, str],
    max_turns: int = 3,
    model: str = "gpt-4o",
    output_dir: Path | None = None,
) -> dict:
    """Run the iterative spatial check → repair loop.

    Returns summary dict with per-turn results.
    """
    llm = LLMClient()
    agent = AgentRepair(llm=llm, model=model)
    compiler = HtmlCodeGenCompiler(llm=llm, model=model)
    bp_slide = BlueprintSlide(
        slide_id=0, role="body",
        primary_proposition="", narrative_position="body",
    )
    evidence = EvidenceState()

    current_codes = dict(slide_codes)
    history = []

    for turn in range(max_turns + 1):
        # === EVALUATE ===
        turn_issues: dict[int, list[Issue]] = {}
        turn_counts: dict[int, int] = {}

        for sid, html in sorted(current_codes.items()):
            state = extract_html_slide_state(sid, html)
            n = count_spatial_issues(state)
            turn_counts[sid] = n
            if n > 0:
                turn_issues[sid] = build_issues_from_state(state, sid)

        total = sum(turn_counts.values())
        history.append({
            "turn": turn,
            "total_issues": total,
            "per_slide": dict(turn_counts),
        })

        print(f"\n{'='*50}")
        print(f"Turn {turn}: {total} spatial issues")
        for sid in sorted(turn_counts):
            n = turn_counts[sid]
            mark = "✅" if n == 0 else "❌"
            print(f"  {mark} slide_{sid:02d}: {n} issues")

        # Converged or last turn?
        if total == 0:
            print(f"\n✅ All issues resolved after {turn} turn(s)!")
            break
        if turn == max_turns:
            print(f"\n⚠️  Reached max turns ({max_turns}), {total} issues remain")
            break

        # === REPAIR ===
        print(f"\n🔧 Repairing {len(turn_issues)} slide(s)...")
        for sid, issues in sorted(turn_issues.items()):
            bp_slide.slide_id = sid
            html = current_codes[sid]
            try:
                repaired = agent.repair(
                    slide_id=sid, code=html, all_issues=issues,
                    bp_slide=bp_slide, evidence=evidence,
                    codegen_compiler=compiler, case_dir="/tmp",
                )
                if repaired:
                    # Spatial regression gate: only accept if hard defects don't increase
                    old_state = extract_html_slide_state(sid, html)
                    new_state = extract_html_slide_state(sid, repaired)
                    old_hard = len(old_state.overlap_pairs) + len(old_state.oob_blocks)
                    new_hard = len(new_state.overlap_pairs) + len(new_state.oob_blocks)
                    if new_hard <= old_hard:
                        current_codes[sid] = repaired
                        new_n = count_spatial_issues(new_state)
                        print(f"  slide_{sid:02d}: {len(issues)} → {new_n}")
                    else:
                        print(f"  slide_{sid:02d}: regression ({old_hard} → {new_hard} hard), kept original")
                else:
                    print(f"  slide_{sid:02d}: no repair returned")
            except Exception as e:
                print(f"  slide_{sid:02d}: repair failed: {e}", file=sys.stderr)

    # === SAVE ===
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for sid, html in sorted(current_codes.items()):
            (output_dir / f"slide_{sid:02d}.html").write_text(html)
        (output_dir / "loop_history.json").write_text(
            json.dumps(history, indent=2)
        )
        print(f"\nOutput: {output_dir}")

    return {
        "history": history,
        "initial_issues": history[0]["total_issues"],
        "final_issues": history[-1]["total_issues"],
        "turns_used": len(history) - 1,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ReDeck Loop — iterative evaluate → repair → re-evaluate"
    )
    parser.add_argument("files", nargs="*", help="HTML slide files")
    parser.add_argument("--dir", help="Directory of slide_*.html files")
    parser.add_argument("--output-dir", "-o", help="Output directory for repaired slides")
    parser.add_argument("--max-turns", type=int, default=3, help="Max repair turns (default: 3)")
    parser.add_argument("--model", default="gpt-4o", help="LLM model for repair")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # Collect input files
    paths = []
    if args.dir:
        paths.extend(sorted(Path(args.dir).glob("slide_*.html")))
    for f in (args.files or []):
        p = Path(f)
        if p.is_file():
            paths.append(p)

    if not paths:
        parser.error("No HTML files. Use positional args or --dir")

    # Build slide_codes
    slide_codes = {}
    for hp in paths:
        try:
            sid = int(hp.stem.split("_")[1])
        except (IndexError, ValueError):
            sid = len(slide_codes) + 1
        slide_codes[sid] = hp.read_text()

    # Output dir
    out_dir = None
    if args.output_dir:
        out_dir = Path(args.output_dir)
    elif args.dir:
        out_dir = Path(args.dir).parent / (Path(args.dir).name + "_looped")

    result = run_loop(
        slide_codes=slide_codes,
        max_turns=args.max_turns,
        model=args.model,
        output_dir=out_dir,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        initial = result["initial_issues"]
        final = result["final_issues"]
        if initial > 0:
            pct = (initial - final) / initial * 100
            print(f"\nSummary: {initial} → {final} issues ({pct:.0f}% fixed in {result['turns_used']} turn(s))")
        else:
            print("\nAll slides clean from the start.")


if __name__ == "__main__":
    main()
