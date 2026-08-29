from app.backends.html_codegen.deck_frame_contract import (
    enforce_html_deck_frame_contract,
    enforce_html_slide_frame_contract,
)
from app.themes import THEME_REGISTRY


def _contract_block(html: str) -> str:
    start = html.index("/* ReDeck frame contract:start */")
    end = html.index("/* ReDeck frame contract:end */")
    return html[start:end]


def test_light_header_gets_quiet_footer_pairing_without_text_loss():
    theme = THEME_REGISTRY["coral_tide"]
    html = """
<!DOCTYPE html><html><head><style>
.header { height:78px; background:#fff8f5; border-bottom:4px solid #f2ad72; }
.title { color:#29434c; }
.bottom-bar { height:72px; background:#29434c; color:#ffffff; }
</style></head><body>
<div class="header"><div class="title">Result <span style="color:#f2ad72">detail</span></div></div>
<div class="bottom-bar">Takeaway text remains intact</div>
</body></html>
"""

    normalized, report = enforce_html_slide_frame_contract(html, theme, slide_id=3)
    block = _contract_block(normalized)

    assert report.changed is True
    assert report.treatment == "light"
    assert "background: #fff8f5 !important" in block
    assert "border-bottom: 4px solid #d95f68 !important" in block
    assert "border-top: 4px solid #d95f68 !important" in block
    assert ".header .title *" in block
    assert "color: inherit !important" in block
    assert "Takeaway text remains intact" in normalized


def test_accent_header_is_forced_back_to_primary_frame_color():
    theme = THEME_REGISTRY["coral_tide"]
    html = """
<!DOCTYPE html><html><head><style>
.header { height:78px; background:#f2ad72; color:#29434c; }
.header .title { color:#29434c; }
.bottom-bar { height:72px; background:#29434c; color:#ffffff; }
</style></head><body>
<div class="header"><div class="title">Conclusion</div></div>
<div class="bottom-bar">One consistent structural hue</div>
</body></html>
"""

    normalized, report = enforce_html_slide_frame_contract(html, theme, slide_id=8)
    block = _contract_block(normalized)

    assert report.changed is True
    assert report.treatment == "filled"
    assert block.count("background: #d95f68 !important") == 1
    assert "background: #fae6e4 !important" in block
    assert "color: #29434c !important" in block
    assert "border-bottom: 0 !important" in block
    assert "border-top: 4px solid #d95f68 !important" in block


def test_filled_header_gets_quiet_contrast_safe_footer():
    theme = THEME_REGISTRY["mint_coral"]
    html = """
<!DOCTYPE html><html><head><style>
.header { height:78px; background:#498f86; color:#ffffff; }
.header .title { color:#ffffff; }
.bottom-bar { height:72px; background:#498f86; color:#ffffff; }
</style></head><body>
<div class="header"><div class="title">Results</div></div>
<div class="bottom-bar">Takeaway text remains readable</div>
</body></html>
"""

    normalized, report = enforce_html_slide_frame_contract(html, theme, slide_id=7)
    block = _contract_block(normalized)

    assert report.treatment == "filled"
    assert ".header" in block
    assert "color: #ffffff !important" in block
    assert ".bottom-bar" in block
    assert "background: #dfede9 !important" in block
    assert "border-top: 4px solid #498f86 !important" in block
    assert "color: #2f4744 !important" in block
    assert "height: clamp(44px, 7.2vh, 56px) !important" in block
    assert "font-size: 13px !important" in block
    assert "left: 36px !important" in block
    assert "right: 36px !important" in block


def test_frame_contract_is_idempotent_and_skips_cover_without_header():
    theme = THEME_REGISTRY["coral_tide"]
    title_slide = "<html><head><style>.banner{background:#29434c}</style></head><body>Cover</body></html>"
    assert enforce_html_slide_frame_contract(title_slide, theme, slide_id=1)[0] == title_slide

    body_slide = """
<html><head><style>.header{background:#f2ad72}.bottom-bar{background:#29434c}</style></head>
<body><div class="header">Title</div><div class="bottom-bar">Footer</div></body></html>
"""
    once, _ = enforce_html_slide_frame_contract(body_slide, theme, slide_id=2)
    twice, _ = enforce_html_slide_frame_contract(once, theme, slide_id=2)
    assert twice.count("/* ReDeck frame contract:start */") == 1
    assert enforce_html_deck_frame_contract({1: title_slide, 2: body_slide}, theme)[1] == title_slide


def test_non_structural_source_footer_class_is_not_recolored_as_frame():
    theme = THEME_REGISTRY["coral_tide"]
    html = """
<html><head><style>
.header{background:#fff8f5;border-bottom:4px solid #f2ad72}
.bottom-bar{position:absolute;left:0;right:0;bottom:0;height:60px;background:#29434c}
.footer{position:absolute;right:30px;bottom:72px;font-size:12px;color:#888}
</style></head>
<body><div class="header">Title</div><div class="footer">Source: page 4</div><div class="bottom-bar">Takeaway</div></body></html>
"""

    normalized, _ = enforce_html_slide_frame_contract(html, theme, slide_id=4)
    block = _contract_block(normalized)

    assert ".bottom-bar" in block
    assert ".footer," not in block
    assert ".footer *" not in block
    assert "Source: page 4" in normalized


def test_structural_bottom_class_is_normalized_as_footer_frame():
    theme = THEME_REGISTRY["mint_coral"]
    html = """
<html><head><style>
.header{background:#498f86;color:white}
.bottom{position:absolute;left:0;right:0;bottom:0;height:64px;background:#1f2428;color:#fff}
</style></head>
<body><div class="header">Title</div><div class="bottom">Takeaway</div></body></html>
"""

    normalized, _ = enforce_html_slide_frame_contract(html, theme, slide_id=2)
    block = _contract_block(normalized)

    assert ".bottom" in block
    assert "left: 36px !important" in block
    assert "height: clamp(44px, 7.2vh, 56px) !important" in block
    assert "Takeaway" in normalized
