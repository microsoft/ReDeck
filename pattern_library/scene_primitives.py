"""Compile executable visual primitives from a BAMS scene reference.

These snippets preserve the source's visual language without exposing its full
DOM, text, or fixed page geometry. Theme variables remain the only color source.
"""

import json
import re
import colorsys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPONENTS = ROOT / "pattern_library" / "metadata" / "seed_components.json"
DEFAULT_CATALOG = ROOT / "pattern_library" / "metadata" / "pattern_catalog.json"
DEFAULT_SEEDS = Path(os.environ.get("REDECK_BAMS_SEEDS", ROOT / "offline/style_seeds"))


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


def _trim(code, limit=1500):
    code = " ".join((code or "").split())
    return code if len(code) <= limit else code[:limit].rstrip() + " /* … */"


def _hex_rgb(value):
    raw = value.lstrip("#")
    if len(raw) == 3:
        raw = "".join(char * 2 for char in raw)
    if len(raw) not in {6, 8}:
        return None
    return tuple(int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4))


def _semanticize_svg(svg, source_luminance):
    """Preserve chromatic role separation while removing literal source colors."""
    role_tokens = [
        "var(--accent-primary)",
        "var(--accent-secondary)",
        "var(--accent-tertiary)",
        "var(--accent-signal)",
    ]
    color_map = {}

    def replace(match):
        color = match.group(0)
        key = color.lower()
        if key in color_map:
            return color_map[key]
        rgb = _hex_rgb(color)
        if not rgb:
            return color
        hue, saturation, lightness = colorsys.rgb_to_hls(*rgb)
        if saturation < 0.12:
            if lightness > 0.72:
                token = "var(--ink-canvas)" if source_luminance != "light" else "var(--surface-canvas)"
            elif lightness < 0.22:
                token = "var(--surface-canvas)" if source_luminance != "light" else "var(--ink-canvas)"
            else:
                token = "var(--ink-canvas)" if source_luminance != "light" else "var(--ink-contrast)"
        else:
            chromatic_index = sum(value in role_tokens for value in color_map.values())
            token = role_tokens[chromatic_index % len(role_tokens)]
        color_map[key] = token
        return token

    svg = re.sub(r"#[0-9a-fA-F]{3,8}\b", replace, svg)
    def replace_rgb(match):
        red, green, blue = (int(match.group(index)) for index in (1, 2, 3))
        alpha = float(match.group(4) or 1)
        brightness = (red * 299 + green * 587 + blue * 114) / 255000
        if max(red, green, blue) - min(red, green, blue) > 36:
            token = "var(--accent-primary)"
        elif brightness > 0.58:
            token = "var(--ink-canvas)" if source_luminance != "light" else "var(--surface-canvas)"
        else:
            # Mid-value neutral strokes are commonly the visible linework of
            # a dark BAMS motif. Mapping them to the dark muted surface makes
            # them disappear after instance opacity is applied.
            token = "var(--ink-canvas)" if source_luminance != "light" else "var(--ink-contrast)"
        if alpha >= 0.99:
            return token
        return f"color-mix(in srgb,{token} {round(alpha * 100)}%,transparent)"

    svg = re.sub(
        r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*([01]?(?:\.\d+)?))?\s*\)",
        replace_rgb,
        svg,
        flags=re.I,
    )
    svg = re.sub(r"\s+(?:aria-label|title)=(['\"]).*?\1", "", svg, flags=re.I)
    return " ".join(svg.split())


def _signature_motifs(seed_path, source_luminance, max_items=3, max_total=6500):
    if not seed_path.exists():
        return []
    html = seed_path.read_text(errors="replace")
    svgs = re.findall(r"<svg\b[^>]*>.*?</svg>", html, re.I | re.S)
    candidates = []
    for svg in svgs:
        if re.search(r"<(?:text|foreignObject)\b", svg, re.I):
            continue
        primitives = len(re.findall(r"<(?:path|polygon|polyline|circle|rect|line|ellipse)\b", svg, re.I))
        gradients = len(re.findall(r"<(?:linearGradient|radialGradient|pattern|filter)\b", svg, re.I))
        if primitives < 2 or len(svg) < 140:
            continue
        score = min(len(svg), 5000) + primitives * 90 + gradients * 300
        candidates.append((score, svg))
    output, total = [], 0
    for _, svg in sorted(candidates, reverse=True):
        clean = _semanticize_svg(svg, source_luminance)
        if total + len(clean) > max_total:
            continue
        output.append(clean)
        total += len(clean)
        if len(output) == max_items:
            break
    return output


class ScenePrimitiveLibrary:
    def __init__(self, components_path=None, catalog_path=None, seeds_path=None):
        self.components = json.loads(Path(components_path or DEFAULT_COMPONENTS).read_text())
        self.catalog = {
            item["id"]: item for item in json.loads(Path(catalog_path or DEFAULT_CATALOG).read_text())
        }
        self.seeds_path = Path(seeds_path or DEFAULT_SEEDS)

    def compile(self, reference_id, targets=None):
        component = self.components.get(reference_id, {})
        catalog = self.catalog.get(reference_id, {})
        dims = catalog.get("dims", {})
        luminance = dims.get("lum", "light")
        recipes = {}
        for key in ("bg", "typo", "sep", "deco"):
            code = _semantic_colors(component.get(key, ""), luminance)
            if code:
                recipes[key] = _trim(code)

        # The original page may use several chromatic roles. Preserve the role
        # count while Theme supplies the actual colors.
        source_colors = catalog.get("colors", {}).get("backgrounds", [])
        chromatic_roles = min(4, max(1, len(source_colors) // 2))
        motif_program = _signature_motifs(
            self.seeds_path / f"{reference_id}.html", luminance
        )

        targets = targets or []
        compatible = [
            item for item in component.get("content", [])
            if item.get("content") in targets[:3]
        ]
        if compatible:
            chosen = min(compatible, key=lambda item: targets.index(item["content"]))
            recipes["content"] = _trim(_semantic_colors(chosen["code"], luminance))

        return {
            "reference_id": reference_id,
            "dimensions": {
                key: dims.get(key) for key in ("lum", "typo", "deco", "bg", "content")
            },
            "recipes": recipes,
            "chromatic_roles": chromatic_roles,
            "motif_program": motif_program,
            "rule": (
                "Use these primitives as the page's native visual language. Adapt selectors and scale, "
                "but preserve their characteristic background construction, type gesture, separator, "
                "and motif geometry. They override generic deck-level component styling."
            ),
        }


def format_scene_primitives(spec):
    labels = {
        "bg": "NATIVE BACKGROUND",
        "typo": "NATIVE TYPOGRAPHIC GESTURE",
        "sep": "NATIVE SEPARATOR",
        "deco": "NATIVE MOTIF PRIMITIVE",
        "content": "NATIVE CONTENT PRIMITIVE",
    }
    lines = [
        "## SCENE-NATIVE EXECUTABLE PRIMITIVES",
        f"BAMS source `{spec['reference_id']}`; dimensions: "
        + ", ".join(f"{key}={value}" for key, value in spec["dimensions"].items()),
        spec["rule"],
        f"Chromatic role count: {spec['chromatic_roles']}. Use primary, secondary, tertiary, and signal "
        "tokens as needed to preserve the source's color-role separation; do not recolor everything primary.",
    ]
    for key in ("bg", "typo", "sep", "deco", "content"):
        code = spec["recipes"].get(key)
        if not code:
            continue
        language = "html" if code.lstrip().startswith("<") else "css"
        lines.extend([f"**{labels[key]}**", f"```{language}\n{code}\n```"])
    if spec.get("motif_program"):
        lines.extend([
            "**SIGNATURE MOTIF PROGRAM — real geometry, no source text or page DOM**",
            "Use at least one of these as a visually significant system (roughly 20–55% of the canvas), "
            "not as a tiny badge. You may crop, mirror, rotate, recolor through the supplied variables, "
            "or repeat subparts; do not reproduce the source's full-page placement.",
        ])
        for motif in spec["motif_program"]:
            lines.append(f"```html\n{motif}\n```")
    lines.append(
        "Implement at least the background and typography primitives, plus every supplied separator/motif "
        "primitive. Do not replace them with a generic top bar, card grid, or house-style decoration."
    )
    return "\n\n".join(lines)
