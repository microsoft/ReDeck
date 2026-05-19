#!/usr/bin/env python3
"""Build probe_registry.json from probe .md files.

Extracts atomic checks from each probe's "Fail if" and "Severity" sections.
Each numbered Fail-if item becomes an atomic check. Severity sub-levels
that describe distinct conditions (not just severity gradations) are added
as additional checks.

Output: probe_registry.json with ≥200 atomic checks total.
"""

import json
import re
import sys
from pathlib import Path

PROBES_DIR = Path(__file__).parent.parent / "app" / "prompts" / "probes"
ISSUE_TYPES_PATH = Path(__file__).parent.parent / "app" / "schemas" / "issue_types.py"

# Manually map probe_id → (issue_type, family, summary) from issue_types.py
# to avoid importing the module (dependency issues)
PROBE_META = {
    "A01": ("weak_thesis", "A", "Thesis clarity — deck lacks clear central objective"),
    "A02": ("missing_context", "A", "Opening context — first slides don't frame the problem"),
    "A03": ("poor_flow", "A", "Logical flow — slide order breaks coherent progression"),
    "A04": ("title_content_mismatch", "A", "Title-content alignment — title doesn't match body"),
    "A05": ("misallocated_detail", "A", "Detail allocation — core under-developed, secondary over-expanded"),
    "A06": ("weak_closing", "A", "Closing closure — ending doesn't synthesize or close"),
    "A07": ("placeholder_slide", "A", "Placeholder slide — slide has only title, no content"),
    "B01": ("visual_inconsistency", "B_visual", "Visual consistency — cross-slide style drift"),
    "B02": ("layout_inappropriate", "B_visual", "Layout appropriateness — structure doesn't fit content"),
    "B03": ("overlap", "B_visual", "Overlap / occlusion — elements hidden behind others"),
    "B04": ("text_overflow", "B_visual", "Text overflow — text cut off or beyond container"),
    "B05": ("low_contrast", "B_visual", "Low contrast — text hard to read against background"),
    "B06": ("text_visual_imbalance", "B_visual", "Text-visual balance — too much text, no visuals"),
    "B07": ("form_misfit", "B_visual", "Form misfit — chart/diagram type wrong for data"),
    "B08": ("irrelevant_visual", "B_visual", "Irrelevant visual — decorative image adds no value"),
    "B09": ("density_imbalance", "B_visual", "Density imbalance — too crowded, sparse, or uneven"),
    "B10": ("missing_data_visualization", "B_visual", "Missing data visualization — numbers in bullets should be chart"),
    "B11": ("typography_error", "B_visual", "Typography error — garbled characters, rendering artifacts"),
    "B12": ("formatting_error", "B_visual", "Formatting consistency — font/spacing inconsistency"),
    "B13": ("alignment_inconsistency", "B_visual", "Spatial coherence — misalignment, uneven spacing"),
    "B14": ("form_redundancy", "B_visual", "Form redundancy — same info in chart AND bullets"),
    "B15": ("container_contract_breach", "B_visual", "Container contract breach — content overflows container"),
    "B16": ("text_wall", "B_visual", "Text wall — ≥7 ungrouped bullets, no structure"),
    "B17": ("raw_figure", "B_visual", "Raw figure — paper figure embedded without adaptation"),
    "B18": ("color_semantic_mismatch", "B_visual", "Color semantic mismatch — colors imply wrong values"),
    "C01": ("missing_section", "C", "Required sections present — thematic area completely missing"),
    "C02": ("missing_point", "C", "Must-cover points — mandatory key points absent"),
    "C03": ("missing_evidence", "C", "Evidence included — claims without supporting evidence"),
    "C04": ("missing_entity", "C", "Entities present — key metrics/names/datasets missing"),
    "C05": ("missing_conclusion", "C", "Conclusions present — required conclusions/limitations absent"),
    "D01": ("incorrect_claim", "D", "Key claims correct — claim contradicts source"),
    "D02": ("numeric_error", "D", "Numeric accuracy — numbers/percentages wrong"),
    "D03": ("entity_error", "D", "Entity accuracy — names/terms incorrect"),
    "D04": ("chart_misinterpretation", "D", "Chart interpretation — chart data doesn't match source"),
    "D05": ("unsupported_causality", "D", "Causality check — unsupported causal/comparative claims"),
    "D06": ("spelling_error", "D", "Spelling & terminology — typos, grammar, language mixing"),
    "E01": ("untraceable", "E", "Traceability — content can't be mapped to source"),
    "E02": ("fabricated", "E", "No fabrication — invented numbers/facts/conclusions"),
    "E03": ("unfaithful_compression", "E", "Faithful compression — paraphrase changes meaning"),
    "E04": ("misleading_omission", "E", "Non-misleading omission — omissions distort stance"),
}


def parse_probe_md(path: Path) -> list[dict]:
    """Extract atomic checks from a probe .md file."""
    text = path.read_text(encoding="utf-8")
    checks = []

    # Extract "Fail if" section items
    fail_match = re.search(
        r'## Fail if\s*\n(.*?)(?=\n## |\Z)', text, re.DOTALL
    )
    if fail_match:
        for m in re.finditer(r'^\d+\.\s+(.+)$', fail_match.group(1), re.MULTILINE):
            checks.append({"text": m.group(1).strip(), "source": "fail_if"})

    # Extract severity sub-levels that describe distinct defect conditions
    sev_match = re.search(
        r'## Severity\s*\n(.*?)(?=\n## |\Z)', text, re.DOTALL
    )
    if sev_match:
        for m in re.finditer(
            r'^- (critical|major|minor)(?::| when| if)\s+(.+)$',
            sev_match.group(1), re.MULTILINE
        ):
            sev_text = m.group(2).strip()
            # Only add if it describes a distinct condition not already in fail_if
            if not any(sev_text.lower()[:30] in c["text"].lower() for c in checks):
                checks.append({
                    "text": sev_text,
                    "source": f"severity_{m.group(1)}",
                })

    return checks


def build_registry():
    registry = {}
    total = 0

    for probe_id in sorted(PROBE_META.keys()):
        issue_type, family, summary = PROBE_META[probe_id]

        # Find the .md file
        md_files = list(PROBES_DIR.glob(f"{probe_id}_*.md"))
        if not md_files:
            print(f"WARNING: no .md file for {probe_id}", file=sys.stderr)
            continue

        checks = parse_probe_md(md_files[0])
        if not checks:
            print(f"WARNING: no checks extracted from {probe_id}", file=sys.stderr)
            continue

        numbered = []
        for i, c in enumerate(checks, 1):
            numbered.append({
                "id": f"{probe_id}.{i}",
                "text": c["text"],
                "source": c["source"],
            })

        registry[probe_id] = {
            "issue_type": issue_type,
            "family": family,
            "summary": summary,
            "checks": numbered,
        }
        total += len(numbered)

    return registry, total


def main():
    registry, total = build_registry()

    # Report
    family_counts = {}
    for pid, info in registry.items():
        fam = info["family"]
        family_counts[fam] = family_counts.get(fam, 0) + len(info["checks"])

    print(f"Total atomic checks: {total}")
    print("Per family:")
    for fam in sorted(family_counts):
        print(f"  {fam}: {family_counts[fam]}")
    print(f"Probe groups: {len(registry)}")

    if total < 200:
        print(f"\nWARNING: only {total} checks, need ≥200. "
              "Consider adding severity sub-checks or splitting large probes.",
              file=sys.stderr)

    # Write output
    out_path = PROBES_DIR / "probe_registry.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    print(f"\nWritten to: {out_path}")


if __name__ == "__main__":
    main()
