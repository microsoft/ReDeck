"""Visual themes and design contracts for HTML slide generation.

The legacy generator exposed :class:`ThemeColors` directly.  Keep that API
stable, but add semantic palette roles and content-driven layout grammars so
the default HTML path can share the visual language used by the public demo.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re


RGB = tuple[int, int, int]


@dataclass
class ThemeColors:
    """Complete color palette for a visual theme.

    The first thirteen fields are the original public API.  The optional
    semantic roles let newer HTML codegen use demo-style palette names without
    breaking callers that construct a legacy theme.
    """

    primary_dark: RGB
    primary_mid: RGB
    primary_light: RGB
    accent: RGB
    accent_alt: RGB
    positive: RGB
    body_text: RGB
    caption_text: RGB
    light_bg: RGB
    warm_bg: RGB
    font_family: str
    theme_id: str
    theme_name: str
    canvas: RGB | None = None
    ink: RGB | None = None
    secondary: RGB | None = None
    support: RGB | None = None
    style_family: str = "legacy"

    @property
    def canvas_color(self) -> RGB:
        return self.canvas or (255, 255, 255)

    @property
    def ink_color(self) -> RGB:
        return self.ink or self.body_text

    @property
    def primary_color(self) -> RGB:
        return self.primary_mid

    @property
    def secondary_color(self) -> RGB:
        return self.secondary or self.primary_light

    @property
    def support_color(self) -> RGB:
        return self.support or self.light_bg


@dataclass(frozen=True)
class LayoutGrammar:
    """A content-driven composition strategy, not a fixed template.

    The first five fields are kept stable for callers introduced with the
    initial design-contract implementation.  The remaining fields describe
    the visual system with enough specificity for codegen to create an
    authored composition rather than fall back to a title plus generic cards.
    """

    grammar_id: str
    name: str
    composition: str
    primary_evidence: str
    avoid: str
    dominant_object: str = ""
    evidence_structure: str = ""
    visual_devices: str = ""
    spatial_rhythm: str = ""
    depth_strategy: str = ""


@dataclass(frozen=True)
class CompositionVariant:
    """A slide-level macro composition within a layout grammar.

    Layout grammars describe the evidence relationship. Variants describe the
    page rhythm for one slide so a deck does not collapse into the same macro
    layout whenever several slides share a grammar.
    """

    variant_id: str
    name: str
    macro_layout: str
    evidence_flow: str
    harmony_rules: str
    avoid: str


LEGACY_THEMES: list[ThemeColors] = [
    ThemeColors(
        primary_dark=(30, 39, 73), primary_mid=(55, 71, 133),
        primary_light=(88, 113, 196), accent=(200, 60, 50),
        accent_alt=(210, 120, 40), positive=(58, 175, 169),
        body_text=(36, 41, 51), caption_text=(120, 128, 143),
        light_bg=(242, 244, 248), warm_bg=(255, 248, 237),
        font_family="Liberation Sans", theme_id="academic_indigo",
        theme_name="Academic Indigo",
    ),
    ThemeColors(
        primary_dark=(27, 94, 32), primary_mid=(56, 142, 60),
        primary_light=(129, 199, 132), accent=(170, 95, 0),
        accent_alt=(160, 65, 0), positive=(46, 125, 50),
        body_text=(33, 33, 33), caption_text=(97, 97, 97),
        light_bg=(232, 245, 233), warm_bg=(255, 248, 225),
        font_family="Liberation Sans", theme_id="forest_academic",
        theme_name="Forest Academic",
    ),
    ThemeColors(
        primary_dark=(38, 50, 56), primary_mid=(69, 90, 100),
        primary_light=(144, 164, 174), accent=(200, 60, 20),
        accent_alt=(190, 40, 30), positive=(76, 175, 80),
        body_text=(33, 33, 33), caption_text=(117, 117, 117),
        light_bg=(236, 239, 241), warm_bg=(255, 243, 224),
        font_family="Liberation Sans", theme_id="slate_modern",
        theme_name="Slate Modern",
    ),
    ThemeColors(
        primary_dark=(74, 20, 140), primary_mid=(48, 63, 159),
        primary_light=(149, 117, 205), accent=(140, 100, 0),
        accent_alt=(150, 75, 0), positive=(102, 187, 106),
        body_text=(38, 50, 56), caption_text=(120, 120, 120),
        light_bg=(237, 231, 246), warm_bg=(255, 253, 231),
        font_family="Liberation Sans", theme_id="royal_elegant",
        theme_name="Royal Elegant",
    ),
    ThemeColors(
        primary_dark=(62, 39, 35), primary_mid=(141, 110, 99),
        primary_light=(188, 170, 164), accent=(0, 121, 107),
        accent_alt=(0, 96, 85), positive=(129, 199, 132),
        body_text=(62, 39, 35), caption_text=(117, 117, 117),
        light_bg=(239, 235, 233), warm_bg=(232, 245, 233),
        font_family="Liberation Sans", theme_id="warm_earth",
        theme_name="Warm Earth",
    ),
]


def _curated_theme(
    theme_id: str,
    name: str,
    *,
    canvas: RGB,
    ink: RGB,
    primary: RGB,
    secondary: RGB,
    accent: RGB,
    support: RGB,
) -> ThemeColors:
    """Map the demo's semantic six-color palette to the legacy API."""

    return ThemeColors(
        primary_dark=ink,
        primary_mid=primary,
        primary_light=secondary,
        accent=accent,
        accent_alt=support,
        positive=secondary,
        body_text=ink,
        caption_text=ink,
        light_bg=support,
        warm_bg=canvas,
        font_family="Liberation Sans",
        theme_id=theme_id,
        theme_name=name,
        canvas=canvas,
        ink=ink,
        secondary=secondary,
        support=support,
        style_family="demo_curated",
    )


# Role-based palettes copied from ReDeck's demo palette library
# (DEMO_CASE_COLOR_PALETTES.md). The default curated pool keeps light,
# editorial, and corporate palettes. Dark palettes are registered and can be
# requested explicitly, but are not the default for arbitrary source figures.
CURATED_THEMES: list[ThemeColors] = [
    _curated_theme(
        "coral_tide", "Coral Tide",
        canvas=(255, 248, 245), ink=(41, 67, 76), primary=(217, 95, 104),
        secondary=(76, 158, 173), accent=(242, 173, 114), support=(185, 216, 197),
    ),
    _curated_theme(
        "ocean_breeze", "Ocean Breeze",
        canvas=(245, 250, 248), ink=(30, 64, 73), primary=(55, 127, 142),
        secondary=(121, 189, 196), accent=(237, 148, 104), support=(217, 201, 141),
    ),
    _curated_theme(
        "apricot_lagoon", "Apricot Lagoon",
        canvas=(255, 249, 241), ink=(61, 69, 71), primary=(229, 138, 95),
        secondary=(63, 146, 158), accent=(244, 196, 116), support=(184, 214, 197),
    ),
    _curated_theme(
        "sea_glass", "Sea Glass",
        canvas=(244, 250, 250), ink=(36, 67, 74), primary=(47, 127, 136),
        secondary=(118, 191, 194), accent=(232, 132, 118), support=(235, 212, 160),
    ),
    _curated_theme(
        "rose_sand", "Rose Sand",
        canvas=(255, 247, 247), ink=(73, 60, 69), primary=(201, 101, 115),
        secondary=(111, 169, 167), accent=(237, 171, 129), support=(240, 217, 154),
    ),
    _curated_theme(
        "citrus_current", "Citrus Current",
        canvas=(255, 251, 242), ink=(52, 70, 74), primary=(217, 120, 85),
        secondary=(61, 137, 151), accent=(240, 190, 98), support=(169, 207, 188),
    ),
    _curated_theme(
        "glacier_peach", "Glacier Peach",
        canvas=(246, 250, 251), ink=(43, 62, 75), primary=(67, 135, 160),
        secondary=(145, 201, 206), accent=(241, 154, 120), support=(244, 211, 159),
    ),
    _curated_theme(
        "mint_coral", "Mint Coral",
        canvas=(244, 250, 247), ink=(47, 71, 68), primary=(73, 143, 134),
        secondary=(169, 211, 195), accent=(236, 125, 112), support=(243, 193, 128),
    ),
    _curated_theme(
        "lavender_coast", "Lavender Coast",
        canvas=(248, 247, 251), ink=(54, 57, 74), primary=(105, 101, 142),
        secondary=(93, 158, 164), accent=(229, 138, 126), support=(230, 202, 141),
    ),
    _curated_theme(
        "olive_shore", "Olive Shore",
        canvas=(248, 248, 241), ink=(57, 67, 56), primary=(109, 139, 112),
        secondary=(63, 138, 145), accent=(217, 121, 94), support=(230, 198, 124),
    ),
    _curated_theme(
        "clay_tide", "Clay and Tide",
        canvas=(251, 247, 243), ink=(65, 59, 57), primary=(183, 102, 80),
        secondary=(69, 136, 145), accent=(217, 154, 99), support=(199, 211, 176),
    ),
    _curated_theme(
        "editorial_slate", "Editorial Slate",
        canvas=(247, 248, 248), ink=(40, 59, 66), primary=(53, 95, 107),
        secondary=(115, 159, 165), accent=(214, 106, 95), support=(216, 182, 110),
    ),
]


DARK_CURATED_THEMES: list[ThemeColors] = [
    _curated_theme(
        "blue_hour_coast", "Blue Hour Coast",
        canvas=(23, 52, 61), ink=(246, 244, 238), primary=(115, 192, 197),
        secondary=(245, 138, 114), accent=(240, 195, 108), support=(166, 201, 185),
    ),
    _curated_theme(
        "deep_reef", "Deep Reef",
        canvas=(16, 46, 53), ink=(245, 248, 247), primary=(62, 164, 170),
        secondary=(130, 200, 196), accent=(239, 121, 107), support=(232, 183, 101),
    ),
    _curated_theme(
        "night_coral", "Night Coral",
        canvas=(37, 46, 56), ink=(248, 243, 236), primary=(225, 108, 114),
        secondary=(77, 161, 176), accent=(240, 180, 113), support=(168, 205, 187),
    ),
    _curated_theme(
        "navy_sand", "Navy Sand",
        canvas=(28, 51, 71), ink=(250, 247, 240), primary=(76, 156, 179),
        secondary=(215, 123, 105), accent=(231, 192, 118), support=(156, 201, 189),
    ),
]


ALL_CURATED_THEMES: list[ThemeColors] = [*CURATED_THEMES, *DARK_CURATED_THEMES]

# Extended palette for more visual diversity
EXTENDED_THEMES: list[ThemeColors] = [
    _curated_theme("electric_sky", "Electric Sky", canvas=(12,25,48), ink=(245,248,255), primary=(56,132,255), secondary=(34,211,238), accent=(255,159,67), support=(120,160,220)),
    _curated_theme("emerald_dusk", "Emerald Dusk", canvas=(10,32,28), ink=(240,253,244), primary=(16,185,129), secondary=(52,211,153), accent=(245,158,11), support=(110,180,160)),
    _curated_theme("slate_corporate", "Slate Corporate", canvas=(248,250,252), ink=(30,41,59), primary=(51,65,85), secondary=(100,116,139), accent=(37,99,235), support=(203,213,225)),
    _curated_theme("midnight_indigo", "Midnight Indigo", canvas=(15,23,42), ink=(241,245,249), primary=(99,102,241), secondary=(129,140,248), accent=(244,114,182), support=(100,116,180)),
    _curated_theme("steel_modern", "Steel Modern", canvas=(245,247,250), ink=(23,37,52), primary=(44,82,130), secondary=(70,130,180), accent=(230,126,34), support=(189,206,224)),
    _curated_theme("sage_wellness", "Sage Wellness", canvas=(247,251,245), ink=(35,55,45), primary=(76,140,100), secondary=(120,180,140), accent=(210,130,80), support=(200,220,195)),
    _curated_theme("burgundy_premium", "Burgundy Premium", canvas=(28,18,22), ink=(248,240,235), primary=(168,50,72), secondary=(210,120,130), accent=(218,175,95), support=(140,90,100)),
    _curated_theme("ocean_gradient", "Ocean Gradient", canvas=(12,30,52), ink=(235,245,255), primary=(32,150,210), secondary=(50,200,200), accent=(255,180,50), support=(80,130,180)),
    _curated_theme("arctic_data", "Arctic Data", canvas=(240,248,255), ink=(20,40,65), primary=(25,100,180), secondary=(60,145,210), accent=(255,100,80), support=(180,215,240)),
    _curated_theme("coffee_pro", "Coffee Professional", canvas=(250,245,238), ink=(50,38,30), primary=(120,75,45), secondary=(165,120,80), accent=(45,130,130), support=(220,200,175)),
    _curated_theme("marine_science", "Marine Science", canvas=(8,38,45), ink=(230,248,248), primary=(0,170,160), secondary=(80,200,190), accent=(255,165,50), support=(50,100,110)),
]


CURATED_DOMAIN_THEME_IDS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("cvpr", "iclr", "icml", "neurips", "aaai", "acl", "emnlp"),
     ("ocean_breeze", "sea_glass", "glacier_peach", "editorial_slate")),
    (("apple", "ipad", "iphone", "tesla", "consumer"),
     ("coral_tide", "apricot_lagoon", "rose_sand")),
    (("bmw", "industrial", "automotive", "energy", "operations"),
     ("olive_shore", "clay_tide", "editorial_slate")),
    (("oecd", "world bank", "policy", "economic", "economics", "market"),
     ("ocean_breeze", "citrus_current", "editorial_slate")),
    (("jpmorgan", "earnings", "finance", "financial", "corporate"),
     ("clay_tide", "editorial_slate", "olive_shore")),
    (("biology", "health", "medical", "medicine", "clinical", "bio", "sustainability"),
     ("rose_sand", "mint_coral", "olive_shore")),
    (("redeck", "slide repair", "presentation repair", "layout repair"),
     ("sea_glass", "glacier_peach", "ocean_breeze")),
)


# THEMES and THEME_REGISTRY continue to expose every concrete theme ID.
THEMES: list[ThemeColors] = [*ALL_CURATED_THEMES, *EXTENDED_THEMES, *LEGACY_THEMES]
THEME_REGISTRY: dict[str, ThemeColors] = {theme.theme_id: theme for theme in THEMES}
DEFAULT_THEME = CURATED_THEMES[0]
THEME_FAMILIES: dict[str, list[str]] = {}  # compatibility stub


LAYOUT_GRAMMARS: dict[str, LayoutGrammar] = {
    "editorial": LayoutGrammar(
        grammar_id="editorial",
        name="Editorial Statement",
        composition=(
            "Build an asymmetric editorial field, usually a 7/5 or 8/4 split. Use an "
            "oversized, tightly edited thesis on one side and a typographic counterpoint, "
            "real evidence artifact, or compact evidence rail on the other."
        ),
        primary_evidence=(
            "Give the central claim or framing idea the strongest typographic weight, then "
            "ground it with one to three concise evidence fragments."
        ),
        avoid=(
            "Avoid a lonely title plus sentence, generic circular-arrow icons, centered poster "
            "layouts, and large empty lower halves."
        ),
        dominant_object=(
            "A 56-92px thesis/title block paired with one real evidence artifact or a "
            "compact set of directly aligned supporting facts."
        ),
        evidence_structure=(
            "Use a compact bottom or side rail for contributions, scope, authors, or key terms; "
            "facts should share alignment but need not be identical cards."
        ),
        visual_devices=(
            "Typographic scale contrast, one directional rule, and a few directly aligned "
            "evidence markers; use SVG only for an explicit evidence-backed relationship."
        ),
        spatial_rhythm="One broad quiet field, one dense focal cluster, then a short evidence cadence.",
        depth_strategy="Canvas typography plus one tinted evidence surface and one foreground accent.",
    ),
    "structured_cards": LayoutGrammar(
        grammar_id="structured_cards",
        name="Structured Evidence Grid",
        composition=(
            "Use a deliberate grid only for genuinely parallel evidence. Combine two to four "
            "unequal regions around a dominant summary, instead of repeating identical cards."
        ),
        primary_evidence="Make the strongest unit larger; order the remaining units by decision value.",
        avoid="Avoid equal-weight card rows, repeated labels, excessive chrome, and card-per-sentence layouts.",
        dominant_object="One larger lead region spanning roughly half the body or two grid tracks.",
        evidence_structure="Two to four peer modules with shared baselines and visibly different priority.",
        visual_devices="Index markers, compact mini-diagrams, aligned measures, or shared category rails.",
        spatial_rhythm="Dense lead region balanced by smaller modules and a deliberate open edge.",
        depth_strategy="Use borders and light palette tints; reserve a solid fill for the lead region only.",
    ),
    "data_led": LayoutGrammar(
        grammar_id="data_led",
        name="Quantitative Story",
        composition=(
            "Turn the comparison into a visual argument: pair one hero result with a chart, "
            "selective table, or calibrated comparison field occupying 55-70% of the body. "
            "Use direct annotations to explain why the highlighted value matters."
        ),
        primary_evidence="The quantitative relationship and delta are the main object, not a generic table shell.",
        avoid="Avoid plain zebra tables, a row of identical KPI cards, repeated values, and unannotated charts.",
        dominant_object=(
            "A ranked comparison, slope/delta view, bar field, or selectively emphasized table "
            "with the best/changed value visible at first glance."
        ),
        evidence_structure=(
            "Place one or two hero metrics near the dominant visual; keep method/context in a "
            "narrow annotation column or footer rail."
        ),
        visual_devices="Direct labels, delta brackets, baseline markers, row bands, and one explanatory callout.",
        spatial_rhythm="Large analytical field followed by a compact interpretation edge.",
        depth_strategy="Flat canvas, lightly tinted data field, and accent only on the decisive values.",
    ),
    "figure_led": LayoutGrammar(
        grammar_id="figure_led",
        name="Annotated Figure",
        composition=(
            "Reserve 55-72% of the body for the supplied figure at its natural aspect ratio, "
            "but vary the macro composition across the deck. The figure may be a centered "
            "stage, a full-width evidence band, a right-hand proof object, or a compact "
            "sidecar composition depending on the selected composition variant."
        ),
        primary_evidence="The source figure is the dominant evidence and must remain inspectable.",
        avoid=(
            "Avoid repeating the same title + left figure + right rail structure on adjacent "
            "figure slides. Also avoid a bare image plus bullets, covering/stretching the "
            "figure, and unrelated decorative icons."
        ),
        dominant_object="The real source figure, large enough that labels and visual structure remain inspectable.",
        evidence_structure=(
            "Use two to four keyed observations as one annotation system: a side rail, bottom "
            "evidence band, perimeter callouts, or metric edge. Do not combine all of them."
        ),
        visual_devices="Keyed markers, leader lines outside the image, crop-safe frame, bottom bands, and one concise takeaway.",
        spatial_rhythm="One continuous visual field with annotations clustered along one chosen edge, not scattered around it.",
        depth_strategy="Keep the figure unobscured; use a subtle frame and small foreground annotation markers.",
    ),
    "comparative_field": LayoutGrammar(
        grammar_id="comparative_field",
        name="Comparative Field",
        composition=(
            "Construct a matched comparison with a shared axis, baseline, or criteria spine. "
            "Use asymmetry to reveal the preferred, combined, or changed option rather than "
            "placing three disconnected cards side by side."
        ),
        primary_evidence="The differences and relationships between alternatives must be scannable before prose is read.",
        avoid="Avoid isolated equal cards, repeated sentence patterns, and comparisons with no shared visual reference.",
        dominant_object="A shared comparison axis, matrix, continuum, or two-sided field spanning most of the body.",
        evidence_structure="Align each option to the same two to four criteria and surface one differentiating takeaway.",
        visual_devices="Shared rails, connectors, checkmarks/dots, aligned measures, and an emphasized convergence outcome.",
        spatial_rhythm="Repeated evidence beats on a common baseline with one clear focal interruption.",
        depth_strategy="Use canvas-level comparison geometry and one tinted highlight for the preferred synthesis.",
    ),
    "process_system": LayoutGrammar(
        grammar_id="process_system",
        name="Process or System Diagram",
        composition=(
            "Draw the actual stages, components, or transformations as a coherent inline-SVG/HTML "
            "system. Use direction, containment, or feedback only when the evidence implies it."
        ),
        primary_evidence="The topology of the method is the main object; labels and outcomes attach to that topology.",
        avoid="Avoid generic boxes in a straight line, decorative arrows, and prose that duplicates node labels.",
        dominant_object="A large process/system diagram occupying 60-75% of the body.",
        evidence_structure="Attach concise inputs, transformations, outputs, and one outcome annotation to the diagram.",
        visual_devices="Connectors, grouping boundaries, flow lanes, stage indices, and input/output ports.",
        spatial_rhythm="A directional visual journey with alternating node scale and purposeful connector spacing.",
        depth_strategy="Containment boundaries create depth; only the critical stage receives a solid accent fill.",
    ),
    "timeline_roadmap": LayoutGrammar(
        grammar_id="timeline_roadmap",
        name="Timeline or Roadmap",
        composition=(
            "Build a temporal path with variable phase widths that reflect emphasis or duration. "
            "Attach milestones and decisions above/below a shared progression line."
        ),
        primary_evidence="Sequence, phase transitions, and the final outcome form one continuous visual narrative.",
        avoid="Avoid four equal cards, disconnected dates, and a generic arrow between text boxes.",
        dominant_object="A horizontal or stepped roadmap spanning most of the body with three to six phases.",
        evidence_structure="Each phase gets one action and one outcome; milestones sit on the shared path.",
        visual_devices="Progress line, phase bands, milestone nodes, duration cues, and a terminal outcome marker.",
        spatial_rhythm="Alternating annotation heights along one continuous horizontal cadence.",
        depth_strategy="Light phase bands behind a strong progression line; accent reserved for the destination.",
    ),
    "evidence_dashboard": LayoutGrammar(
        grammar_id="evidence_dashboard",
        name="Evidence Dashboard",
        composition=(
            "Compose a dense but editorial evidence board: one dominant metric or chart, a "
            "secondary comparison region, and two to four compact evidence modules. Modules "
            "must share alignment and answer different questions."
        ),
        primary_evidence="A lead metric or finding commands the first glance; supporting modules explain magnitude and cause.",
        avoid="Avoid app chrome, uniform KPI tiles, tiny text, and filling every module with the same visual treatment.",
        dominant_object="One hero metric/chart region taking about 35-50% of the body.",
        evidence_structure="Two to four supporting modules for trend, comparison, context, and takeaway.",
        visual_devices="Micro-bars, ranked rows, inline deltas, compact matrices, and section labels.",
        spatial_rhythm="Dense evidence clusters separated by stable gutters and one clear quiet boundary.",
        depth_strategy="Two surface levels only; use scale, alignment, and color emphasis rather than heavy shadows.",
    ),
}


COMPOSITION_VARIANT_VERSION = "composition_variants.v1"


COMPOSITION_VARIANTS: dict[str, tuple[CompositionVariant, ...]] = {
    "editorial": (
        CompositionVariant(
            variant_id="editorial_thesis_counterpoint",
            name="Thesis With Counterpoint",
            macro_layout=(
                "Use an oversized thesis field on one side and a compact counterpoint on the "
                "opposite side; keep the lower canvas grounded by one aligned evidence rail."
            ),
            evidence_flow="Thesis first, then two or three supporting facts that share one baseline.",
            harmony_rules="Leave one quiet edge; use one tinted surface at most and keep the thesis on the canvas.",
            avoid="Do not center the whole slide or put the main thesis inside a large card.",
        ),
        CompositionVariant(
            variant_id="editorial_lower_band",
            name="Statement Over Evidence Band",
            macro_layout=(
                "Let the title occupy the upper-left field and place a structured evidence band "
                "across the lower third with unequal units."
            ),
            evidence_flow="Framing statement above; scope, authors, or implications below in a horizontal cadence.",
            harmony_rules="The lower band should be visually lighter than the thesis and use shared baselines.",
            avoid="Do not split three short facts into identical floating cards.",
        ),
    ),
    "figure_led": (
        CompositionVariant(
            variant_id="figure_hero_band",
            name="Full-Width Figure Band",
            macro_layout=(
                "Place the real figure as a wide inspectable band spanning most of the safe width, "
                "with a compact header above and one evidence band below or above it."
            ),
            evidence_flow="Title -> figure band -> two or three directly aligned observations.",
            harmony_rules=(
                "No right-side observation rail. Keep the band shallow enough that the figure keeps "
                "its natural aspect ratio and the annotation band does not fight the image. Leave a "
                "clear bottom reserve instead of pushing footers or keys below the canvas."
            ),
            avoid="Do not add a title strip, caption, side rail, and takeaway all at once.",
        ),
        CompositionVariant(
            variant_id="figure_center_stage",
            name="Centered Evidence Stage",
            macro_layout=(
                "Center the figure as the dominant stage, with short perimeter labels or a narrow "
                "interpretation shelf attached to one edge."
            ),
            evidence_flow="Compact thesis, then figure stage, then one small synthesis note.",
            harmony_rules=(
                "Keep annotations close to the relevant figure edge; avoid balancing with a tall sidebar. "
                "The bottom key row must be shallow and fully inside the 40px safe area."
            ),
            avoid="Do not leave a large empty rectangle around a short landscape image.",
        ),
        CompositionVariant(
            variant_id="figure_right_explainer",
            name="Right-Hand Proof Object",
            macro_layout=(
                "Put the figure on the right as the proof object and use the left field for a "
                "short explanation, ordered steps, or one metric plus interpretation."
            ),
            evidence_flow="Claim or mechanism on the left; source figure validates it on the right.",
            harmony_rules="The left field should be text-led and airy; the figure should not shrink below inspectable size.",
            avoid="Do not mirror this into the default left-figure/right-rail pattern.",
        ),
        CompositionVariant(
            variant_id="figure_strip_stack",
            name="Figure Strip With Synthesis Stack",
            macro_layout=(
                "Use a wide gallery or chart as a horizontal strip, then stack the thesis, metric, "
                "and evidence keys above or beside it in unequal blocks."
            ),
            evidence_flow="Synthesis block and key value first; wide visual strip confirms the pattern.",
            harmony_rules=(
                "Use the strip to create rhythm; keep text blocks short and aligned to the strip edges. "
                "Reserve bottom space for footer or omit the footer rather than clipping the strip."
            ),
            avoid="Do not stretch a non-wide image into a strip; fall back to centered stage if aspect ratio resists.",
        ),
        CompositionVariant(
            variant_id="figure_metric_edge",
            name="Metric Edge With Figure Field",
            macro_layout=(
                "Attach one decisive metric or delta to an outside edge of the figure field, with "
                "remaining observations as compact rows under that metric."
            ),
            evidence_flow="Hero value -> figure evidence -> concise interpretation rows.",
            harmony_rules="One metric only; keep the metric edge visually narrower than the figure field.",
            avoid="Do not create a grid of KPI cards or a second chart beside the real figure.",
        ),
        CompositionVariant(
            variant_id="figure_sidecar_left",
            name="Classic Figure Sidecar",
            macro_layout=(
                "Use the conventional large figure plus side observation rail only when it is the "
                "clearest reading path for this evidence."
            ),
            evidence_flow="Figure first; two or three side observations interpret visible regions.",
            harmony_rules="Make the rail shorter than or equal to the figure height and use it sparingly across a deck.",
            avoid="Do not use this if the previous or next figure-led slide also uses a side rail.",
        ),
    ),
    "data_led": (
        CompositionVariant(
            variant_id="data_hero_left",
            name="Hero Value Plus Analytical Field",
            macro_layout="Put one decisive value on the left and a chart/table field on the right or lower field.",
            evidence_flow="Lead value, comparison, then interpretation.",
            harmony_rules="The hero value should interrupt the grid; supporting numbers stay subordinate.",
            avoid="Do not make every number an equal KPI tile.",
        ),
        CompositionVariant(
            variant_id="data_wide_table_signal",
            name="Wide Signal Table",
            macro_layout="Let a redesigned table span most of the body with a narrow interpretation note attached to one edge.",
            evidence_flow="Column/row signal first; takeaway attached to the highlighted cells.",
            harmony_rules="Use row bands, numeric alignment, and a single highlight path rather than decorative panels.",
            avoid="Do not wrap the table in a large card or repeat the highlighted value in multiple places.",
        ),
        CompositionVariant(
            variant_id="data_source_chart_signal",
            name="Source Chart Signal",
            macro_layout=(
                "Use the supplied chart or figure as the analytical evidence field, paired with "
                "one hero value or compact interpretation edge."
            ),
            evidence_flow="Hero relationship first; source chart or figure second; interpretation edge last.",
            harmony_rules=(
                "Do not draw a replacement chart when a source chart image is available and readable. "
                "Use at most two edge facts; compress any remaining context into one short footer line."
            ),
            avoid=(
                "Do not create a table shell unless Available Tables supplies real rows and columns. "
                "Do not stack three or more metric/note blocks beside the source figure."
            ),
        ),
    ),
    "comparative_field": (
        CompositionVariant(
            variant_id="comparison_shared_spine",
            name="Shared Criteria Spine",
            macro_layout="Build a shared spine of criteria with alternatives aligned to the same rows or baseline.",
            evidence_flow="Criteria establish comparability; focused cells reveal the difference.",
            harmony_rules="Keep every option evaluated on the same dimensions; emphasize only the supported winner or synthesis.",
            avoid="Do not use isolated equal cards with repeated prose.",
        ),
        CompositionVariant(
            variant_id="comparison_two_field",
            name="Two-Sided Contrast Field",
            macro_layout="Use two unequal fields around a shared boundary, baseline, or convergence point.",
            evidence_flow="Contrast first, then convergence or trade-off.",
            harmony_rules="The shared boundary must encode a real comparison dimension.",
            avoid="Do not add arrows unless the evidence states a transformation.",
        ),
    ),
    "process_system": (
        CompositionVariant(
            variant_id="process_map_with_outcome",
            name="System Map With Outcome Edge",
            macro_layout="Use a large content-specific topology with one outcome edge or implication shelf.",
            evidence_flow="Inputs and mechanisms lead to one named outcome.",
            harmony_rules="Vary node scale by importance and keep connectors quieter than labels.",
            avoid="Do not make a row of equal boxes with heavy arrows.",
        ),
    ),
    "timeline_roadmap": (
        CompositionVariant(
            variant_id="timeline_phase_field",
            name="Phase Field",
            macro_layout="Use variable phase fields along one progression, with annotations alternating above and below.",
            evidence_flow="Ordered phases, then outcome.",
            harmony_rules="Phase widths may vary by emphasis, but all phases stay on one path.",
            avoid="Do not use generic milestone dots when no dates or durations are supplied.",
        ),
    ),
    "evidence_dashboard": (
        CompositionVariant(
            variant_id="dashboard_asymmetric_board",
            name="Asymmetric Evidence Board",
            macro_layout="Use one dominant metric/chart region plus smaller trend, context, and decision modules.",
            evidence_flow="Magnitude first; cause or context second; decision note last.",
            harmony_rules="Modules answer different questions and vary scale; gutters are more important than boxes.",
            avoid="Do not create a row of uniform KPI cards.",
        ),
    ),
    "structured_cards": (
        CompositionVariant(
            variant_id="structured_lead_plus_peers",
            name="Lead Unit Plus Peers",
            macro_layout="Make the strongest unit larger and align two or three peer units to its edge.",
            evidence_flow="Lead claim first; peer support follows on a common grid.",
            harmony_rules="Use unequal scale and shared baselines instead of repeated card styling.",
            avoid="Do not use three identical cards for concepts with priority or dependency.",
        ),
    ),
}


def _variant_by_id(grammar_id: str, variant_id: str) -> CompositionVariant:
    for variant in COMPOSITION_VARIANTS[grammar_id]:
        if variant.variant_id == variant_id:
            return variant
    raise KeyError(f"Unknown composition variant '{variant_id}' for grammar '{grammar_id}'")


def _cycle_variant(candidates: tuple[CompositionVariant, ...], slide_index: int) -> CompositionVariant:
    if not candidates:
        raise ValueError("At least one composition variant is required")
    return candidates[(max(slide_index, 1) - 1) % len(candidates)]


def select_composition_variant(
    grammar: LayoutGrammar,
    *,
    slide_role: str = "",
    slide_index: int = 1,
    total_slides: int = 10,
    layout_hint: str = "",
    has_images: bool = False,
    has_table: bool = False,
    content_text: str = "",
    image_aspect: float | None = None,
) -> CompositionVariant:
    """Choose a macro composition variant without using paper-specific IDs.

    The selector deliberately uses only general slide signals: grammar, role,
    position, content density, and image orientation. It is deterministic so a
    frozen blueprint can be regenerated while still avoiding one repeated shape.
    """

    del total_slides  # Reserved for future first/middle/final deck pacing.

    grammar_id = grammar.grammar_id
    variants = COMPOSITION_VARIANTS.get(grammar_id) or COMPOSITION_VARIANTS["editorial"]
    role = (slide_role or "").lower()
    hint = (layout_hint or "").lower().replace("_", "-")
    combined = f"{role} {hint} {content_text.lower()}"
    numeric_count = len(re.findall(r"(?<![A-Za-z])(?:[$]?\d[\d,.]*%?)", content_text))

    if grammar_id == "figure_led" and has_images:
        if role == "conclusion" or "quote" in hint or "implication" in combined:
            return _variant_by_id("figure_led", "figure_right_explainer")

        if role in {"context", "overview"}:
            return _variant_by_id("figure_led", "figure_hero_band")

        if numeric_count >= 1 and role in {"results", "evaluation", "comparison"}:
            candidates = (
                _variant_by_id("figure_led", "figure_metric_edge"),
                _variant_by_id("figure_led", "figure_hero_band"),
                _variant_by_id("figure_led", "figure_center_stage"),
                _variant_by_id("figure_led", "figure_strip_stack"),
            )
            return _cycle_variant(candidates, slide_index)

        if "image-hero" in hint:
            candidates = (
                _variant_by_id("figure_led", "figure_hero_band"),
                _variant_by_id("figure_led", "figure_center_stage"),
                _variant_by_id("figure_led", "figure_strip_stack"),
            )
            return _cycle_variant(candidates, slide_index)

        if image_aspect is not None and image_aspect >= 1.75:
            candidates = (
                _variant_by_id("figure_led", "figure_hero_band"),
                _variant_by_id("figure_led", "figure_strip_stack"),
                _variant_by_id("figure_led", "figure_center_stage"),
                _variant_by_id("figure_led", "figure_right_explainer"),
                _variant_by_id("figure_led", "figure_sidecar_left"),
            )
            return _cycle_variant(candidates, slide_index)

        if image_aspect is not None and image_aspect <= 0.85:
            candidates = (
                _variant_by_id("figure_led", "figure_right_explainer"),
                _variant_by_id("figure_led", "figure_center_stage"),
                _variant_by_id("figure_led", "figure_sidecar_left"),
            )
            return _cycle_variant(candidates, slide_index)

        candidates = (
            _variant_by_id("figure_led", "figure_center_stage"),
            _variant_by_id("figure_led", "figure_right_explainer"),
            _variant_by_id("figure_led", "figure_hero_band"),
            _variant_by_id("figure_led", "figure_strip_stack"),
            _variant_by_id("figure_led", "figure_sidecar_left"),
        )
        return _cycle_variant(candidates, slide_index)

    if grammar_id == "data_led":
        if has_table and "table" in hint:
            return _variant_by_id("data_led", "data_wide_table_signal")
        if has_images and not has_table:
            return _variant_by_id("data_led", "data_source_chart_signal")
    if grammar_id == "editorial" and role in {"title", "opening"}:
        return _variant_by_id("editorial", "editorial_thesis_counterpoint")

    return _cycle_variant(variants, slide_index)


def format_composition_variant_contract(variant: CompositionVariant) -> str:
    """Format the selected macro variant for slide-level prompt context."""

    return f"""## Composition Variant — {variant.name} (`{variant.variant_id}`)

This variant is mandatory for this slide's macro layout. It is not a fixed template; adapt exact proportions to the evidence.

- Macro layout: {variant.macro_layout}
- Evidence flow: {variant.evidence_flow}
- Harmony rules: {variant.harmony_rules}
- Avoid: {variant.avoid}"""


def _pick_theme_from_pool(paper_title: str, pool: list[ThemeColors]) -> ThemeColors:
    if not pool:
        raise ValueError("Theme pool must not be empty")
    digest = hashlib.md5(paper_title.encode("utf-8")).hexdigest()
    return pool[int(digest, 16) % len(pool)]


def _domain_curated_pool(paper_title: str) -> list[ThemeColors]:
    normalized = (paper_title or "").lower()
    for keywords, theme_ids in CURATED_DOMAIN_THEME_IDS:
        if any(keyword in normalized for keyword in keywords):
            return [THEME_REGISTRY[theme_id] for theme_id in theme_ids]
    return CURATED_THEMES


def select_theme_for_paper(
    paper_title: str,
    theme_id: str = "demo_curated",
) -> ThemeColors:
    """Resolve an explicit theme or deterministically select from a theme family."""

    if not theme_id or theme_id == "None":
        theme_id = "demo_curated"

    if theme_id in THEME_REGISTRY:
        return THEME_REGISTRY[theme_id]
    if theme_id == "demo_curated":
        pool = _domain_curated_pool(paper_title)
    elif theme_id == "demo_curated_all":
        pool = ALL_CURATED_THEMES
    elif theme_id == "demo_curated_dark":
        pool = DARK_CURATED_THEMES
    elif theme_id == "legacy":
        pool = LEGACY_THEMES
    else:
        choices = ", ".join([
            "demo_curated", "demo_curated_all", "demo_curated_dark", "legacy",
            *sorted(THEME_REGISTRY),
        ])
        raise ValueError(f"Unknown HTML theme '{theme_id}'. Expected one of: {choices}")

    return _pick_theme_from_pool(paper_title, pool)


def match_theme_from_html(html: str) -> ThemeColors | None:
    """Recover a known semantic theme from generated CSS variables."""

    role_values = {
        role.lower(): value.upper()
        for role, value in re.findall(
            r"--(canvas|ink|primary|secondary|accent|support)\s*:\s*(#[0-9a-fA-F]{6})",
            html,
            flags=re.IGNORECASE,
        )
    }
    if len(role_values) < 3:
        return None
    for theme in THEMES:
        expected = {
            "canvas": _hex(theme.canvas_color),
            "ink": _hex(theme.ink_color),
            "primary": _hex(theme.primary_color),
        }
        if all(role_values.get(role) == value for role, value in expected.items()):
            return theme
    return None


def select_layout_grammar(
    slide_role: str,
    *,
    layout_hint: str = "",
    has_images: bool = False,
    has_table: bool = False,
    content_text: str = "",
) -> LayoutGrammar:
    """Choose a layout grammar from content semantics rather than case IDs."""

    role = (slide_role or "").lower()
    hint = (layout_hint or "").lower().replace("_", "-")
    combined = f"{role} {hint} {content_text.lower()}"
    numeric_count = len(re.findall(r"(?<![A-Za-z])(?:[$]?\d[\d,.]*%?)", content_text))
    no_visual_evidence = not has_images and not has_table
    is_talk_agenda = any(token in combined for token in (
        "talk roadmap", "presentation roadmap", "deck roadmap", "outline", "agenda",
    ))
    has_real_temporal_signal = any(token in combined for token in (
        "timeline", "milestone", "phase", "chronolog", "duration", "dated", "year", "month",
    ))

    if role in {"title", "opening", "agenda"}:
        grammar_id = "editorial"
    elif no_visual_evidence and is_talk_agenda and not has_real_temporal_signal:
        grammar_id = "editorial"
    elif no_visual_evidence and "metric-card" in hint and numeric_count < 3:
        grammar_id = "editorial"
    elif has_table or "table" in hint:
        grammar_id = "data_led"
    elif has_images:
        grammar_id = "figure_led"
    elif any(token in combined for token in ("timeline", "roadmap", "milestone", "phase", "chronolog")):
        grammar_id = "timeline_roadmap"
    elif any(token in combined for token in (
        "process", "pipeline", "workflow", "architecture", "component", "system", "stage", "mechanism",
    )):
        grammar_id = "process_system"
    elif any(token in combined for token in (
        "comparison", "compare", "versus", " vs ", "side-by-side", "alternative", "trade-off", "tradeoff",
    )):
        grammar_id = "comparative_field"
    elif any(token in combined for token in ("kpi", "metric-card", "dashboard", "portfolio", "overview")):
        grammar_id = "evidence_dashboard"
    elif numeric_count >= 3 and any(token in combined for token in (
        "result", "evaluation", "benchmark", "ablation", "accuracy", "latency", "cost", "performance",
    )):
        grammar_id = "evidence_dashboard"
    elif any(token in combined for token in (
        "taxonomy", "category", "pillar", "dimension", "contribution", "capability",
    )):
        grammar_id = "structured_cards"
    elif role in {"results", "evaluation"} and 1 <= numeric_count <= 2:
        grammar_id = "evidence_dashboard"
    else:
        grammar_id = "editorial"
    return LAYOUT_GRAMMARS[grammar_id]


def _hex(color: RGB) -> str:
    return f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"


def _relative_luminance(color: RGB) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def contrast_ratio(foreground: RGB, background: RGB) -> float:
    """Return the WCAG contrast ratio for two RGB colors."""

    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _darken_for_text(color: RGB, background: RGB, min_ratio: float = 4.5) -> RGB:
    candidate = color
    for _ in range(24):
        if contrast_ratio(candidate, background) >= min_ratio:
            return candidate
        candidate = tuple(max(0, round(value * 0.9)) for value in candidate)  # type: ignore[assignment]
    return candidate


def format_html_design_contract(theme: ThemeColors, grammar: LayoutGrammar) -> str:
    """Format the palette, layout grammar, and hierarchy as one prompt contract."""

    canvas = theme.canvas_color
    ink = theme.ink_color
    primary = theme.primary_color
    secondary = theme.secondary_color
    accent = theme.accent
    support = theme.support_color
    primary_text = _darken_for_text(primary, canvas)
    secondary_text = _darken_for_text(secondary, canvas)
    accent_text = _darken_for_text(accent, canvas)

    return f"""## Design Contract (MANDATORY)

### Palette — {theme.theme_name}

Define these exact CSS custom properties in `:root` and use the variables throughout the page:

```css
:root {{
  --canvas: {_hex(canvas)};
  --ink: {_hex(ink)};
  --primary: {_hex(primary)};
  --secondary: {_hex(secondary)};
  --accent: {_hex(accent)};
  --support: {_hex(support)};
  --primary-text: {_hex(primary_text)};
  --secondary-text: {_hex(secondary_text)};
  --accent-text: {_hex(accent_text)};
}}
```

- Canvas is the slide background; Ink is the default title/body color.
- Primary is the dominant structural color; Secondary supports comparisons and borders.
- Accent marks the most important facts. Support is a low-emphasis fill.
- Aim for a canvas-led composition with primary/secondary structure and focused accent emphasis.
- `--primary`, `--secondary`, and `--accent` are structural colors. Use their `-text` variants for text on the canvas.
- On tinted or solid fills, use `--ink` unless another text color is verified to meet 4.5:1 contrast against that fill.
- You may derive restrained 8-22% alpha tints from these variables for evidence surfaces. Do not invent unrelated colors, gradients, or muddy mixtures.

### Layout Grammar — {grammar.name} (`{grammar.grammar_id}`)

- Composition: {grammar.composition}
- Primary evidence: {grammar.primary_evidence}
- Dominant object: {grammar.dominant_object}
- Evidence structure: {grammar.evidence_structure}
- Visual devices: {grammar.visual_devices}
- Spatial rhythm: {grammar.spatial_rhythm}
- Depth strategy: {grammar.depth_strategy}
- Avoid: {grammar.avoid}
- This grammar describes relationships and hierarchy, not fixed coordinates. Adapt it to the actual evidence.

### Visual Hierarchy

1. Establish one clear thesis; title and body must behave as one composition, not two stacked templates.
2. Give the dominant object 40-70% of the usable body and make its meaning legible at first glance.
3. Build at least three perceptible hierarchy levels: thesis, primary evidence, and annotation/context.
4. Encode relationships visually with position, scale, grouping, or aligned measures. Use connectors only for explicit paths, dependencies, or transitions.
5. Use asymmetry deliberately. Balance a large focal region with a denser evidence cluster or rail.
6. Add a takeaway only when it interprets evidence rather than repeating the title.
7. Keep supporting context subordinate through smaller type and restrained color, but do not leave accidental empty quadrants.
8. Express each fact once. Do not repeat a heading as the first phrase in its body.

### Type And Geometry

- Title: 34-48px (up to 72px for a short opening thesis); body: 16-22px; labels/captions: 14-16px; hero metric: 48-92px. Only a source footer may use 11-12px.
- Use `{theme.font_family}`, 'Segoe UI', Arial, sans-serif.
- Keep meaningful content inside the 40px safe area and align related edges to the grid.
- Prefer 3-6 meaningful visual regions when the evidence supports density; regions may be canvas-level text, diagrams, rails, table fields, or panels rather than cards.
- Sparse evidence may need only two or three regions. Never split one supported sentence into redundant modules to simulate density.
- Never nest cards, keep corner radii at 8px or below, and do not make every fact a separate container.
- Card interiors must not be mostly empty. Size containers to their content instead of stretching short text to fill the body.
- Use inline SVG only when the evidence explicitly supplies a process, topology, sequence, spatial relationship, or quantitative geometry. Never invent abstract geometry to fill a no-image slide; all SVG labels must fit.
- In editorial grammar, do not place the main thesis inside a large tinted rectangle; use the canvas, type scale, and spatial counterpoint as structure.
- Source figures must remain large enough to inspect and must retain their natural aspect ratio."""


def format_theme_colors_for_prompt(theme: ThemeColors) -> str:
    """Format the legacy color palette for callers outside HTML codegen."""

    def rgb_str(color: RGB) -> str:
        return f"({color[0]}, {color[1]}, {color[2]})"

    return f"""### Color Palette — {theme.theme_name}

| Role | RGB | Hex | Usage |
|------|-----|-----|-------|
| Primary Dark | {rgb_str(theme.primary_dark)} | {_hex(theme.primary_dark)} | Dark backgrounds, hero regions |
| Primary Mid | {rgb_str(theme.primary_mid)} | {_hex(theme.primary_mid)} | Titles, headings |
| Primary Light | {rgb_str(theme.primary_light)} | {_hex(theme.primary_light)} | Accent borders, links |
| Accent | {rgb_str(theme.accent)} | {_hex(theme.accent)} | Key metric, one emphasis per slide |
| Accent Alt | {rgb_str(theme.accent_alt)} | {_hex(theme.accent_alt)} | Secondary accent |
| Positive | {rgb_str(theme.positive)} | {_hex(theme.positive)} | Positive results |
| Body Text | {rgb_str(theme.body_text)} | {_hex(theme.body_text)} | Primary body text |
| Caption | {rgb_str(theme.caption_text)} | {_hex(theme.caption_text)} | Secondary text |
| Light BG | {rgb_str(theme.light_bg)} | {_hex(theme.light_bg)} | Light containers |
| Warm BG | {rgb_str(theme.warm_bg)} | {_hex(theme.warm_bg)} | Alternate light surfaces |"""


def format_theme_typography_for_prompt(theme: ThemeColors) -> str:
    """Format a theme's typography as a prompt section."""

    return f"""### Typography

- Slide title: 34-42px, bold
- Section header in body: 20-24px, bold
- Body / bullets: 18-22px (minimum 16px)
- Captions / footnotes: 14-16px
- Large metric numbers: 48-80px, bold
- Font family: {theme.font_family}"""
