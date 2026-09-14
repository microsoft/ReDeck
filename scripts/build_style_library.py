#!/usr/bin/env python3
"""Compile BAMS components into executable, coherent StyleSpec families."""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "pattern_library" / "metadata" / "pattern_catalog.json"
DEFAULT_COMPONENTS = ROOT / "pattern_library" / "metadata" / "seed_components.json"
DEFAULT_OUTPUT = ROOT / "pattern_library" / "metadata" / "style_library.json"

def _token_value(css, name, fallback):
    match = re.search(rf"{re.escape(name)}\s*:\s*([^;}}]+)", css)
    return match.group(1).strip() if match else fallback


def _semantic_colors(code, source_luminance):
    dark_source = source_luminance != "light"
    replacements = {
        "--source-dark": "--surface-canvas" if dark_source else "--surface-contrast",
        "--source-light": "--surface-contrast" if dark_source else "--surface-canvas",
        "--source-accent": "--accent-primary",
        "--source-ink-dark": "--ink-contrast" if dark_source else "--ink-canvas",
        "--source-ink-light": "--ink-canvas" if dark_source else "--ink-contrast",
    }
    for source, target in replacements.items():
        code = code.replace(source, target)
    return code


def _semantic_background(code, source_luminance):
    dark_count = code.count("--source-dark")
    light_count = code.count("--source-light")
    if dark_count == light_count:
        canvas_source = "--source-light" if source_luminance == "light" else "--source-dark"
    else:
        canvas_source = "--source-dark" if dark_count > light_count else "--source-light"
    contrast_source = "--source-light" if canvas_source == "--source-dark" else "--source-dark"
    replacements = {
        canvas_source: "--surface-canvas",
        contrast_source: "--surface-contrast",
        "--source-accent": "--accent-primary",
        "--source-ink-dark": "--ink-canvas" if source_luminance == "light" else "--ink-contrast",
        "--source-ink-light": "--ink-contrast" if source_luminance == "light" else "--ink-canvas",
    }
    for source, target in replacements.items():
        code = code.replace(source, target)
    return code


def _most_common_radius(css):
    values = re.findall(r"border-radius\s*:\s*([^;{}]+)", css, re.IGNORECASE)
    if not values:
        return "0px"
    simple = []
    for value in values:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)px", value.strip())
        if match:
            simple.append(min(float(match.group(1)), 32.0))
        elif "%" in value:
            simple.append(999.0)
    if not simple:
        return "0px"
    chosen = Counter(simple).most_common(1)[0][0]
    return "50%" if chosen == 999.0 else f"{chosen:g}px"


def _element_grammar(css, deco_dim, content_dim, card_heaviness):
    radius = _most_common_radius(css)
    has_shadow = "box-shadow" in css
    has_gradient = "gradient(" in css
    has_clip = "clip-path" in css
    has_outline = bool(re.search(r"border(?:-[\w]+)?\s*:", css))
    depth = "layered" if has_shadow else "outlined" if has_outline else "flat"
    if radius == "50%":
        shape = "circular accents with rectilinear content zones"
    elif radius != "0px":
        shape = "soft-corner modular surfaces"
    elif has_clip:
        shape = "angular clipped surfaces"
    else:
        shape = "rectilinear edge-defined surfaces"
    return {
        "surface": depth,
        "shape": shape,
        "corner_radius": radius,
        "background_layers": "multi-layer" if has_gradient else "flat",
        "separator": "structural" if re.search(r"divider|separator|rule|border", css, re.I) else "whitespace",
        "content_emphasis": content_dim,
        "decoration_family": deco_dim,
        "component_density": "dense" if card_heaviness >= 5 else "modular" if card_heaviness >= 2 else "open",
    }


def _style_tokens(typo_css, all_css, typo_dim, deco_dim):
    font_defaults = {
        "serif-classic": "Georgia,serif",
        "mixed-editorial": "Georgia,'Segoe UI',sans-serif",
        "mono-tech": "'Courier New',monospace",
        "large-display": "Impact,'Arial Narrow',sans-serif",
    }
    font = _token_value(typo_css, "font-family", font_defaults.get(typo_dim, "'Segoe UI',Arial,sans-serif"))
    size = _token_value(typo_css, "font-size", "44px")
    weight = _token_value(typo_css, "font-weight", "700")
    line_height = _token_value(typo_css, "line-height", "1.08")
    tracking = _token_value(typo_css, "letter-spacing", "-0.5px")
    shadow = _token_value(typo_css, "text-shadow", "none")
    return {
        "font_title": font,
        "font_body": "'Segoe UI',Arial,sans-serif" if typo_dim != "mono-tech" else "'Courier New',monospace",
        "title_size": size,
        "title_weight": weight,
        "title_line_height": line_height,
        "title_tracking": tracking,
        "title_shadow": shadow,
        "corner_radius": _most_common_radius(all_css),
        "border_width": "1px",
        "surface_shadow": (
            "0 8px 24px color-mix(in srgb,var(--ink-canvas) 14%,transparent)"
            if "box-shadow" in all_css or deco_dim in {"shadow-cards"}
            else "none"
        ),
    }


_COLOR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:white|black)\b",
    re.IGNORECASE,
)


def _semantic_content(code, source_luminance):
    """Keep BAMS component geometry while making every visual value theme-safe."""
    code = _semantic_colors(code, source_luminance)
    placeholders = {
        "{{SOURCE_DARK}}": "var(--surface-contrast)",
        "{{SOURCE_LIGHT}}": "var(--surface-canvas)",
        "{{SOURCE_ACCENT}}": "var(--accent-primary)",
        "{{SOURCE_INK_DARK}}": "var(--ink-canvas)",
        "{{SOURCE_INK_LIGHT}}": "var(--ink-contrast)",
    }
    for source, target in placeholders.items():
        code = code.replace(source, target)

    def rewrite_declaration(match):
        prop, value = match.group(1), match.group(2)
        normalized = prop.strip().lower()
        if normalized == "border-radius":
            return f"{prop}:var(--style-corner-radius)"
        if normalized in {"box-shadow", "text-shadow"}:
            return f"{prop}:var(--style-surface-shadow)"
        if normalized in {"color", "fill"}:
            token = "var(--ink-canvas)" if normalized == "color" else "var(--accent-primary)"
        elif normalized == "stroke" or normalized.startswith("border"):
            token = "var(--accent-primary)"
        elif normalized.startswith("background"):
            token = "var(--surface-muted)"
        else:
            token = "var(--accent-primary)"
        return f"{prop}:{_COLOR_LITERAL.sub(token, value)}"

    code = re.sub(r"([\w-]+)\s*:\s*([^;{}]+)", rewrite_declaration, code)
    return _COLOR_LITERAL.sub("var(--accent-primary)", code)


def build_library(catalog_path, components_path):
    catalog = {item["id"]: item for item in json.loads(Path(catalog_path).read_text())}
    components = json.loads(Path(components_path).read_text())
    specs = []

    for seed_id in sorted(components):
        source = catalog.get(seed_id)
        if not source:
            continue
        dims = source["dims"]
        comp = components[seed_id]
        typo_code = _semantic_colors(comp.get("typo", ""), dims["lum"])
        all_css = " ".join(
            [comp.get("layout", ""), comp.get("deco", ""), comp.get("sep", ""), typo_code]
            + [item.get("code", "") for item in comp.get("content", [])]
        )
        family = f"{dims['typo']}__{dims['deco']}"
        classes = " ".join(source.get("css_classes", [])).lower()
        card_heaviness = min(sum(classes.count(term) for term in ("card", "panel", "box")), 9)
        specs.append({
            "id": seed_id,
            "family": family,
            "dimensions": {
                key: dims.get(key)
                for key in ("typo", "deco", "bg", "content")
            },
            "tokens": _style_tokens(typo_code, all_css, dims["typo"], dims["deco"]),
            "element_grammar": _element_grammar(
                all_css,
                dims["deco"],
                dims.get("content", "unknown"),
                card_heaviness,
            ),
            "recipes": {
                "background": _semantic_background(comp.get("bg", ""), dims["lum"]),
                "separator": _semantic_colors(comp.get("sep", ""), dims["lum"]),
                "decoration": _semantic_colors(comp.get("deco", ""), dims["lum"]),
                "content": [
                    {
                        "content": item.get("content", dims.get("content", "unknown")),
                        "code": _semantic_content(item["code"], dims["lum"]),
                    }
                    for item in comp.get("content", [])
                ],
            },
            "card_heaviness": card_heaviness,
        })

    families = []
    grouped = defaultdict(list)
    for spec in specs:
        grouped[spec["family"]].append(spec)
    for family_id, members in sorted(grouped.items()):
        families.append({
            "id": family_id,
            "typo": members[0]["dimensions"]["typo"],
            "deco": members[0]["dimensions"]["deco"],
            "member_count": len(members),
            "backgrounds": dict(Counter(item["dimensions"]["bg"] for item in members)),
            "contents": dict(Counter(item["dimensions"]["content"] for item in members)),
            "members": members,
        })
    return {"version": 1, "spec_count": len(specs), "family_count": len(families), "families": families}


def main():
    parser = argparse.ArgumentParser(description="Build executable BAMS StyleSpec library")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--components", type=Path, default=DEFAULT_COMPONENTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_library(args.catalog, args.components)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {result['spec_count']} executable specs in {result['family_count']} families to {args.out}")


if __name__ == "__main__":
    main()
