#!/usr/bin/env python3
"""Extract structured pattern metadata from bams seed HTML slides.

Produces a pattern_catalog.json with:
  - layout structure (CSS classes, positioning model)
  - color scheme (backgrounds, text, accents)
  - decorative elements (SVG, gradients, clip-paths)
  - content slots (what semantic roles are present)
  - HTML skeleton (anonymized structure, no content)
"""

import argparse
import json, re, os
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
SEEDS_DIR = Path(os.environ.get("REDECK_BAMS_SEEDS", ROOT / "offline/style_seeds"))
LIBRARY_JSON = Path(os.environ.get("REDECK_PATTERN_CATALOG", ROOT / "pattern_library/metadata/pattern_catalog.json"))
OUT_DIR = ROOT / "pattern_library/metadata"


def extract_colors(css_text: str) -> dict:
    """Extract all colors from CSS."""
    hex_colors = re.findall(r'#[0-9a-fA-F]{3,8}\b', css_text)
    rgba_colors = re.findall(r'rgba?\([^)]+\)', css_text)

    # Classify colors
    bg_colors = []
    text_colors = []
    accent_colors = []

    # Find background-related colors
    for m in re.finditer(r'background[^;]*?([#][0-9a-fA-F]{3,8})', css_text):
        bg_colors.append(m.group(1))
    for m in re.finditer(r'background[^;]*?(rgba?\([^)]+\))', css_text):
        bg_colors.append(m.group(1))

    # Find text colors
    for m in re.finditer(r'(?<!background-)color\s*:\s*([#][0-9a-fA-F]{3,8})', css_text):
        text_colors.append(m.group(1))

    return {
        "all_hex": list(dict.fromkeys(hex_colors))[:20],  # dedupe, cap
        "backgrounds": list(dict.fromkeys(bg_colors))[:8],
        "text_colors": list(dict.fromkeys(text_colors))[:8],
    }


def extract_layout_model(css_text: str, html_text: str) -> dict:
    """Determine positioning model and layout structure."""
    abs_count = len(re.findall(r'position\s*:\s*absolute', css_text))
    grid_count = len(re.findall(r'display\s*:\s*grid', css_text))
    flex_count = len(re.findall(r'display\s*:\s*flex', css_text))

    if grid_count > 2:
        model = "grid"
    elif abs_count > 8:
        model = "absolute"
    elif flex_count > 3:
        model = "flex"
    else:
        model = "mixed"

    return {
        "model": model,
        "absolute_count": abs_count,
        "grid_count": grid_count,
        "flex_count": flex_count,
    }


def extract_decorative_elements(html_text: str) -> list:
    """Identify decorative techniques used."""
    decos = []
    if '<svg' in html_text:
        decos.append("svg")
    if 'clip-path' in html_text:
        decos.append("clip-path")
    if 'linear-gradient' in html_text:
        decos.append("linear-gradient")
    if 'radial-gradient' in html_text:
        decos.append("radial-gradient")
    if 'border-radius' in html_text:
        decos.append("border-radius")
    if 'box-shadow' in html_text:
        decos.append("box-shadow")
    if 'text-shadow' in html_text:
        decos.append("text-shadow")
    if 'opacity' in html_text:
        decos.append("opacity-layer")
    if re.search(r'mask-image|webkit-mask', html_text):
        decos.append("mask")
    if 'backdrop-filter' in html_text:
        decos.append("backdrop-filter")
    return decos


def extract_css_classes(html_text: str) -> list:
    """Extract all CSS class names used in the HTML."""
    classes = re.findall(r'class="([^"]*)"', html_text)
    all_classes = []
    for c in classes:
        all_classes.extend(c.split())
    return sorted(set(all_classes))


def extract_semantic_slots(classes: list, html_text: str) -> list:
    """Identify semantic content slots from class names."""
    slot_keywords = {
        "title": ["title", "heading", "headline"],
        "subtitle": ["subtitle", "sub-title", "tagline"],
        "body_text": ["body", "desc", "description", "content", "text", "paragraph", "intro"],
        "metric": ["metric", "kpi", "stat", "number", "num", "value", "big-number"],
        "chart": ["chart", "bar", "donut", "pie", "graph"],
        "table": ["table", "row", "cell", "grid-data", "header"],
        "timeline": ["timeline", "time", "date", "year", "phase", "step"],
        "icon": ["icon", "badge", "circle-icon", "logo"],
        "card": ["card", "panel", "box"],
        "list": ["list", "bullet", "item"],
        "image": ["img", "image", "photo", "figure"],
        "quote": ["quote", "testimonial"],
        "label": ["label", "tag", "category"],
        "separator": ["divider", "separator", "rule", "line"],
        "navigation": ["nav", "tab", "menu"],
    }

    found = set()
    cls_lower = " ".join(classes).lower()
    for slot, keywords in slot_keywords.items():
        for kw in keywords:
            if kw in cls_lower:
                found.add(slot)
                break

    # Also check HTML content
    if '<table' in html_text:
        found.add("table")
    if '<svg' in html_text and any(t in html_text for t in ['<rect', '<circle', '<path']):
        found.add("chart")  # might be decorative though

    return sorted(found)


def extract_skeleton(html_text: str) -> str:
    """Create an anonymized HTML skeleton showing structure without content.

    Keeps: tag hierarchy, class names, key CSS properties
    Removes: actual text content, specific pixel values, colors
    """
    # Extract the body content between <body> or after </style>
    body_match = re.search(r'</style>\s*(.*?)</body>', html_text, re.DOTALL)
    if not body_match:
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html_text, re.DOTALL)
    if not body_match:
        return ""

    body = body_match.group(1).strip()

    # Simplify: remove text content but keep structure
    # Replace text between tags with placeholder
    skeleton = re.sub(r'>([^<]{1,200})<', '>…<', body)
    # Remove inline styles (they're in the CSS anyway)
    skeleton = re.sub(r'\s*style="[^"]*"', '', skeleton)
    # Collapse whitespace
    skeleton = re.sub(r'\n\s*\n', '\n', skeleton)

    # Truncate if too long
    if len(skeleton) > 2000:
        skeleton = skeleton[:2000] + "\n<!-- truncated -->"

    return skeleton


def compute_luminance(hex_color: str) -> float:
    """Rough luminance from hex color."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 3:
        hex_color = ''.join(c*2 for c in hex_color)
    if len(hex_color) < 6:
        return 0.5
    try:
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255
    except:
        return 0.5


def classify_theme(colors: dict) -> str:
    """Classify as dark/light/medium based on background colors."""
    bg = colors.get("backgrounds", [])
    if not bg:
        return "unknown"
    hex_bgs = [c for c in bg if c.startswith('#')]
    if not hex_bgs:
        return "unknown"
    avg_lum = sum(compute_luminance(c) for c in hex_bgs[:3]) / min(len(hex_bgs), 3)
    if avg_lum < 0.3:
        return "dark"
    elif avg_lum > 0.7:
        return "light"
    return "medium"


def process_seed(seed_id: str, html_path: Path, dims: dict) -> dict:
    """Process one seed HTML into structured metadata."""
    html = html_path.read_text(errors='replace')

    # Extract CSS block
    css_match = re.search(r'<style[^>]*>(.*?)</style>', html, re.DOTALL)
    css_text = css_match.group(1) if css_match else ""

    # Title
    title_match = re.search(r'<title>([^<]+)</title>', html)
    title = title_match.group(1).strip() if title_match else ""

    colors = extract_colors(css_text)
    layout = extract_layout_model(css_text, html)
    decos = extract_decorative_elements(html)
    classes = extract_css_classes(html)
    slots = extract_semantic_slots(classes, html)
    skeleton = extract_skeleton(html)
    theme = classify_theme(colors)

    return {
        "id": seed_id,
        "title": title,
        "dims": dims,
        "theme": theme,
        "layout": layout,
        "colors": colors,
        "decorations": decos,
        "semantic_slots": slots,
        "css_classes": classes,
        "skeleton": skeleton,
        "file_size": html_path.stat().st_size,
        "css_length": len(css_text),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds-dir", type=Path, default=SEEDS_DIR)
    parser.add_argument("--catalog", type=Path, default=LIBRARY_JSON)
    parser.add_argument("--out", type=Path, default=OUT_DIR / "pattern_catalog.json")
    args = parser.parse_args(argv)
    seed_files = sorted(args.seeds_dir.glob("seed_*.html"))
    if not seed_files:
        parser.error(f"No seed_*.html files under {args.seeds_dir}; supply authorized offline seeds")
    with args.catalog.open() as source:
        library = json.load(source)
    dims_by_id = {item["id"]: item["dims"] for item in library}
    missing = [path.stem for path in seed_files if path.stem not in dims_by_id]
    if missing:
        parser.error(f"Catalog is missing dimension metadata for: {', '.join(missing)}")

    catalog = []
    print(f"Processing {len(seed_files)} seed slides...")

    for seed_path in seed_files:
        seed_id = seed_path.stem
        dims = dims_by_id[seed_id]
        entry = process_seed(seed_id, seed_path, dims)
        catalog.append(entry)

    # Write catalog
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('w') as destination:
        json.dump(catalog, destination, indent=2, ensure_ascii=False)
    print(f"Wrote {len(catalog)} patterns to {args.out}")

    # Summary stats
    print(f"\n--- Summary ---")
    theme_dist = Counter(p["theme"] for p in catalog)
    print(f"Themes: {dict(theme_dist)}")

    layout_dist = Counter(p["layout"]["model"] for p in catalog)
    print(f"Layout models: {dict(layout_dist)}")

    deco_dist = Counter()
    for p in catalog:
        deco_dist.update(p["decorations"])
    print(f"Top decorations: {deco_dist.most_common(8)}")

    slot_dist = Counter()
    for p in catalog:
        slot_dist.update(p["semantic_slots"])
    print(f"Top slots: {slot_dist.most_common(10)}")

    # File size distribution
    sizes = [p["file_size"] for p in catalog]
    print(f"File size: min={min(sizes)}, max={max(sizes)}, avg={sum(sizes)//len(sizes)}")


if __name__ == "__main__":
    main()
