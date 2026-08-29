"""Deterministic frame-color controls for HTML generated decks.

The LLM is still allowed to vary composition, but full-width deck framing
needs a stable contract. This module normalizes only header/footer frame
colors and leaves body charts, figures, tables, and local highlights alone.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...themes import ThemeColors

RGB = tuple[int, int, int]

_CONTRACT_START = "/* ReDeck frame contract:start */"
_CONTRACT_END = "/* ReDeck frame contract:end */"
_CONTRACT_BLOCK_RE = re.compile(
    re.escape(_CONTRACT_START) + r".*?" + re.escape(_CONTRACT_END),
    re.DOTALL,
)

_HEADER_BLOCK_RE = re.compile(r"(?<![\w-])\.header\s*\{(?P<body>[^}]*)\}", re.IGNORECASE)
_HEADER_INLINE_RE = re.compile(
    r"<[^>]*class=[\"'][^\"']*\bheader\b[^\"']*[\"'][^>]*style=[\"'](?P<body>[^\"']*)[\"']",
    re.IGNORECASE,
)
_BG_RE = re.compile(r"background(?:-color)?\s*:\s*(?P<value>[^;]+)", re.IGNORECASE)
_HEX_RE = re.compile(r"#(?P<hex>[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


@dataclass(frozen=True)
class FrameContractReport:
    """Summary of how a slide was normalized."""

    slide_id: int | None
    changed: bool
    treatment: str


@dataclass(frozen=True)
class _Palette:
    canvas: RGB
    ink: RGB
    primary: RGB
    secondary: RGB
    accent: RGB
    support: RGB


def enforce_html_deck_frame_contract(
    slide_codes: dict[int, str],
    theme: ThemeColors,
) -> dict[int, str]:
    """Normalize frame treatments across a generated HTML deck.

    CONSISTENCY FIX: First pass determines majority treatment across all slides,
    then second pass forces ALL slides to use that same treatment.
    This prevents per-slide classification from producing mixed light/filled headers.
    """
    # First pass: classify each slide's treatment
    palette = _Palette(
        canvas=getattr(theme, "canvas_color", getattr(theme, "light_bg")),
        ink=getattr(theme, "ink_color", getattr(theme, "body_text")),
        primary=getattr(theme, "primary_color", getattr(theme, "primary_dark")),
        secondary=getattr(theme, "secondary_color", getattr(theme, "primary_mid")),
        accent=getattr(theme, "accent", getattr(theme, "accent_color", (200, 200, 200))),
        support=getattr(theme, "support_color", getattr(theme, "light_bg")),
    )

    treatments = {}
    for slide_id, html in slide_codes.items():
        if not html or "header" not in html.lower():
            treatments[slide_id] = "none"
            continue
        cleaned = _CONTRACT_BLOCK_RE.sub("", html)
        header_css = _extract_header_style(cleaned)
        if not header_css:
            treatments[slide_id] = "none"
            continue
        treatments[slide_id] = _classify_header_treatment(header_css, palette)

    # Determine majority treatment (excluding "none")
    from collections import Counter
    active = [t for t in treatments.values() if t != "none"]
    if active:
        majority = Counter(active).most_common(1)[0][0]
    else:
        majority = "filled"

    # Second pass: apply majority treatment to ALL slides
    result = {}
    for slide_id, html in slide_codes.items():
        if treatments[slide_id] == "none":
            result[slide_id] = html
            continue
        cleaned = _CONTRACT_BLOCK_RE.sub("", html)
        override_css = _build_override_css(majority, palette, _footer_selectors(cleaned))
        result[slide_id] = _inject_style_override(cleaned, override_css)
    return result


def enforce_html_slide_frame_contract(
    html: str,
    theme: ThemeColors,
    slide_id: int | None = None,
) -> tuple[str, FrameContractReport]:
    """Apply the header/footer frame contract to one HTML slide.

    Rules:
    - Accent/Secondary/Support are never full-width header/footer fills.
    - Filled content headers use the deck Primary as their structural hue.
    - Takeaway/footer bands are always quiet supporting structure: Canvas or a
      subtle Primary tint with a Primary rule. A filled header is already the
      deck frame's dominant structural block; repeating that fill at the
      bottom inverts slide hierarchy on content-heavy pages.
    - Header title text is one color within the band; local title spans cannot
      introduce a second structural hue.
    """

    if not html or "header" not in html.lower():
        return html, FrameContractReport(slide_id, changed=False, treatment="none")

    cleaned = _CONTRACT_BLOCK_RE.sub("", html)
    header_css = _extract_header_style(cleaned)
    if not header_css:
        return cleaned, FrameContractReport(slide_id, changed=cleaned != html, treatment="none")

    palette = _palette_from_theme(theme)
    treatment = _classify_header_treatment(header_css, palette)
    if treatment == "none":
        return cleaned, FrameContractReport(slide_id, changed=cleaned != html, treatment="none")

    override_css = _build_override_css(treatment, palette, _footer_selectors(cleaned))
    updated = _inject_style_override(cleaned, override_css)
    return updated, FrameContractReport(slide_id, changed=updated != html, treatment=treatment)


def _palette_from_theme(theme: ThemeColors) -> _Palette:
    return _Palette(
        canvas=getattr(theme, "canvas_color", getattr(theme, "light_bg")),
        ink=getattr(theme, "ink_color", getattr(theme, "body_text")),
        primary=getattr(theme, "primary_color", getattr(theme, "primary_dark")),
        secondary=getattr(theme, "secondary_color", getattr(theme, "primary_mid")),
        accent=getattr(theme, "accent"),
        support=getattr(theme, "support_color", getattr(theme, "warm_bg")),
    )


def _extract_header_style(html: str) -> str:
    css_match = _HEADER_BLOCK_RE.search(html)
    if css_match:
        return css_match.group("body")
    inline_match = _HEADER_INLINE_RE.search(html)
    if inline_match:
        return inline_match.group("body")
    return ""


def _classify_header_treatment(style: str, palette: _Palette) -> str:
    bg_values = [m.group("value").strip() for m in _BG_RE.finditer(style)]
    bg = bg_values[-1] if bg_values else ""
    style_lower = style.lower()
    bg_lower = bg.lower()

    if not bg and "border-bottom" in style_lower:
        return "light"
    if not bg:
        return "none"

    if any(token in bg_lower for token in ("accent", "secondary", "support")):
        return "filled"
    if "canvas" in bg_lower or "light_bg" in bg_lower or "#fff" in bg_lower or "white" in bg_lower:
        return "light"
    if "primary" in bg_lower:
        return "filled"
    if "gradient" in bg_lower:
        return "filled"

    colors = [_parse_hex(match.group(0)) for match in _HEX_RE.finditer(bg)]
    colors = [color for color in colors if color is not None]
    if not colors:
        return "none"

    # If any header fill is clearly an accent/secondary/support role, force it
    # back to Primary. The frame is deck structure, not per-slide emphasis.
    for color in colors:
        if (
            _color_distance(color, palette.accent) <= 36
            or _color_distance(color, palette.secondary) <= 36
            or _color_distance(color, palette.support) <= 36
        ):
            return "filled"

    average_luma = sum(_relative_luminance(color) for color in colors) / len(colors)
    if average_luma >= 0.78 or any(_color_distance(color, palette.canvas) <= 42 for color in colors):
        return "light"
    return "filled"


def _footer_selectors(html: str) -> tuple[str, ...]:
    selectors = [
        ".bottom-bar",
        ".takeaway",
        ".takeaway-footer",
        ".takeaway-bar",
        ".footer-bar",
        ".footer-band",
    ]
    if _is_structural_footer_selector(html, ".footer"):
        selectors.append(".footer")
    if _is_structural_footer_selector(html, ".bottom"):
        selectors.append(".bottom")
    if _is_structural_footer_selector(html, "footer"):
        selectors.append("footer")
    return tuple(selectors)


def _is_structural_footer_selector(html: str, selector: str) -> bool:
    if selector == "footer":
        pattern = r"(?<![.\w-])footer\s*\{(?P<body>[^}]*)\}"
    else:
        pattern = rf"(?<![\w-]){re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}"
    match = re.search(pattern, html, flags=re.IGNORECASE)
    if not match:
        return False
    body = re.sub(r"\s+", "", match.group("body").lower())
    has_bottom_position = "bottom:0" in body and "position:" in body
    has_full_width = "left:0" in body and ("right:0" in body or "width:100%" in body or "width:1280px" in body)
    tall_enough = bool(re.search(r"height:(?:[4-9]\d|1\d\d)px", body))
    return has_bottom_position and has_full_width and tall_enough


def _build_override_css(treatment: str, palette: _Palette, footer_selectors: tuple[str, ...]) -> str:
    primary = _hex(palette.primary)
    ink = _hex(palette.ink)

    if treatment == "light":
        footer_tint = 0.08
        header_bg = _hex(palette.canvas)
        header_text = ink
        header_border = f"4px solid {primary}"
    else:
        header_bg = primary
        footer_tint = 0.12
        header_text = _hex(_best_frame_text_color(
            palette.primary,
            palette.ink,
            min_contrast=3.0,
        ))
        header_border = "0"

    footer_bg = _hex(_blend(palette.canvas, palette.primary, footer_tint))
    footer_text = ink
    footer_border = f"4px solid {primary}"

    footer_selector = ",\n".join(footer_selectors)
    footer_child_selector = ",\n".join(f"{selector} *" for selector in footer_selectors)

    return f"""
{_CONTRACT_START}
.header {{
  background: {header_bg} !important;
  color: {header_text} !important;
  border-bottom: {header_border} !important;
}}
.header .title,
.header h1,
.header .slide-num,
.header .slide-no,
.header .num {{
  color: {header_text} !important;
}}
.header .title *,
.header h1 * {{
  color: inherit !important;
}}
{footer_selector} {{
  left: 36px !important;
  right: 36px !important;
  bottom: 4px !important;
  width: auto !important;
  min-height: 44px !important;
  height: clamp(44px, 7.2vh, 56px) !important;
  max-height: 56px !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  padding: 0 32px !important;
  background: {footer_bg} !important;
  color: {footer_text} !important;
  border-top: {footer_border} !important;
  font-size: 13px !important;
  line-height: 1.15 !important;
  font-weight: 500 !important;
  letter-spacing: 0 !important;
  text-align: center !important;
}}
{footer_child_selector} {{
  color: inherit !important;
}}
{_CONTRACT_END}
""".strip()


def _inject_style_override(html: str, css: str) -> str:
    if "</style>" in html.lower():
        return re.sub(r"</style>", f"\n{css}\n</style>", html, count=1, flags=re.IGNORECASE)
    if "</head>" in html.lower():
        return re.sub(
            r"</head>",
            f"<style>\n{css}\n</style>\n</head>",
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    return f"<style>\n{css}\n</style>\n{html}"


def _parse_hex(value: str) -> RGB | None:
    match = _HEX_RE.search(value)
    if not match:
        return None
    raw = match.group("hex")
    if len(raw) == 3:
        raw = "".join(char * 2 for char in raw)
    return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _hex(color: RGB) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def _blend(base: RGB, overlay: RGB, alpha: float) -> RGB:
    return tuple(round(base[i] * (1 - alpha) + overlay[i] * alpha) for i in range(3))  # type: ignore[return-value]


def _color_distance(a: RGB, b: RGB) -> float:
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def _relative_luminance(color: RGB) -> float:
    def channel(value: int) -> float:
        normalized = value / 255
        return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def _contrast_ratio(foreground: RGB, background: RGB) -> float:
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _best_frame_text_color(
    background: RGB,
    ink: RGB,
    *,
    min_contrast: float = 4.5,
) -> RGB:
    candidates: tuple[RGB, ...] = ((255, 255, 255), ink, (0, 0, 0))
    for color in candidates:
        if _contrast_ratio(color, background) >= min_contrast:
            return color
    return max(candidates, key=lambda color: _contrast_ratio(color, background))
