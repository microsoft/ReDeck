"""Tests for FontMetrics Pillow-based text measurement."""
import pytest
from app.backends.python_pptx.refiner.font_metrics import FontMetrics, TextMeasurement, OverflowResult

EMU_PER_PT = 12700
EMU_PER_INCH = 914400

@pytest.fixture
def fm():
    return FontMetrics()


def test_measure_text_returns_measurement(fm):
    result = fm.measure_text("Hello World", "Arial", 18 * EMU_PER_PT)
    assert isinstance(result, TextMeasurement)
    assert result.width_px > 0
    assert result.height_px > 0
    assert result.width_emu > 0
    assert result.height_emu > 0


def test_measure_cjk_text(fm):
    latin = fm.measure_text("Hello", "Arial", 18 * EMU_PER_PT)
    cjk = fm.measure_text("你好世界！", "Microsoft YaHei", 18 * EMU_PER_PT)
    # CJK characters are typically wider per character
    assert cjk.width_px > latin.width_px


def test_bold_wider_than_regular(fm):
    regular = fm.measure_text("Hello World", "Arial", 18 * EMU_PER_PT, bold=False)
    bold = fm.measure_text("Hello World", "Arial", 18 * EMU_PER_PT, bold=True)
    assert bold.width_px >= regular.width_px


def test_check_overflow_no_overflow(fm):
    # Short text in a large box (4 inches wide, 2 inches tall)
    result = fm.check_overflow(
        "Hi", "Arial", 12 * EMU_PER_PT, False,
        4 * EMU_PER_INCH, 2 * EMU_PER_INCH
    )
    assert isinstance(result, OverflowResult)
    assert not result.overflows_width
    assert not result.overflows_height


def test_check_overflow_detects_width_overflow(fm):
    # Long bold text at 36pt in a 1-inch wide box
    long_text = "This is a very long text that should overflow the box width"
    result = fm.check_overflow(
        long_text, "Arial", 36 * EMU_PER_PT, True,
        1 * EMU_PER_INCH, 2 * EMU_PER_INCH
    )
    assert result.overflows_width
    assert result.overflow_width_emu > 0
    assert result.suggested_font_size_emu > 0


def test_font_fallback(fm):
    # Unknown font should not crash
    result = fm.measure_text("Hello", "UnknownFontXYZ", 14 * EMU_PER_PT)
    assert result.width_px > 0
    assert result.height_px > 0


def test_empty_text(fm):
    result = fm.measure_text("", "Arial", 14 * EMU_PER_PT)
    assert result.width_px == 0
    assert result.height_px == 0
    assert result.width_emu == 0
    assert result.height_emu == 0


def test_multiline_height(fm):
    single = fm.measure_text("Line one", "Arial", 14 * EMU_PER_PT)
    three_lines = fm.measure_text("Line one\nLine two\nLine three", "Arial", 14 * EMU_PER_PT)
    assert three_lines.height_px > 2 * single.height_px
