#!/usr/bin/env python3
"""Build a geometry-preserving BAMS layout library without model calls.

The existing component extraction already normalized most major zones to
percentages. This script combines those zones with the catalog's semantic
labels, producing compact layout blueprints for content-aware retrieval.
"""

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMPONENTS = ROOT / "pattern_library" / "metadata" / "seed_components.json"
DEFAULT_CATALOG = ROOT / "pattern_library" / "metadata" / "pattern_catalog.json"
DEFAULT_OUTPUT = ROOT / "pattern_library" / "metadata" / "layout_library.json"

CANVAS_WIDTH = 1536.0
CANVAS_HEIGHT = 864.0
GEOMETRY_PROPS = {"left", "right", "top", "bottom", "width", "height", "inset"}
IGNORE_SELECTORS = {".slide", "#stage", "html", "body", "html,body", "*"}


def _number(value, axis):
    """Convert a simple percentage or px value to canvas percentage."""
    if value is None:
        return None
    value = value.strip().lower()
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)%", value)
    if match:
        return round(float(match.group(1)), 1)
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)px", value)
    if match:
        base = CANVAS_WIDTH if axis == "x" else CANVAS_HEIGHT
        return round(float(match.group(1)) / base * 100, 1)
    if value == "0":
        return 0.0
    return None


def _expand_inset(value):
    values = value.split()
    if not 1 <= len(values) <= 4:
        return {}
    if len(values) == 1:
        top = right = bottom = left = values[0]
    elif len(values) == 2:
        top = bottom = values[0]
        right = left = values[1]
    elif len(values) == 3:
        top, right, bottom = values
        left = right
    else:
        top, right, bottom, left = values
    return {"top": top, "right": right, "bottom": bottom, "left": left}


def _slot_for_selector(selector):
    value = selector.lower()
    slot_keywords = (
        ("title", ("title", "headline", "heading")),
        ("header", ("header", "top", "masthead")),
        ("metric", ("metric", "stat", "kpi", "number")),
        ("visual", ("chart", "figure", "image", "photo", "graph", "diagram")),
        ("table", ("table", "matrix")),
        ("sidebar", ("sidebar", "rail", "left-panel")),
        ("footer", ("footer", "source", "footnote")),
        ("narrative", ("content", "intro", "summary", "para", "text", "main")),
        ("panel", ("panel", "card", "feature", "item", "column", "col")),
        ("band", ("band", "strip", "row")),
    )
    for slot, keywords in slot_keywords:
        if any(keyword in value for keyword in keywords):
            return slot
    return "zone"


def _parse_zones(css):
    zones = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(selector.strip().split())
        if selector in IGNORE_SELECTORS or selector.startswith("@"):
            continue
        props = {
            key.strip().lower(): value.strip()
            for key, value in re.findall(r"([\w-]+)\s*:\s*([^;{}]+)", body)
        }
        if "inset" in props:
            for key, value in _expand_inset(props["inset"]).items():
                props.setdefault(key, value)
        if not GEOMETRY_PROPS.intersection(props):
            continue

        left = _number(props.get("left"), "x")
        right = _number(props.get("right"), "x")
        top = _number(props.get("top"), "y")
        bottom = _number(props.get("bottom"), "y")
        width = _number(props.get("width"), "x")
        height = _number(props.get("height"), "y")
        if width is None and left is not None and right is not None:
            width = round(100 - left - right, 1)
        if height is None and top is not None and bottom is not None:
            height = round(100 - top - bottom, 1)
        if left is None and right is not None and width is not None:
            left = round(100 - right - width, 1)
        if top is None and bottom is not None and height is not None:
            top = round(100 - bottom - height, 1)

        zone = {"selector": selector[:80], "slot": _slot_for_selector(selector)}
        for key, value in (("x", left), ("y", top), ("w", width), ("h", height)):
            if value is not None:
                zone[key] = value
        if len(zone) > 2:
            zones.append(zone)
    return zones[:10]


def _focus_for(macro, zones):
    if macro == "asymmetric-hero-left":
        return "left"
    if macro in {"asymmetric-hero-right", "left-title-right-body", "left-sidebar"}:
        return "right"
    if macro in {"single-center", "grid-2x2", "grid-3x2", "three-column", "two-column-equal"}:
        return "balanced"

    weighted = []
    for zone in zones:
        if all(key in zone for key in ("x", "w")):
            weight = zone.get("w", 10) * zone.get("h", 20)
            weighted.append((zone["x"] + zone["w"] / 2, weight))
    if not weighted:
        return "balanced"
    center = sum(x * weight for x, weight in weighted) / sum(weight for _, weight in weighted)
    return "left" if center < 43 else "right" if center > 57 else "balanced"


def _density_for(content):
    if content in {"data-table", "bar-chart", "big-numbers-KPI", "comparison-columns"}:
        return "high"
    if content in {"diagram-boxes", "process-arrows", "timeline-nodes", "icon-grid", "team-cards"}:
        return "medium"
    return "low"


def build_library(components_path, catalog_path):
    components = json.loads(Path(components_path).read_text())
    catalog = {
        entry["id"]: entry
        for entry in json.loads(Path(catalog_path).read_text())
    }
    output = []
    for seed_id in sorted(components):
        entry = catalog.get(seed_id)
        if not entry:
            continue
        layout_css = components[seed_id].get("layout", "").strip()
        zones = _parse_zones(layout_css)
        if len(zones) < 2:
            continue
        dims = entry.get("dims", {})
        macro = dims.get("layout", "unknown")
        content = dims.get("content", "unknown")
        classes = " ".join(entry.get("css_classes", [])).lower()
        card_terms = sum(classes.count(term) for term in ("card", "panel", "box"))
        signature = "|".join(
            f"{zone['slot']}:{zone.get('x','?')}:{zone.get('y','?')}:{zone.get('w','?')}:{zone.get('h','?')}"
            for zone in zones
        )
        output.append({
            "id": seed_id,
            "macro": macro,
            "source_content": content,
            "focus": _focus_for(macro, zones),
            "density": _density_for(content),
            "zones": zones,
            "semantic_slots": entry.get("semantic_slots", []),
            "card_heaviness": min(card_terms, 9),
            "geometry_signature": signature,
        })
    return output


def main():
    parser = argparse.ArgumentParser(description="Build BAMS layout blueprint library")
    parser.add_argument("--components", type=Path, default=DEFAULT_COMPONENTS)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    library = build_library(args.components, args.catalog)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(library, indent=2, ensure_ascii=False) + "\n")
    macros = sorted({entry["macro"] for entry in library})
    print(f"Wrote {len(library)} BAMS layout blueprints to {args.out}")
    print(f"Macro families: {len(macros)} ({', '.join(macros)})")


if __name__ == "__main__":
    main()
