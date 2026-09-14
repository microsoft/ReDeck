#!/usr/bin/env python3
"""Build probe_registry.json from probe .md files.

Extracts atomic checks from each probe's "Fail if" and "Severity" sections.
Each numbered Fail-if item becomes an atomic check. Severity sub-levels
that describe distinct conditions (not just severity gradations) are added
as additional checks.

Output: probe_registry.json derived from the maintained probe definitions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.schemas.issue_types import PROBE_REGISTRY

PROBES_DIR = ROOT / "app" / "prompts" / "probes"


def _heading_sections(text: str, title: str) -> list[str]:
    """Return Markdown sections whose heading starts with ``title``.

    A section ends at the next heading of the same or higher level. This keeps
    nested ``### Do not flag`` content out of a ``### Fail if`` section while
    still supporting multiple ``## Fail if - subtype`` sections in one probe.
    """
    headings = list(re.finditer(r"^(#{2,6})\s+(.+?)\s*$", text, re.MULTILINE))
    sections = []
    wanted = title.lower()
    for index, heading in enumerate(headings):
        heading_text = heading.group(2).strip().lower()
        if heading_text != wanted and not re.match(
            rf"^{re.escape(wanted)}\s*(?:[-—:]|$)", heading_text,
        ):
            continue
        level = len(heading.group(1))
        end = len(text)
        for next_heading in headings[index + 1:]:
            if len(next_heading.group(1)) <= level:
                end = next_heading.start()
                break
        sections.append(text[heading.end():end])
    return sections


def _numbered_items(section: str) -> list[str]:
    """Parse numbered Markdown items, joining indented continuation lines."""
    items = []
    current: list[str] | None = None
    for line in section.splitlines():
        match = re.match(r"^\d+\.\s+(.+)$", line)
        if match:
            if current:
                items.append(" ".join(current))
            current = [match.group(1).strip()]
            continue
        if current and line[:1].isspace() and line.strip():
            current.append(line.strip())
            continue
        if current:
            items.append(" ".join(current))
            current = None
    if current:
        items.append(" ".join(current))
    return items


def _severity_items(section: str) -> list[tuple[str, str]]:
    """Parse severity bullets, joining indented continuation lines."""
    items = []
    current: tuple[str, list[str]] | None = None
    for line in section.splitlines():
        match = re.match(
            r"^- (critical|major|minor)(?::| when| if)\s+(.+)$",
            line,
        )
        if match:
            if current:
                items.append((current[0], " ".join(current[1])))
            current = (match.group(1), [match.group(2).strip()])
            continue
        if current and line[:1].isspace() and line.strip():
            current[1].append(line.strip())
            continue
        if current:
            items.append((current[0], " ".join(current[1])))
            current = None
    if current:
        items.append((current[0], " ".join(current[1])))
    return items


def parse_probe_md(path: Path) -> list[dict]:
    """Extract atomic checks from a probe .md file."""
    text = path.read_text(encoding="utf-8")
    checks = []
    seen_fail_if = set()

    for section in _heading_sections(text, "Fail if"):
        for check_text in _numbered_items(section):
            if check_text in seen_fail_if:
                continue
            seen_fail_if.add(check_text)
            checks.append({"text": check_text, "source": "fail_if"})

    # Extract severity sub-levels that describe distinct defect conditions.
    for section in _heading_sections(text, "Severity"):
        for severity, severity_text in _severity_items(section):
            if not any(
                severity_text.lower()[:30] in check["text"].lower()
                for check in checks
            ):
                checks.append({
                    "text": severity_text,
                    "source": f"severity_{severity}",
                })

    return checks


def build_registry(probes_dir=PROBES_DIR):
    registry = {}
    total = 0

    for probe_id, definition in sorted(PROBE_REGISTRY.items()):
        path = Path(probes_dir) / definition.probe_file
        checks = parse_probe_md(path)
        if not checks:
            raise ValueError(f"No atomic checks extracted from {path}")
        heading = re.search(r"^#\s+(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
        summary = heading.group(1).strip() if heading else definition.name

        numbered = []
        for index, check in enumerate(checks, 1):
            numbered.append({
                "id": f"{probe_id}.{index}",
                "text": check["text"],
                "source": check["source"],
            })

        registry[probe_id] = {
            "issue_type": definition.name,
            "family": definition.family.value,
            "summary": summary,
            "checks": numbered,
        }
        total += len(numbered)

    return registry, total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probes-dir", type=Path, default=PROBES_DIR)
    parser.add_argument("--out", type=Path, default=PROBES_DIR / "probe_registry.json")
    args = parser.parse_args(argv)
    registry, total = build_registry(args.probes_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(registry)} probe groups with {total} atomic checks to {args.out}")


if __name__ == "__main__":
    main()
