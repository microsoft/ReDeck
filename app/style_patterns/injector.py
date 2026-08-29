"""Format a design pattern as a deck-level style contract for prompt injection."""

from __future__ import annotations

import re


def format_deck_style_contract(pattern: dict) -> str:
    """Format pattern with real CSS + deck consistency anchors.

    Injects the actual CSS from the pattern seed, plus explicit CSS custom properties
    that MUST be used across all slides to ensure deck-level consistency.
    """
    dims = pattern.get("dims", {})
    css = pattern.get("css_snippet", "")

    # Truncate if too long
    if len(css) > 1800:
        css = css[:1800] + "\n/* ... truncated ... */"

    lum = dims.get("lum", "light")
    bg = dims.get("bg", "solid")
    palette = dims.get("palette", "blue-cool")
    deco = dims.get("deco", "none")
    typo = dims.get("typo", "sans-clean")

    # Extract CSS custom properties and key colors from the pattern
    css_vars = _extract_css_vars(css)
    colors = _extract_colors(css)

    # Build a mandatory :root block for deck consistency
    root_block = _build_root_block(css_vars, colors, lum)

    # Extract the background CSS to enforce on every slide
    bg_css = _extract_background(css)

    return f"""
## DECK DESIGN SYSTEM — Apply to EVERY slide (highest priority)

This design system defines the visual identity for the entire deck. Every slide MUST use these exact colors, background, and decorative style.

### Mandatory CSS Variables (copy into every slide's :root)
```css
{root_block}
```

### Mandatory Background (copy this EXACT background to every slide's body/.slide)
```css
{bg_css}
```

### Reference Design (adapt this aesthetic — same colors, same background, same decorative elements):
```css
{css}
```

### Design Identity
- Background: {bg} ({lum} luminance)
- Palette: {palette}
- Decoration: {deco} — include matching decorative elements on every slide
- Typography: {typo}

### Deck Consistency Rules
- Every slide MUST start with the exact `:root` variables above
- Background treatment must be IDENTICAL on every slide — copy the exact background CSS from the reference
- ALL colors on the slide must come from the `:root` variables or the reference CSS palette — do NOT introduce new colors (no random greens, blues, oranges not in the palette)
- Decorative elements (shapes, lines, patterns) must use the same style throughout
- Never use plain white background or generic card-based layouts
- The deck should feel like ONE cohesive designed template, not independent pages
- If the reference uses radial-gradient, EVERY slide must use radial-gradient with the same colors
"""


def _extract_css_vars(css: str) -> dict[str, str]:
    """Extract CSS custom property declarations."""
    vars_dict = {}
    for m in re.finditer(r'(--[\w-]+)\s*:\s*([^;]+);', css):
        vars_dict[m.group(1)] = m.group(2).strip()
    return vars_dict


def _extract_colors(css: str) -> list[str]:
    """Extract color values from CSS."""
    colors = set()
    # hex colors
    for m in re.finditer(r'#([0-9a-fA-F]{3,8})\b', css):
        colors.add('#' + m.group(1))
    # rgb/rgba
    for m in re.finditer(r'(rgba?\([^)]+\))', css):
        colors.add(m.group(1))
    return sorted(colors, key=lambda c: len(c))[:10]


def _build_root_block(css_vars: dict, colors: list, lum: str) -> str:
    """Build a :root block with FULL color palette for deck consistency.

    Extracts as many colors as possible so the LLM has a complete palette
    and doesn't need to invent new colors.
    """
    if css_vars:
        lines = [":root {"]
        for k, v in list(css_vars.items())[:15]:
            lines.append(f"  {k}: {v};")
        # If fewer than 6 vars, supplement with extracted colors
        if len(css_vars) < 6 and colors:
            for i, c in enumerate(colors[:6]):
                varname = f"--color-{i+1}"
                if varname not in css_vars:
                    lines.append(f"  {varname}: {c};")
        lines.append("}")
        return "\n".join(lines)

    # No CSS vars found — build from extracted colors
    lines = [":root {"]
    if lum == "dark":
        bg = next((c for c in colors if _is_dark(c)), colors[0] if colors else "#0a0e1a")
        text = "#e8eaf0"
    else:
        bg = next((c for c in colors if not _is_dark(c)), colors[-1] if colors else "#f8f9fa")
        text = "#1a1a2e"

    lines.append(f"  --bg: {bg};")
    lines.append(f"  --text: {text};")

    # Assign all extracted colors as named variables
    roles = ["--primary", "--secondary", "--accent", "--highlight", "--muted", "--surface"]
    for i, c in enumerate(colors[:len(roles)]):
        lines.append(f"  {roles[i]}: {c};")

    lines.append("}")
    lines.append("/* USE ONLY THESE COLORS — do not introduce new hues */")
    return "\n".join(lines)


def _is_dark(color: str) -> bool:
    """Check if a hex color is dark."""
    if not color.startswith('#'):
        return False
    hex_str = color[1:]
    if len(hex_str) == 3:
        hex_str = ''.join(c*2 for c in hex_str)
    if len(hex_str) < 6:
        return True
    try:
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        return (r + g + b) / 3 < 128
    except ValueError:
        return False


def _extract_background(css: str) -> str:
    """Extract the main background declaration(s) from the pattern CSS.

    Returns the background CSS to be copied verbatim to every slide.
    """
    # Find the .slide or body background
    # Look for the most complex background (likely the main one)
    bg_declarations = []
    for m in re.finditer(r'(?:body|\.slide|html)[^{]*\{([^}]+)\}', css):
        block = m.group(1)
        # Find background properties in this block
        for bm in re.finditer(r'(background[^:]*:\s*[^;]+(?:;|\Z))', block):
            bg = bm.group(1).strip()
            if len(bg) > 20:  # skip trivial "background:#fff"
                bg_declarations.append(bg)

    if not bg_declarations:
        # Fallback: any background declaration
        for m in re.finditer(r'(background\s*:[^;]+;)', css):
            if len(m.group(1)) > 30:
                bg_declarations.append(m.group(1).strip())
                break

    if bg_declarations:
        # Use the longest/most complex one (likely the gradient)
        best = max(bg_declarations, key=len)
        return f"body, .slide {{\n  {best}\n}}"

    return "/* Use background from the reference CSS above */"

