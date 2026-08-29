"""Compose design elements from vocabulary — layout skeleton + domain-aware style injection.

Core insight: the prompt's main guidance is a LAYOUT SKELETON
(natural language spatial description) + COLOR SCHEME + ANTI-CARD RULES.
Style element CSS snippets are just secondary flavor — 200 chars each, max.

The deck consistency is handled by the existing serial generation + CSS anchor
mechanism in html_codegen_compiler.py (same as template mode).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
from collections import defaultdict

_VOCAB_PATH = Path(__file__).parent / "element_vocab.json"
_VOCAB: list[dict] | None = None
_BY_CAT: dict[str, list[dict]] | None = None


def _load_vocab() -> tuple[list[dict], dict[str, list[dict]]]:
    global _VOCAB, _BY_CAT
    if _VOCAB is None:
        _VOCAB = json.loads(_VOCAB_PATH.read_text("utf-8"))
        _BY_CAT = defaultdict(list)
        for v in _VOCAB:
            _BY_CAT[v.get("category", "other")].append(v)
    return _VOCAB, _BY_CAT


# ═══════════════════════════════════════════════════════════════════
# 20 Layout Skeletons (real PPT layout patterns)
# ═══════════════════════════════════════════════════════════════════

LAYOUTS = [
    {"id": "header_grid", "desc": "Full-width header band (top 12%) with colored background. Content in 2×2 or 3×2 grid below. Footer strip at bottom.", "deco": "moderate"},
    {"id": "left_sidebar", "desc": "Left sidebar panel (width 25%, full height, dark/colored). Main content on right 75%. Title inside sidebar.", "deco": "minimal"},
    {"id": "right_sidebar", "desc": "Main content on left 70%. Right sidebar (30%) with summary/highlights on colored background.", "deco": "minimal"},
    {"id": "top_heavy", "desc": "Large top section (top 40%) with colored/gradient background and big title. Compact content grid in bottom 60% on white/light.", "deco": "moderate"},
    {"id": "bottom_table", "desc": "Title strip at top (10%). Full-width data table occupies remaining 85% of slide. Clean table with header row and alternating subtle row colors. No cards.", "deco": "none"},
    {"id": "three_column", "desc": "Three equal vertical columns separated by thin vertical lines. Each column has its own mini-title and content. No cards, just column division.", "deco": "minimal"},
    {"id": "two_column_split", "desc": "Left half has colored background with white text. Right half has white/light background with dark text. Split down the middle.", "deco": "minimal"},
    {"id": "diagonal_split", "desc": "Diagonal division: upper-left triangle is colored, lower-right is white. Title on colored area, content on white area.", "deco": "moderate"},
    {"id": "center_focus", "desc": "One large central element (big number, key message, or diagram) occupying 60% of area. Supporting text around periphery in small font. Lots of breathing room.", "deco": "minimal"},
    {"id": "timeline_horizontal", "desc": "Title at top. Horizontal timeline line across middle of slide. Milestone nodes (circles/diamonds) on the line with labels above and below, alternating.", "deco": "moderate"},
    {"id": "full_bleed_dark", "desc": "Entire slide is dark (navy/charcoal gradient). Content arranged with generous spacing. Accent color for highlights. Numbers/titles directly on dark background.", "deco": "moderate"},
    {"id": "minimal_white", "desc": "Clean white background. Title top-left, large font. Content below with generous whitespace. One thin accent line or small color element only. Extremely clean.", "deco": "none"},
    {"id": "stepped_rows", "desc": "4-5 horizontal strips/rows spanning full width. Each row slightly different shade or separated by thin lines. Content in each row. Like a Kanban or stepped list.", "deco": "minimal"},
    {"id": "l_shape", "desc": "L-shaped colored area: top header band + left sidebar connected. Content in the remaining space (bottom-right rectangle).", "deco": "moderate"},
    {"id": "floating_panels", "desc": "Dark or gradient background. 3-4 semi-transparent panels (NOT rounded cards — use sharp corners, subtle bg tint, no border-radius) floating at different positions.", "deco": "moderate"},
    {"id": "data_dashboard", "desc": "Dense grid layout: top row has 3-4 large KPI numbers. Below is a chart area (bar chart or table). Bottom has footnotes. All text directly placed, no cards.", "deco": "none"},
    {"id": "process_chevron", "desc": "4-5 chevron/arrow shapes in a horizontal row, each containing a step number and title. Connected visually. Below each chevron is description text.", "deco": "moderate"},
    {"id": "quote_centered", "desc": "Large quotation marks as decorative element. Quote text centered in large italic font. Attribution below. Mostly empty space around the quote. Elegant.", "deco": "rich"},
    {"id": "comparison_table", "desc": "Title at top. Below: 2-3 columns with header labels. Rows of comparison data aligned. Thin borders between cells, header row has colored background. NOT cards.", "deco": "none"},
    {"id": "icon_grid", "desc": "Title at top. Below: 2×3 or 3×2 grid where each cell has a simple icon/symbol (SVG or unicode) + short label underneath. No boxes around icons, just evenly spaced.", "deco": "moderate"},
]
_LAYOUT_MAP = {l["id"]: l for l in LAYOUTS}

# ═══════════════════════════════════════════════════════════════════
# Domain preferences (natural language color scheme + layout skeleton)
# ═══════════════════════════════════════════════════════════════════

DOMAIN_PREFS = {
    "cs_ml": {
        "preferred_layouts": ["data_dashboard", "full_bleed_dark", "left_sidebar", "header_grid", "comparison_table"],
        "color_scheme": "Dark navy (#1B2838) background with electric blue (#3A86FF) accents and teal (#2EC4B6) secondary. White text. Professional tech feel.",
        "decoration_level": "minimal to moderate",
        "icon_style": "If icons needed: simple line icons (code brackets, neural network nodes, chart) in accent color",
        "bg_tags": ["dark", "cool"],
    },
    "bio_med": {
        "preferred_layouts": ["minimal_white", "bottom_table", "left_sidebar", "two_column_split", "comparison_table"],
        "color_scheme": "White background. Dark navy or teal (#0D9488) text. One accent color (coral #F97316 or blue #3B82F6). Clinical, clean.",
        "decoration_level": "none",
        "icon_style": "Almost no icons. If needed: simple numbered circles. Focus on tables and clean text.",
        "bg_tags": ["light"],
    },
    "finance": {
        "preferred_layouts": ["data_dashboard", "bottom_table", "header_grid", "full_bleed_dark", "stepped_rows"],
        "color_scheme": "Dark backgrounds (#0F2027 to #203A43). Green (#22C55E) for positive, red (#EF4444) for negative. Gold (#F0A850) accents. Conservative, executive.",
        "decoration_level": "none to minimal",
        "icon_style": "Minimal. Focus on numbers and data visualization (bars, arrows indicating trend).",
        "bg_tags": ["dark", "cool"],
    },
    "physics": {
        "preferred_layouts": ["full_bleed_dark", "left_sidebar", "data_dashboard", "two_column_split", "comparison_table"],
        "color_scheme": "Deep dark (#0A0A1A to #1A1A2E). Primary: purple (#7C3AED). Secondary: cyan (#06B6D4). Amber (#F59E0B) for highlights. Scientific, precise.",
        "decoration_level": "minimal",
        "icon_style": "Clean geometric elements. Axis lines, equation-style notation.",
        "bg_tags": ["dark"],
    },
    "social": {
        "preferred_layouts": ["header_grid", "three_column", "icon_grid", "top_heavy", "timeline_horizontal"],
        "color_scheme": "Warm light (#FFF8F0 to #FFFFFF). Warm orange (#EA580C) primary, earthy green (#65A30D) secondary. Deep brown (#78350F) for text. Approachable, editorial.",
        "decoration_level": "moderate",
        "icon_style": "Friendly rounded icons. Editorial lines, pull-quote styling.",
        "bg_tags": ["light", "warm"],
    },
}

# Role → layout affinity
ROLE_LAYOUTS = {
    "title": ["center_focus", "full_bleed_dark", "diagonal_split", "top_heavy"],
    "data": ["data_dashboard", "bottom_table", "header_grid", "full_bleed_dark"],
    "method": ["left_sidebar", "three_column", "l_shape", "floating_panels"],
    "comparison": ["comparison_table", "two_column_split", "three_column", "bottom_table"],
    "results": ["data_dashboard", "header_grid", "full_bleed_dark", "bottom_table"],
    "conclusion": ["center_focus", "minimal_white", "full_bleed_dark", "two_column_split"],
    "process": ["process_chevron", "stepped_rows", "timeline_horizontal", "three_column"],
    "architecture": ["floating_panels", "three_column", "l_shape", "center_focus"],
}


def _select_layout(rng: random.Random, domain: str, role: str) -> dict:
    """Select layout skeleton based on domain + slide role."""
    domain_layouts = DOMAIN_PREFS.get(domain, {}).get("preferred_layouts", [])
    role_layouts = ROLE_LAYOUTS.get(role, [])

    # Try intersection first
    both = [l for l in domain_layouts if l in role_layouts]
    if both and rng.random() < 0.5:
        layout_id = rng.choice(both)
    elif role_layouts and rng.random() < 0.6:
        layout_id = rng.choice(role_layouts)
    elif domain_layouts:
        layout_id = rng.choice(domain_layouts)
    else:
        layout_id = rng.choice([l["id"] for l in LAYOUTS])

    return _LAYOUT_MAP.get(layout_id, rng.choice(LAYOUTS))


def _select_style_elements(rng: random.Random, decoration_level: str, is_dark: bool) -> list[str]:
    """Select a few style element CSS snippets — kept short (200 chars each).

    Filters elements to match the domain's light/dark preference to prevent
    the LLM from picking up conflicting color cues.
    """
    _, by_cat = _load_vocab()
    elements: list[str] = []

    def _is_dark_element(code: str) -> bool:
        """Heuristic: does this CSS snippet use dark colors?"""
        # Check for dark hex colors or rgba with low values
        import re
        hex_colors = re.findall(r'#([0-9a-fA-F]{6})', code)
        if hex_colors:
            avg_brightness = sum(
                (int(h[0:2], 16) + int(h[2:4], 16) + int(h[4:6], 16)) / 3
                for h in hex_colors[:3]
            ) / min(len(hex_colors), 3)
            return avg_brightness < 128
        return 'rgba(0' in code or 'rgba(1' in code or 'rgba(2' in code

    # Background — filter by light/dark match
    bg_pool = [e for e in by_cat.get("background", [])
               if _is_dark_element(e["code"]) == is_dark]
    if not bg_pool:  # fallback
        bg_pool = by_cat.get("background", [])
    if bg_pool:
        elements.append(rng.choice(bg_pool)["code"][:200])

    # Typography — no filtering needed (font styles are color-agnostic mostly)
    typo_pool = by_cat.get("typography", [])
    if typo_pool:
        elements.append(rng.choice(typo_pool)["code"][:200])

    # Decoration based on level
    if decoration_level in ("moderate", "rich") and by_cat.get("decoration"):
        n = 2 if decoration_level == "rich" else 1
        for _ in range(n):
            elements.append(rng.choice(by_cat["decoration"])["code"][:200])

    # Separator for visual rhythm
    if by_cat.get("separator") and rng.random() < 0.4:
        elements.append(rng.choice(by_cat["separator"])["code"][:150])

    return elements


def compose_style_elements(
    paper_title: str,
    paper_domain: str | None = None,
) -> dict:
    """Compose design elements from vocabulary for a deck.

    Returns dict with domain_style, style_elements, and a
    per-deck layout seed (the deck picks layouts per slide from
    the same pool for consistency).
    """
    from .selector import _detect_domain

    domain = paper_domain or _detect_domain(paper_title)
    prefs = DOMAIN_PREFS.get(domain, DOMAIN_PREFS["cs_ml"])

    seed = int(hashlib.md5(paper_title.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # Determine if this domain prefers dark backgrounds
    is_dark = any(t in ("dark", "cool") for t in prefs.get("bg_tags", []))

    style_elements = _select_style_elements(rng, prefs.get("decoration_level", "minimal"), is_dark)

    return {
        "domain": domain,
        "prefs": prefs,
        "style_elements": style_elements,
        "seed": seed,
    }


def format_vocab_style_contract(
    paper_title: str,
    paper_domain: str | None = None,
    slide_role: str | None = None,
) -> str:
    """Format vocab-composed style as a structured prompt injection.

    Deck consistency: color scheme + style elements are FIXED per paper_title.
    Only the layout skeleton varies per slide role.
    """
    comp = compose_style_elements(paper_title, paper_domain)
    prefs = comp["prefs"]

    # Layout uses a SEPARATE RNG seeded by role, so it doesn't disturb
    # the deck-level style element selection
    layout_seed = comp["seed"] ^ hash(slide_role or "data")
    layout_rng = random.Random(layout_seed)
    layout = _select_layout(layout_rng, comp["domain"], slide_role or "data")

    return f"""## DECK DESIGN SYSTEM — MANDATORY for every slide

### COLOR SCHEME (MUST follow exactly)
{prefs['color_scheme']}

### LAYOUT (follow this spatial arrangement)
{layout['desc']}

### DECORATION LEVEL: {prefs.get('decoration_level', 'minimal')}
### ICONS: {prefs.get('icon_style', 'None needed')}

### STRICT RULES
1. Follow the LAYOUT description above for spatial organization
2. DO NOT use rounded-corner cards, card grids, or box-shadow containers
3. Use the color scheme specified — define `:root` variables with `--bg`, `--text`, `--primary`, `--secondary`, `--accent`
4. Respect the decoration level — if "none" → NO decorative elements, just clean structure
5. Use position:absolute for element placement (1280×720px, overflow:hidden)
6. All content must be visible and readable with sufficient contrast
7. DO NOT use generic web patterns (hero sections, call-to-action buttons, flexbox card layouts)
8. This is a PRESENTATION SLIDE, not a web page — use PPT-style composition
9. EVERY slide in this deck MUST use the SAME background color/gradient and text color
"""
