#!/usr/bin/env python3
"""Build the runtime semantic theme library from color-only source palettes."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "pattern_library" / "metadata" / "palette_sources.json"
DEFAULT_OUTPUT = ROOT / "pattern_library" / "metadata" / "theme_library.json"

_DARK_SURFACE_SOFT = {
    "blue-corporate": "#c8ddf0", "red-accent": "#f0d0d0",
    "purple-violet": "#d8ccf0", "green-forest": "#c8e8d0",
    "teal-cool": "#c0e8e8", "orange-sunset": "#f0dcc0",
    "earth-warm": "#f0e0d0", "gray-mono": "#d8d8d8",
    "multi-vibrant": "#e0d8f0", "pastel-soft": "#e8e0f0",
}

_ACCENT_HARMONY = {
    "blue-corporate": ("#35b7d3", "#7d9ee8", "#f0b84b"),
    "red-accent": ("#f06a4d", "#b54db1", "#f2b84b"),
    "purple-violet": ("#d477ff", "#6d8cff", "#f0a6d8"),
    "green-forest": ("#78a85a", "#c7a45a", "#73aaa0"),
    "teal-cool": ("#32b7ba", "#4b88c8", "#d9a441"),
    "orange-sunset": ("#f09545", "#d94b6d", "#7658b7"),
    "earth-warm": ("#ce8050", "#8e7654", "#7c9670"),
    "gray-mono": ("#747b85", "#b2b6bd", "#d3a84a"),
    "multi-vibrant": ("#e43d82", "#22b59f", "#f2b62f"),
    "pastel-soft": ("#e9a7b8", "#8fcfc6", "#b9a5df"),
}


def _luminance(color):
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    channels = [int(value[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first, second):
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _best_ink(background, candidates):
    return max(candidates, key=lambda color: _contrast(background, color))


def _mix(first, second, second_weight):
    def channels(color):
        value = color.lstrip("#")
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))

    left, right = channels(first), channels(second)
    mixed = tuple(round(a * (1 - second_weight) + b * second_weight) for a, b in zip(left, right))
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def build_theme_library(path):
    result = []
    for source in json.loads(Path(path).read_text()):
        palette = dict(source["palette"])
        if palette.get("bg_light") == "#808080":
            palette["bg_light"] = _DARK_SURFACE_SOFT.get(source["palette_name"], "#d0d0d0")
        if palette.get("text_dark") == "#808080":
            palette["text_dark"] = "#1a1a2e"
        if source["luminance"] == "light":
            canvas, contrast = palette["bg_light"], palette["bg_dark"]
        else:
            canvas, contrast = palette["bg_dark"], palette["bg_light"]
        accent = palette["accent"]
        secondary, tertiary, signal = _ACCENT_HARMONY.get(
            source["palette_name"],
            (_mix(accent, contrast, 0.28), _mix(accent, canvas, 0.32), _mix(accent, "#f0b84b", 0.5)),
        )
        if _contrast(canvas, contrast) < 1.15:
            contrast = _mix(canvas, accent, 0.18)
        muted = _mix(canvas, accent, 0.08)
        # Extracted text colors can themselves be chromatic or placeholders.
        # Neutral extrema guarantee readable text while still allowing a source
        # ink to win when it genuinely has the highest contrast.
        inks = (palette["text_dark"], palette["text_light"], "#000000", "#ffffff")
        result.append({
            "id": source["id"],
            "palette_name": source["palette_name"],
            "luminance": source["luminance"],
            "tokens": {
                "surface_canvas": canvas,
                "surface_contrast": contrast,
                "surface_muted": muted,
                "accent_primary": accent,
                "accent_secondary": secondary,
                "accent_tertiary": tertiary,
                "accent_signal": signal,
                "ink_canvas": _best_ink(canvas, inks),
                "ink_contrast": _best_ink(contrast, inks),
                "ink_accent": _best_ink(accent, inks),
            },
        })
    return {"version": 1, "theme_count": len(result), "themes": sorted(result, key=lambda item: item["id"])}


def main():
    parser = argparse.ArgumentParser(description="Build semantic runtime theme library")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_theme_library(args.input)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {result['theme_count']} semantic themes to {args.out}")


if __name__ == "__main__":
    main()
