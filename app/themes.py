"""Visual themes for slide generation.

Provides 5 distinct visual themes to ensure diversity across decks.
Each theme defines a complete color palette + font family.
"""

from dataclasses import dataclass


@dataclass
class ThemeColors:
    """Complete color palette for a visual theme."""
    primary_dark: tuple[int, int, int]      # Dark backgrounds, sidebars
    primary_mid: tuple[int, int, int]       # Titles, primary accents
    primary_light: tuple[int, int, int]     # Highlights, links
    accent: tuple[int, int, int]            # Key metrics, emphasis
    accent_alt: tuple[int, int, int]        # Secondary accent (warnings, etc.)
    positive: tuple[int, int, int]          # Positive results, checkmarks
    body_text: tuple[int, int, int]         # Primary body text
    caption_text: tuple[int, int, int]      # Secondary text, captions
    light_bg: tuple[int, int, int]          # Card backgrounds, containers
    warm_bg: tuple[int, int, int]           # Alternate card backgrounds
    font_family: str                        # Primary font
    theme_id: str                           # Unique identifier
    theme_name: str                         # Human-readable name


THEMES: list[ThemeColors] = [
    # Theme 1: Academic Indigo (triadic harmony: indigo + coral + teal)
    ThemeColors(
        primary_dark=(30, 39, 73),
        primary_mid=(55, 71, 133),
        primary_light=(88, 113, 196),
        accent=(200, 60, 50),
        accent_alt=(210, 120, 40),
        positive=(58, 175, 169),
        body_text=(36, 41, 51),
        caption_text=(120, 128, 143),
        light_bg=(242, 244, 248),
        warm_bg=(255, 248, 237),
        font_family="Liberation Sans",
        theme_id="academic_indigo",
        theme_name="Academic Indigo",
    ),
    # Theme 2: Forest Academic (analogous harmony: greens + warm orange accent)
    ThemeColors(
        primary_dark=(27, 94, 32),
        primary_mid=(56, 142, 60),
        primary_light=(129, 199, 132),
        accent=(170, 95, 0),
        accent_alt=(160, 65, 0),
        positive=(46, 125, 50),
        body_text=(33, 33, 33),
        caption_text=(97, 97, 97),
        light_bg=(232, 245, 233),
        warm_bg=(255, 248, 225),
        font_family="Liberation Sans",
        theme_id="forest_academic",
        theme_name="Forest Academic",
    ),
    # Theme 3: Slate Modern (cool neutral + warm orange pop)
    ThemeColors(
        primary_dark=(38, 50, 56),
        primary_mid=(69, 90, 100),
        primary_light=(144, 164, 174),
        accent=(200, 60, 20),
        accent_alt=(190, 40, 30),
        positive=(76, 175, 80),
        body_text=(33, 33, 33),
        caption_text=(117, 117, 117),
        light_bg=(236, 239, 241),
        warm_bg=(255, 243, 224),
        font_family="Liberation Sans",
        theme_id="slate_modern",
        theme_name="Slate Modern",
    ),
    # Theme 4: Royal Elegant (split-complementary: purple-blue + golden accent)
    ThemeColors(
        primary_dark=(74, 20, 140),
        primary_mid=(48, 63, 159),
        primary_light=(149, 117, 205),
        accent=(140, 100, 0),
        accent_alt=(150, 75, 0),
        positive=(102, 187, 106),
        body_text=(38, 50, 56),
        caption_text=(120, 120, 120),
        light_bg=(237, 231, 246),
        warm_bg=(255, 253, 231),
        font_family="Liberation Sans",
        theme_id="royal_elegant",
        theme_name="Royal Elegant",
    ),
    # Theme 5: Warm Earth (warm neutrals + cool teal accent)
    ThemeColors(
        primary_dark=(62, 39, 35),
        primary_mid=(141, 110, 99),
        primary_light=(188, 170, 164),
        accent=(0, 121, 107),
        accent_alt=(0, 96, 85),
        positive=(129, 199, 132),
        body_text=(62, 39, 35),
        caption_text=(117, 117, 117),
        light_bg=(239, 235, 233),
        warm_bg=(232, 245, 233),
        font_family="Liberation Sans",
        theme_id="warm_earth",
        theme_name="Warm Earth",
    ),
]

THEME_REGISTRY: dict[str, ThemeColors] = {t.theme_id: t for t in THEMES}
DEFAULT_THEME = THEMES[0]


def select_theme_for_paper(paper_title: str) -> ThemeColors:
    """Select a theme deterministically based on paper title hash."""
    import hashlib
    digest = hashlib.md5(paper_title.encode()).hexdigest()
    idx = int(digest, 16) % len(THEMES)
    return THEMES[idx]


def format_theme_colors_for_prompt(theme: ThemeColors) -> str:
    """Format a theme's color palette as a prompt section for the codegen LLM."""
    def rgb_str(c: tuple[int, int, int]) -> str:
        return f"({c[0]}, {c[1]}, {c[2]})"

    def hex_str(c: tuple[int, int, int]) -> str:
        return f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"

    return f"""### Color Palette — {theme.theme_name}

Use ONLY these colors. They form a pre-designed color harmony. Follow the 60-30-10 rule: 60% white/light surfaces, 30% primary family, 10% accent.

| Role | RGB | Hex | Usage |
|------|-----|-----|-------|
| Primary Dark | {rgb_str(theme.primary_dark)} | {hex_str(theme.primary_dark)} | Dark backgrounds, hero regions |
| Primary Mid | {rgb_str(theme.primary_mid)} | {hex_str(theme.primary_mid)} | Titles, headings |
| Primary Light | {rgb_str(theme.primary_light)} | {hex_str(theme.primary_light)} | Accent borders, links |
| Accent | {rgb_str(theme.accent)} | {hex_str(theme.accent)} | Key metric, ONE emphasis per slide |
| Accent Alt | {rgb_str(theme.accent_alt)} | {hex_str(theme.accent_alt)} | Secondary accent, chart highlight |
| Positive | {rgb_str(theme.positive)} | {hex_str(theme.positive)} | Positive results, checkmarks |
| Body Text | {rgb_str(theme.body_text)} | {hex_str(theme.body_text)} | Primary body text |
| Caption | {rgb_str(theme.caption_text)} | {hex_str(theme.caption_text)} | Secondary text, captions |
| Light BG | {rgb_str(theme.light_bg)} | {hex_str(theme.light_bg)} | Card backgrounds |
| Warm BG | {rgb_str(theme.warm_bg)} | {hex_str(theme.warm_bg)} | Alternate card backgrounds |"""


def format_theme_typography_for_prompt(theme: ThemeColors) -> str:
    """Format a theme's typography as a prompt section."""
    return f"""### Typography

- Slide title: 30-36pt, bold
- Section header in body: 20-22pt, bold
- Body / bullets: 16-18pt (MINIMUM 14pt — never go below 14pt)
- Captions / footnotes: 14pt (MINIMUM — never go below 14pt anywhere)
- Large metric numbers: 36-48pt, bold
- Font family: {theme.font_family}
- CRITICAL: The absolute minimum font size for ANY text on the slide is 14pt (except chart axis labels at 10-11pt)"""
