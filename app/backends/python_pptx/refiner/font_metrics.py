"""Pillow-based precise text measurement for PPTX spatial analysis."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from PIL import ImageFont

# ── Unit constants ────────────────────────────────────────────────────────────
EMU_PER_INCH: int = 914400
EMU_PER_PT: int = 12700
PX_PER_INCH: int = 96

# Conversion helpers
def _emu_to_pt(emu: float) -> float:
    return emu / EMU_PER_PT

def _pt_to_px(pt: float) -> float:
    return pt * PX_PER_INCH / 72

def _emu_to_px(emu: float) -> float:
    return _pt_to_px(_emu_to_pt(emu))

def _px_to_emu(px: float) -> float:
    return px * EMU_PER_INCH / PX_PER_INCH


# ── Result dataclasses ────────────────────────────────────────────────────────
@dataclass
class TextMeasurement:
    width_px: float
    height_px: float
    width_emu: float
    height_emu: float


@dataclass
class OverflowResult:
    overflows_width: bool
    overflows_height: bool
    overflow_width_emu: float   # positive = amount over; 0 if no overflow
    overflow_height_emu: float
    suggested_font_size_emu: float  # emu; valid when overflow detected


# ── Font resolution table ─────────────────────────────────────────────────────
_FONT_CANDIDATES: dict[str, list[str]] = {
    "microsoft yahei": [
        "/usr/share/fonts/truetype/msyh.ttc",
        "/usr/share/fonts/msyh.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ],
    "arial": [
        "/usr/share/fonts/truetype/arial.ttf",
        "/usr/share/fonts/arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "arial bold": [
        "/usr/share/fonts/truetype/arialbd.ttf",
        "/usr/share/fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    "segoe ui": [
        "/usr/share/fonts/truetype/segoeui.ttf",
        "/usr/share/fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
}

_FALLBACK_FONTS: list[str] = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


class FontMetrics:
    """Measure text dimensions using Pillow TrueType metrics."""

    def __init__(self, extra_font_dirs: Optional[list[str]] = None):
        self._cache: dict[tuple, ImageFont.FreeTypeFont] = {}
        self._extra_font_dirs: list[str] = extra_font_dirs or []
        self._default_font: Optional[ImageFont.FreeTypeFont] = None  # lazy

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_font(self, font_name: str, size_px: float,
                   bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
        key = (font_name.lower(), round(size_px, 2), bold, italic)
        if key in self._cache:
            return self._cache[key]

        font = self._resolve_font(font_name, int(round(size_px)), bold, italic)
        self._cache[key] = font
        return font

    def _resolve_font(self, font_name: str, size_px: int,
                      bold: bool, italic: bool) -> ImageFont.FreeTypeFont:
        lookup = font_name.lower()
        # Bold variant lookup
        if bold and f"{lookup} bold" in _FONT_CANDIDATES:
            lookup = f"{lookup} bold"

        candidates = list(_FONT_CANDIDATES.get(lookup, []))

        # Extra dirs: try <font_name>.ttf / .ttc inside them
        for d in self._extra_font_dirs:
            for ext in ("ttf", "ttc", "otf"):
                candidates.append(os.path.join(d, f"{font_name}.{ext}"))
                candidates.append(os.path.join(d, f"{font_name.lower()}.{ext}"))

        for path in candidates:
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size_px)
                except Exception:
                    continue

        # Fallback
        for path in _FALLBACK_FONTS:
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size_px)
                except Exception:
                    continue

        # Last resort: Pillow default bitmap font (no size scaling)
        return ImageFont.load_default()

    # ── Public API ────────────────────────────────────────────────────────────

    def measure_text(
        self,
        text: str,
        font_name: str,
        size_emu: float,
        bold: bool = False,
        italic: bool = False,
    ) -> TextMeasurement:
        """Return pixel and EMU dimensions of *text* rendered at *size_emu*."""
        if not text:
            return TextMeasurement(0.0, 0.0, 0.0, 0.0)

        size_px = _emu_to_px(size_emu)
        font = self._load_font(font_name, size_px, bold, italic)

        lines = text.split("\n")
        max_w = 0.0
        total_h = 0.0

        for line in lines:
            if line:
                bbox = font.getbbox(line)   # (left, top, right, bottom)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
            else:
                # Empty line: use ascent height for line gap
                ascent, descent = font.getmetrics()
                w = 0
                h = ascent + descent
            max_w = max(max_w, w)
            total_h += h

        return TextMeasurement(
            width_px=max_w,
            height_px=total_h,
            width_emu=_px_to_emu(max_w),
            height_emu=_px_to_emu(total_h),
        )

    def check_overflow(
        self,
        text: str,
        font_name: str,
        size_emu: float,
        bold: bool,
        box_width_emu: float,
        box_height_emu: float,
    ) -> OverflowResult:
        """Check whether *text* overflows *box* and compute a suggested size."""
        m = self.measure_text(text, font_name, size_emu, bold)

        ow = max(0.0, m.width_emu - box_width_emu)
        oh = max(0.0, m.height_emu - box_height_emu)
        overflows_w = ow > 0
        overflows_h = oh > 0

        # Suggest a font size that fits with a 5 % safety margin
        suggested = size_emu
        if overflows_w or overflows_h:
            ratio_w = box_width_emu / m.width_emu if m.width_emu > 0 else 1.0
            ratio_h = box_height_emu / m.height_emu if m.height_emu > 0 else 1.0
            scale = min(ratio_w, ratio_h) * 0.95  # 5 % safety margin
            min_size_emu = 10 * EMU_PER_PT
            suggested = max(size_emu * scale, min_size_emu)

        return OverflowResult(
            overflows_width=overflows_w,
            overflows_height=overflows_h,
            overflow_width_emu=ow,
            overflow_height_emu=oh,
            suggested_font_size_emu=suggested,
        )
