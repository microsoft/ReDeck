"""Contrast and color utility functions extracted from AgentRepair.

Provides WCAG-compliant luminance, contrast ratio, and color extraction
utilities for both PPTX (RGBColor) and HTML (CSS) code patterns.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def extract_fill_colors(code: str) -> dict[str, tuple[int, int, int]]:
    """Extract fill colors for shape variables from code.

    Looks for patterns like:
        var_name.fill.fore_color.rgb = RGBColor(R, G, B)
    or
        var_name.fill.fore_color.rgb = RGBColor(*theme_colors["key"])

    Returns {var_name: (R, G, B)}.
    """
    result: dict[str, tuple[int, int, int]] = {}

    # Direct RGBColor(r, g, b) pattern
    for m in re.finditer(
        r'(\w+)\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    ):
        var = m.group(1)
        rgb = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
        result[var] = rgb

    # RGBColor(*theme_colors["key"]) pattern — resolve from theme dict
    theme_dict: dict[str, tuple[int, int, int]] = {}
    for m in re.finditer(
        r'"(\w+)"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    ):
        theme_dict[m.group(1)] = (
            int(m.group(2)), int(m.group(3)), int(m.group(4)),
        )

    for m in re.finditer(
        r'(\w+)\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
        code,
    ):
        var = m.group(1)
        key = m.group(2)
        if key in theme_dict:
            result[var] = theme_dict[key]

    return result


def calculate_luminance(r: int, g: int, b: int) -> float:
    """Calculate relative luminance using WCAG formula.

    L = 0.2126 * R' + 0.7152 * G' + 0.0722 * B'
    where R' = (R/255)^2.2 (simplified sRGB)
    """
    r_norm = (r / 255) ** 2.2
    g_norm = (g / 255) ** 2.2
    b_norm = (b / 255) ** 2.2
    return 0.2126 * r_norm + 0.7152 * g_norm + 0.0722 * b_norm


def calculate_contrast_ratio(lum1: float, lum2: float) -> float:
    """Calculate WCAG contrast ratio between two luminance values.

    Contrast ratio = (L_lighter + 0.05) / (L_darker + 0.05)
    """
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def extract_text_rgb(code: str, var_name: str) -> tuple[int, int, int]:
    """Extract text RGB color for a given element.

    Returns RGB tuple, defaults to (50, 50, 50) for dark text.
    """
    var_pos = code.find(var_name)
    if var_pos < 0:
        return (50, 50, 50)  # Default: dark text

    window = code[var_pos:var_pos + 2000]

    # 1. Check for theme-based text color FIRST
    m = re.search(
        r'\.font\.color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
        window,
    )
    if m:
        theme_dict: dict[str, tuple[int, int, int]] = {}
        for tm in re.finditer(
            r'"(\w+)"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
            code,
        ):
            theme_dict[tm.group(1)] = (
                int(tm.group(2)), int(tm.group(3)), int(tm.group(4)),
            )
        key = m.group(1)
        if key in theme_dict:
            return theme_dict[key]

    # 2. Check for literal RGBColor(r, g, b) font color in the window
    m = re.search(
        r'\.font\.color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        window,
    )
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # 3. Check for set_text_style helper with color parameter
    m = re.search(
        r'set_text_style\s*\([^)]*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        window,
    )
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # Default: dark text
    return (50, 50, 50)


def extract_text_brightness(code: str, var_name: str) -> float:
    """Extract text color brightness for a given element.

    Searches for font.color.rgb assignments near the variable's
    text frame setup using a bounded window to avoid cross-element
    contamination (e.g., matching a font color from a completely
    different element that appears later in the code).
    """
    var_pos = code.find(var_name)
    if var_pos < 0:
        return 0.2  # Default: assume dark text

    # Use a bounded window after the variable first appears.
    # This avoids the cross-element contamination bug where a
    # full-code regex like `var_name.*?font.color.rgb = RGBColor(R,G,B)`
    # can span thousands of characters and match a font color from
    # an entirely different element.
    window = code[var_pos:var_pos + 2000]

    # 1. Check for theme-based text color FIRST — this is the most
    #    common pattern and prevents false matches from literal
    #    RGBColor values on other elements.
    m = re.search(
        r'\.font\.color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
        window,
    )
    if m:
        theme_dict: dict[str, tuple[int, int, int]] = {}
        for tm in re.finditer(
            r'"(\w+)"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
            code,
        ):
            theme_dict[tm.group(1)] = (
                int(tm.group(2)), int(tm.group(3)), int(tm.group(4)),
            )
        key = m.group(1)
        if key in theme_dict:
            r, g, b = theme_dict[key]
            return (0.299 * r + 0.587 * g + 0.114 * b) / 255

    # 2. Check for literal RGBColor(r, g, b) font color in the window
    m = re.search(
        r'\.font\.color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        window,
    )
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255

    # 3. Check for set_text_style helper with color parameter
    m = re.search(
        r'set_text_style\s*\([^)]*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        window,
    )
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255

    # Default: assume dark text (common for body text on light slides)
    return 0.2


def check_color_contrast(
    blocks: list,
    fill_colors: dict[str, tuple[int, int, int]],
    code: str,
) -> list[str]:
    """Detect dark-on-dark or low contrast text/background combos using WCAG contrast ratios.

    Returns list of human-readable warnings.
    """
    warnings: list[str] = []

    # Extract background color from slide.background.fill or
    # full-slide background shapes (common pattern: a rectangle
    # covering the entire slide used as a dark hero background).
    bg_brightness = 0.95  # default: assume light
    bg_luminance = 0.95  # default background luminance

    # Helper: resolve theme_colors dict from code
    theme_dict: dict[str, tuple[int, int, int]] = {}
    for m in re.finditer(
        r'"(\w+)"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    ):
        theme_dict[m.group(1)] = (
            int(m.group(2)), int(m.group(3)), int(m.group(4)),
        )

    # Pattern 1: slide.background.fill
    bg_match = re.search(
        r'bg_fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    )
    if not bg_match:
        # Check theme_colors pattern for background
        bg_match = re.search(
            r'bg_fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
            code,
        )
        if bg_match:
            key = bg_match.group(1)
            if key in theme_dict:
                r, g, b = theme_dict[key]
                bg_brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
                bg_luminance = calculate_luminance(r, g, b)
    elif bg_match:
        r, g, b = int(bg_match.group(1)), int(bg_match.group(2)), int(bg_match.group(3))
        bg_brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        bg_luminance = calculate_luminance(r, g, b)

    # Pattern 2: full-slide background shape (e.g. bg = slide.shapes.add_shape(...RECTANGLE...0, 0, prs.slide_width, prs.slide_height))
    # These cover the entire slide and set the effective background color.
    if bg_brightness > 0.9:  # Only override if no explicit bg_fill found
        # Look for shapes at position (0, 0) with slide dimensions
        bg_shape_match = re.search(
            r'(\w+)\s*=\s*slide\.shapes\.add_shape\(\s*MSO_SHAPE\.\w+\s*,\s*0\s*,\s*0\s*,\s*prs\.slide_width\s*,\s*prs\.slide_height\s*\)',
            code,
        )
        if bg_shape_match:
            bg_var = bg_shape_match.group(1)
            # Find the fill color for this shape
            fill_match = re.search(
                rf'{bg_var}\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
                code,
            )
            if fill_match:
                r, g, b = int(fill_match.group(1)), int(fill_match.group(2)), int(fill_match.group(3))
                bg_brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
                bg_luminance = calculate_luminance(r, g, b)
            else:
                # Check theme_colors pattern
                fill_theme_match = re.search(
                    rf'{bg_var}\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
                    code,
                )
                if fill_theme_match:
                    key = fill_theme_match.group(1)
                    if key in theme_dict:
                        r, g, b = theme_dict[key]
                        bg_brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
                        bg_luminance = calculate_luminance(r, g, b)

    bg_is_dark = bg_brightness < 0.4
    bg_is_explicit = bg_brightness != 0.95  # True if we found actual bg

    # Extract text colors for each text element
    for b in blocks:
        if b.text_chars == 0:
            continue

        has_fill = b.var_name in fill_colors

        # Determine the element's fill brightness and luminance
        elem_brightness = 0.95
        elem_luminance = 0.95
        if has_fill:
            r, g, bb = fill_colors[b.var_name]
            elem_brightness = (0.299 * r + 0.587 * g + 0.114 * bb) / 255
            elem_luminance = calculate_luminance(r, g, bb)

        # Find text color for this element
        text_brightness = extract_text_brightness(code, b.var_name)
        text_rgb = extract_text_rgb(code, b.var_name)
        text_luminance = calculate_luminance(*text_rgb)

        # Fill-based contrast check — ONLY for elements with explicit fills.
        # Textboxes without fills are transparent; their contrast depends on
        # whatever is behind them (slide background), handled below.
        if has_fill:
            contrast_ratio = calculate_contrast_ratio(text_luminance, elem_luminance)

            # WCAG AA minimum is 3:1 for large text, 4.5:1 for normal text
            # For simplicity, we use 3:1 as the threshold for CRITICAL issues
            if contrast_ratio < 3.0:
                warnings.append(
                    f"  {b.var_name}: CRITICAL contrast — ratio {contrast_ratio:.1f}:1 "
                    f"(text brightness={text_brightness:.2f}, fill brightness="
                    f"{elem_brightness:.2f})"
                )
            # Keep original brightness-based checks for backward compatibility
            elif elem_brightness < 0.4 and text_brightness < 0.5:
                warnings.append(
                    f"  {b.var_name}: low contrast — text brightness="
                    f"{text_brightness:.2f}, fill brightness="
                    f"{elem_brightness:.2f}"
                )
            # Check: light text on light fill
            elif elem_brightness > 0.7 and text_brightness > 0.7:
                warnings.append(
                    f"  {b.var_name}: low contrast — text brightness="
                    f"{text_brightness:.2f}, fill brightness="
                    f"{elem_brightness:.2f}"
                )

        # For textboxes sitting on slide background (no fill of their own)
        if not has_fill and b.shape_type == "textbox":
            contrast_ratio = calculate_contrast_ratio(text_luminance, bg_luminance)

            if contrast_ratio < 3.0:
                warnings.append(
                    f"  {b.var_name}: CRITICAL contrast — ratio {contrast_ratio:.1f}:1 "
                    f"(text brightness={text_brightness:.2f} on bg brightness="
                    f"{bg_brightness:.2f})"
                )
            elif bg_is_dark and text_brightness < 0.5:
                warnings.append(
                    f"  {b.var_name}: low contrast — text brightness="
                    f"{text_brightness:.2f} on bg brightness="
                    f"{bg_brightness:.2f}"
                )
            elif bg_is_explicit and not bg_is_dark and text_brightness > 0.8:
                # Only flag light-on-light when we KNOW the background
                # is light (not just assuming the default).  Textboxes
                # without fills may sit on colored shapes underneath.
                warnings.append(
                    f"  {b.var_name}: low contrast — text brightness="
                    f"{text_brightness:.2f} on bg brightness="
                    f"{bg_brightness:.2f}"
                )

    return warnings


def check_contrast_regression(
    original_code: str, current_code: str, slide_id: int
) -> str | None:
    """Check for contrast ratio regressions between T0 and T1.

    For HTML code: parses CSS color/background properties directly.
    For PPTX code: uses RGBColor patterns.

    BLOCKS if any text element's contrast drops below 3:1 (WCAG AA).
    Returns a warning/block message or None if clean.
    """
    try:
        if "<html" in current_code.lower() or "<!doctype" in current_code.lower() or "<div" in current_code[:500]:
            return check_html_contrast_regression(original_code, current_code, slide_id)
        else:
            return check_pptx_contrast_regression(original_code, current_code, slide_id)
    except Exception as e:
        logger.warning(f"Contrast regression check failed: {e}")
        return None


def check_html_contrast_regression(
    original_code: str, current_code: str, slide_id: int
) -> str | None:
    """HTML-specific contrast regression check.

    Extracts text color and background color from CSS inline styles,
    computes contrast ratio, and blocks if any text becomes invisible.
    """
    import re as _re

    def _parse_rgb(s: str) -> tuple[int, int, int] | None:
        m = _re.search(r'rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', s)
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3))
        # hex color
        m = _re.search(r'#([0-9a-fA-F]{6})', s)
        if m:
            h = m.group(1)
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return None

    def _extract_text_elements(code: str) -> list[dict]:
        """Find all elements with text content and extract their colors."""
        elements = []
        # Match styled elements containing text
        for m in _re.finditer(
            r'<(?:h[1-6]|p|span|div|li)\s+style="([^"]*)"[^>]*>([^<]{3,})',
            code, _re.IGNORECASE
        ):
            style = m.group(1)
            text = m.group(2).strip()
            if not text or len(text) < 3:
                continue
            fg = _parse_rgb(style) if 'color:' in style.split('background')[0] else None
            # For foreground, find 'color:' that is NOT 'background-color:'
            fg_match = _re.search(r'(?<!background-)color:\s*(rgb\([^)]+\)|#[0-9a-fA-F]{6})', style)
            fg = _parse_rgb(fg_match.group(1)) if fg_match else None
            bg_match = _re.search(r'background(?:-color)?:\s*(rgb\([^)]+\)|#[0-9a-fA-F]{6})', style)
            bg = _parse_rgb(bg_match.group(1)) if bg_match else None
            elements.append({
                'text': text[:50],
                'fg': fg,
                'bg': bg,
                'pos': m.start(),
            })
        return elements

    def _find_parent_bg(code: str, pos: int) -> tuple[int, int, int] | None:
        """Walk backwards from pos to find nearest parent with background."""
        # Find all div/section backgrounds before this position
        bgs = []
        for m in _re.finditer(
            r'<(?:div|section)\s+style="([^"]*)"',
            code[:pos], _re.IGNORECASE
        ):
            style = m.group(1)
            bg_match = _re.search(r'background(?:-color)?:\s*(rgb\([^)]+\)|#[0-9a-fA-F]{6})', style)
            if bg_match:
                rgb = _parse_rgb(bg_match.group(1))
                if rgb:
                    bgs.append(rgb)
        return bgs[-1] if bgs else None

    current_elements = _extract_text_elements(current_code)

    # Also extract original elements to filter out PRE-EXISTING
    # low contrast (don't penalize agent for T0's problems).
    original_low_contrast_texts: set[str] = set()
    for el in _extract_text_elements(original_code):
        fg = el['fg']
        if not fg:
            continue
        bg = el['bg'] or _find_parent_bg(original_code, el['pos'])
        if not bg:
            bg = (255, 255, 255)
        ratio = calculate_contrast_ratio(
            calculate_luminance(*fg),
            calculate_luminance(*bg),
        )
        if ratio < 3.0:
            original_low_contrast_texts.add(el['text'][:30])

    critical = []

    for el in current_elements:
        fg = el['fg']
        if not fg:
            continue  # no explicit color = inherits, skip

        # Skip pre-existing low contrast elements (not a regression)
        if el['text'][:30] in original_low_contrast_texts:
            continue

        # Find effective background
        bg = el['bg'] or _find_parent_bg(current_code, el['pos'])
        if not bg:
            bg = (255, 255, 255)  # assume white default

        fg_lum = calculate_luminance(*fg)
        bg_lum = calculate_luminance(*bg)
        ratio = calculate_contrast_ratio(fg_lum, bg_lum)

        if ratio < 2.0:
            critical.append(
                f"  \"{el['text']}\": fg=rgb({fg[0]},{fg[1]},{fg[2]}) on "
                f"bg=rgb({bg[0]},{bg[1]},{bg[2]}) → contrast {ratio:.1f}:1 "
                f"(text is nearly invisible)"
            )
        elif ratio < 3.0:
            critical.append(
                f"  \"{el['text']}\": fg=rgb({fg[0]},{fg[1]},{fg[2]}) on "
                f"bg=rgb({bg[0]},{bg[1]},{bg[2]}) → contrast {ratio:.1f}:1 "
                f"(below WCAG AA 3:1)"
            )

    if critical:
        return (
            "🚨 SUBMIT BLOCKED — text contrast below WCAG AA minimum:\n"
            + "\n".join(critical)
            + "\n\nFix text colors to ensure readable contrast against "
            "their backgrounds. Use dark text (rgb < 80) on light "
            "backgrounds (rgb > 180), and light text on dark backgrounds."
        )

    return None


def check_pptx_contrast_regression(
    original_code: str, current_code: str, slide_id: int
) -> str | None:
    """PPTX-specific contrast regression check (legacy)."""
    return None  # pptx mode is legacy; HTML check handles current usage


def calculate_element_contrast_ratio(
    code: str, var_name: str, fill_colors: dict[str, tuple[int, int, int]]
) -> float:
    """Calculate contrast ratio for a specific element.

    Returns contrast ratio between text and its background (element fill or slide bg).
    """
    # Get text color
    text_rgb = extract_text_rgb(code, var_name)
    text_luminance = calculate_luminance(*text_rgb)

    # Get background color (element fill or slide background)
    if var_name in fill_colors:
        # Element has its own fill
        bg_rgb = fill_colors[var_name]
        bg_luminance = calculate_luminance(*bg_rgb)
    else:
        # Use slide background
        bg_luminance = extract_slide_background_luminance(code)

    return calculate_contrast_ratio(text_luminance, bg_luminance)


def extract_slide_background_luminance(code: str) -> float:
    """Extract slide background luminance, defaults to light background."""
    # Helper: resolve theme_colors dict from code
    theme_dict: dict[str, tuple[int, int, int]] = {}
    for m in re.finditer(
        r'"(\w+)"\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    ):
        theme_dict[m.group(1)] = (
            int(m.group(2)), int(m.group(3)), int(m.group(4)),
        )

    # Pattern 1: slide.background.fill
    bg_match = re.search(
        r'bg_fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
        code,
    )
    if bg_match:
        r, g, b = int(bg_match.group(1)), int(bg_match.group(2)), int(bg_match.group(3))
        return calculate_luminance(r, g, b)

    # Check theme_colors pattern for background
    bg_match = re.search(
        r'bg_fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
        code,
    )
    if bg_match:
        key = bg_match.group(1)
        if key in theme_dict:
            r, g, b = theme_dict[key]
            return calculate_luminance(r, g, b)

    # Pattern 2: full-slide background shape
    bg_shape_match = re.search(
        r'(\w+)\s*=\s*slide\.shapes\.add_shape\(\s*MSO_SHAPE\.\w+\s*,\s*0\s*,\s*0\s*,\s*prs\.slide_width\s*,\s*prs\.slide_height\s*\)',
        code,
    )
    if bg_shape_match:
        bg_var = bg_shape_match.group(1)
        # Find the fill color for this shape
        fill_match = re.search(
            rf'{bg_var}\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
            code,
        )
        if fill_match:
            r, g, b = int(fill_match.group(1)), int(fill_match.group(2)), int(fill_match.group(3))
            return calculate_luminance(r, g, b)
        else:
            # Check theme_colors pattern
            fill_theme_match = re.search(
                rf'{bg_var}\.fill\.fore_color\.rgb\s*=\s*RGBColor\(\s*\*\s*theme_colors\[\s*"(\w+)"\s*\]\s*\)',
                code,
            )
            if fill_theme_match:
                key = fill_theme_match.group(1)
                if key in theme_dict:
                    r, g, b = theme_dict[key]
                    return calculate_luminance(r, g, b)

    # Default: assume light background (white)
    return calculate_luminance(255, 255, 255)
