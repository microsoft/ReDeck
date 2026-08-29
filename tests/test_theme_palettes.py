from app.themes import (
    ALL_CURATED_THEMES,
    CURATED_THEMES,
    DARK_CURATED_THEMES,
    THEMES,
    THEME_REGISTRY,
    format_theme_colors_for_prompt,
    match_theme_from_html,
    select_theme_for_paper,
)
from app.backends.python_pptx.html_codegen_compiler import HtmlCodeGenCompiler
from app.schemas.blueprint import BlueprintSlide
from app.schemas.evidence import EvidenceState


def test_demo_palette_catalog_has_16_registered_themes():
    assert len(CURATED_THEMES) == 12
    assert len(DARK_CURATED_THEMES) == 4
    assert len(ALL_CURATED_THEMES) == 16
    assert THEMES == ALL_CURATED_THEMES
    assert len(THEME_REGISTRY) == 16
    for theme in ALL_CURATED_THEMES:
        assert THEME_REGISTRY[theme.theme_id] is theme
        assert theme.canvas is not None
        assert theme.ink is not None
        assert theme.secondary is not None
        assert theme.support is not None


def test_explicit_theme_id_and_family_selection():
    assert select_theme_for_paper("anything", "navy_sand").theme_id == "navy_sand"
    assert select_theme_for_paper("anything", "demo_curated_dark") in DARK_CURATED_THEMES
    assert select_theme_for_paper("anything", "demo_curated_all") in ALL_CURATED_THEMES


def test_domain_routing_uses_recommended_theme_pools():
    assert select_theme_for_paper("CVPR 2025 DepthCrafter").theme_id in {
        "ocean_breeze", "sea_glass", "glacier_peach", "editorial_slate",
    }
    assert select_theme_for_paper("BMW industrial operations report").theme_id in {
        "olive_shore", "clay_tide", "deep_reef", "navy_sand",
    }
    assert select_theme_for_paper("q-bio health skull morphology").theme_id in {
        "rose_sand", "mint_coral", "olive_shore",
    }


def test_curated_palette_prompt_has_strict_role_contract():
    prompt = format_theme_colors_for_prompt(CURATED_THEMES[0])

    assert "Role contract" in prompt
    assert "Ink is for all readable text" in prompt
    assert "Accent is small-area emphasis only" in prompt
    assert "Do not swap semantic roles" in prompt
    assert "Ink is not a full-width footer fill" in prompt
    assert "Primary is the only full-width framing color" in prompt
    assert "Never use Secondary, Accent, or Support as a full-width title-band" in prompt


def test_match_theme_from_html_recovers_raw_curated_palette_colors():
    html = """
<style>
  body { background:#f4faf7; color:#2f4744; }
  .header { background:#f4faf7; border-bottom:4px solid #498f86; }
  .bottom-bar { background:#2f4744; color:#ffffff; }
  .accent { color:#ec7d70; }
  .secondary { border-color:#a9d3c3; }
</style>
"""

    assert match_theme_from_html(html).theme_id == "mint_coral"


def test_light_curated_header_gets_quiet_footer_instruction():
    compiler = HtmlCodeGenCompiler(object(), codegen_prompt="slide_html_codegen_anticard")
    compiler._theme = CURATED_THEMES[0]
    slide = BlueprintSlide(
        slide_id=3,
        role="context",
        primary_proposition="Explain the benchmark context",
        narrative_position="body",
    )

    prompt, _ = compiler._build_slide_prompt(
        slide,
        EvidenceState(),
        image_dir=None,
        available_images=[],
        total_slides=10,
    )

    assert "Recommended header style**: light" in prompt
    assert "Required footer treatment" in prompt
    assert "Do NOT use Ink/PRIMARY_DARK as a solid full-width footer fill" in prompt


def test_filled_curated_header_gets_quiet_footer_instruction():
    compiler = HtmlCodeGenCompiler(object(), codegen_prompt="slide_html_codegen_anticard")
    compiler._theme = CURATED_THEMES[0]
    slide = BlueprintSlide(
        slide_id=4,
        role="method",
        primary_proposition="Describe the method",
        narrative_position="body",
    )

    prompt, _ = compiler._build_slide_prompt(
        slide,
        EvidenceState(),
        image_dir=None,
        available_images=[],
        total_slides=10,
    )

    assert "Recommended header style**: primary" in prompt
    assert "Do not repeat the filled header as a second full-width block" in prompt


def test_curated_results_header_keeps_primary_structural_hue():
    compiler = HtmlCodeGenCompiler(object(), codegen_prompt="slide_html_codegen_anticard")
    compiler._theme = CURATED_THEMES[0]
    slide = BlueprintSlide(
        slide_id=5,
        role="results",
        primary_proposition="Present the main result",
        narrative_position="body",
    )

    prompt, _ = compiler._build_slide_prompt(
        slide,
        EvidenceState(),
        image_dir=None,
        available_images=[],
        total_slides=10,
    )

    assert "Recommended header style**: light" in prompt
    assert "border-bottom: 4px solid #d95f68" in prompt.lower()
    assert "Accent-dominant header" not in prompt
