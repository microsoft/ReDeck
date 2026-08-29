"""Design tokens for slide generation."""

from pptx.util import Pt, Inches, Emu
from pptx.dml.color import RGBColor


# Slide dimensions (widescreen 16:9)
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

# Margins
MARGIN_LEFT = Inches(0.5)
MARGIN_RIGHT = Inches(0.5)
MARGIN_TOP = Inches(0.5)
MARGIN_BOTTOM = Inches(0.5)

# Colors
COLOR_PRIMARY = RGBColor(0x1A, 0x47, 0x8A)      # Dark blue
COLOR_SECONDARY = RGBColor(0x2E, 0x86, 0xC1)    # Medium blue
COLOR_ACCENT = RGBColor(0xE7, 0x4C, 0x3C)       # Red accent
COLOR_TEXT_DARK = RGBColor(0x2C, 0x3E, 0x50)     # Dark gray-blue
COLOR_TEXT_LIGHT = RGBColor(0x7F, 0x8C, 0x8D)    # Gray
COLOR_BG_WHITE = RGBColor(0xFF, 0xFF, 0xFF)      # White
COLOR_BG_LIGHT = RGBColor(0xF5, 0xF6, 0xFA)     # Light gray
COLOR_CHART_1 = RGBColor(0x3498, 0xDB, 0x00)[0:3] if False else RGBColor(0x34, 0x98, 0xDB)
COLOR_CHART_2 = RGBColor(0xE7, 0x4C, 0x3C)
COLOR_CHART_3 = RGBColor(0x2E, 0xCC, 0x71)
CHART_COLORS = [COLOR_CHART_1, COLOR_CHART_2, COLOR_CHART_3]

# Typography
FONT_FAMILY = "Liberation Sans"
FONT_FAMILY_MONO = "Consolas"

FONT_SIZE_TITLE = Pt(28)
FONT_SIZE_SUBTITLE = Pt(20)
FONT_SIZE_BODY = Pt(18)
FONT_SIZE_CAPTION = Pt(14)
FONT_SIZE_METRIC = Pt(36)
FONT_SIZE_LABEL = Pt(12)

# Font role to size mapping
FONT_ROLE_SIZES = {
    "title": FONT_SIZE_TITLE,
    "subtitle": FONT_SIZE_SUBTITLE,
    "body": FONT_SIZE_BODY,
    "caption": FONT_SIZE_CAPTION,
    "metric": FONT_SIZE_METRIC,
    "label": FONT_SIZE_LABEL,
}

# Spacing
LINE_SPACING_PT = 1.2  # relative
PARAGRAPH_SPACING_PT = Pt(6)
