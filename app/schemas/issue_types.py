"""IssueTypeRegistry — single source of truth for all issue type metadata.

Every issue type is defined ONCE here. All other files import derived sets
instead of maintaining their own copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


# ================================================================
# FAMILIES
# ================================================================

class IssueFamily(str, Enum):
    A = "A"            # Narrative
    B = "B_visual"     # Visual / Layout
    C = "C"            # Completeness
    D = "D"            # Correctness
    E = "E"            # Fidelity


# ================================================================
# ISSUE TYPE DEFINITION
# ================================================================

@dataclass(frozen=True)
class IssueTypeDef:
    """Metadata for a single issue type."""

    name: str
    family: IssueFamily
    probe_id: str = ""                  # e.g. "B03", "D01"
    probe_file: str = ""                # e.g. "B03_overlap.md"
    requires_vision: bool = False       # Probe needs PNG images
    requires_spatial: bool = False      # Probe needs spatial_signals from Playwright
    requires_source: bool = False       # Probe needs source evidence chunks
    is_deck_level: bool = False         # Operates on full deck, not per-slide
    is_spatial: bool = False            # Pure layout/style — no text content change
    is_b_series: bool = False           # Visual series — eligible for per-slide capping
    is_deterministic: bool = False      # Detected by geom_checks/Playwright, not LLM
    is_cross_slide: bool = False        # Inherently cross-slide
    is_unsolvable: bool = False         # Cannot be fixed by single-slide repair
    residual_categories: frozenset[str] = frozenset()
    # Significant DOM categories that this issue is expected to clear. Empty
    # means DOM checks are regression guards only and resolution is decided by
    # the issue's own evaluator.


def _b(name: str, **kw) -> IssueTypeDef:
    """Shorthand for B-series visual types (spatial + b_series + requires_vision by default)."""
    kw.setdefault("is_spatial", True)
    kw.setdefault("is_b_series", True)
    kw.setdefault("requires_vision", True)
    return IssueTypeDef(name=name, family=IssueFamily.B, **kw)


# ================================================================
# REGISTRY — every issue type defined once
# ================================================================

ISSUE_TYPE_DEFS: dict[str, IssueTypeDef] = {}


def _reg(*defs: IssueTypeDef) -> None:
    for d in defs:
        ISSUE_TYPE_DEFS[d.name] = d


# --- A: Narrative ---
_reg(
    IssueTypeDef("weak_thesis",           IssueFamily.A,
                 probe_id="A01", probe_file="A01_thesis_clarity.md", is_deck_level=True),
    IssueTypeDef("missing_context",       IssueFamily.A,
                 probe_id="A02", probe_file="A02_opening_context.md", is_deck_level=True),
    IssueTypeDef("poor_flow",             IssueFamily.A, is_cross_slide=True, is_unsolvable=True,
                 probe_id="A03", probe_file="A03_logical_flow.md", is_deck_level=True),
    IssueTypeDef("title_content_mismatch", IssueFamily.A,
                 probe_id="A04", probe_file="A04_title_content_alignment.md"),
    IssueTypeDef("weak_closing",          IssueFamily.A,
                 probe_id="A06", probe_file="A06_closing_closure.md", is_deck_level=True),
    IssueTypeDef("misallocated_detail",   IssueFamily.A,
                 probe_id="A05", probe_file="A05_detail_allocation.md"),
    IssueTypeDef("spelling_error",        IssueFamily.A,
                 probe_id="D06", probe_file="D06_spelling_terminology.md"),  # shared with D
    IssueTypeDef("non_slide_content",     IssueFamily.A, is_deterministic=True),
    IssueTypeDef("placeholder_slide",     IssueFamily.A,
                 probe_id="A07", probe_file="A07_placeholder_slide.md"),
    IssueTypeDef("grammar_error",         IssueFamily.A,
                 probe_id="D06", probe_file="D06_spelling_terminology.md"),  # shared with D06
    IssueTypeDef("language_inconsistency", IssueFamily.A,
                 probe_id="D06", probe_file="D06_spelling_terminology.md"),  # shared with D06
)

# --- B: Visual / Layout ---
_reg(
    _b("visual_inconsistency", is_cross_slide=True, is_unsolvable=True,
       probe_id="B01", probe_file="B01_visual_consistency.md"),
    _b("layout_inappropriate",
       probe_id="B02", probe_file="B02_layout_inappropriate.md"),
    _b("overlap",
       probe_id="B03", probe_file="B03_overlap.md", requires_spatial=True,
       residual_categories=frozenset({"overlap", "occlusion"})),
    _b("text_overflow",
       probe_id="B04", probe_file="B04_text_overflow.md", requires_spatial=True,
       residual_categories=frozenset({
           "text_overflow", "svg_text_overflow", "clipped", "canvas_truncation",
       })),
    _b("low_contrast",
       probe_id="B05", probe_file="B05_low_contrast.md", requires_spatial=True),
    _b("text_visual_imbalance",
       probe_id="B06", probe_file="B06_text_visual_imbalance.md"),
    _b("form_misfit",
       probe_id="B07", probe_file="B07_form_misfit.md"),
    _b("irrelevant_visual",     is_spatial=False,
       probe_id="B08", probe_file="B08_irrelevant_visual.md"),
    _b("density_imbalance",
       probe_id="B09", probe_file="B09_density_imbalance.md"),
    _b("missing_data_visualization", is_spatial=False,
       probe_id="B10", probe_file="B10_missing_data_visualization.md"),
    _b("typography_error",
       probe_id="B11", probe_file="B11_text_clarity.md"),
    _b("formatting_error",
       probe_id="B12", probe_file="B12_formatting_consistency.md"),
    _b("alignment_inconsistency",
       probe_id="B13", probe_file="B13_spatial_coherence.md", requires_spatial=True),
    _b("form_redundancy",
       probe_id="B14", probe_file="B14_form_redundancy.md"),
    _b("container_contract_breach",
       probe_id="B15", probe_file="B15_container_contract.md", requires_spatial=True),
    _b("text_wall",             is_spatial=False,
       probe_id="B16", probe_file="B16_text_wall.md"),
    _b("raw_figure",            is_spatial=False,
       probe_id="B17", probe_file="B17_raw_figure.md"),
    _b("color_semantic_mismatch",
       probe_id="B18", probe_file="B18_color_semantic_mismatch.md"),
    # Deterministic (geom_checks) — no probe file, detected programmatically
    _b("empty_slide",           is_deterministic=True),
    _b("empty_placeholder",     is_deterministic=True),
    _b("out_of_bounds",         is_deterministic=True,
       residual_categories=frozenset({"out_of_bounds"})),
    _b("svg_visual_defect",
       probe_id="B20", probe_file="B20_svg_visual_quality.md", requires_spatial=True,
       residual_categories=frozenset({"svg_text_overflow"})),
    _b("content_anomaly",       is_deterministic=True),
)

# --- C: Completeness ---
_reg(
    IssueTypeDef("missing_section",    IssueFamily.C, is_cross_slide=True, is_unsolvable=True,
                 probe_id="C01", probe_file="C01_required_sections.md",
                 requires_source=True, is_deck_level=True),
    IssueTypeDef("missing_point",      IssueFamily.C,
                 probe_id="C02", probe_file="C02_must_cover_points.md",
                 requires_source=True),
    IssueTypeDef("missing_evidence",   IssueFamily.C,
                 probe_id="C03", probe_file="C03_evidence_included.md",
                 requires_source=True),
    IssueTypeDef("missing_entity",     IssueFamily.C,
                 probe_id="C04", probe_file="C04_entities_present.md",
                 requires_source=True),
    IssueTypeDef("missing_conclusion", IssueFamily.C,
                 probe_id="C05", probe_file="C05_conclusions_present.md",
                 requires_source=True, is_deck_level=True, is_cross_slide=True),
)

# --- D: Correctness ---
_reg(
    IssueTypeDef("incorrect_claim",        IssueFamily.D,
                 probe_id="D01", probe_file="D01_key_claims_correct.md",
                 requires_source=True),
    IssueTypeDef("numeric_error",          IssueFamily.D,
                 probe_id="D02", probe_file="D02_numeric_accuracy.md",
                 requires_source=True),
    IssueTypeDef("entity_error",           IssueFamily.D,
                 probe_id="D03", probe_file="D03_entity_accuracy.md",
                 requires_source=True),
    IssueTypeDef("chart_misinterpretation", IssueFamily.D,
                 probe_id="D04", probe_file="D04_chart_interpretation.md",
                 requires_source=True),
    IssueTypeDef("unsupported_causality",  IssueFamily.D,
                 probe_id="D05", probe_file="D05_causality_check.md",
                 requires_source=True),
    # spelling_error already registered under A; D also accepts it
    # but the primary family is A. We handle this via VALID_ISSUE_TYPES below.
)

# --- E: Fidelity ---
_reg(
    IssueTypeDef("untraceable",             IssueFamily.E,
                 probe_id="E01", probe_file="E01_traceability.md",
                 requires_source=True),
    IssueTypeDef("fabricated",              IssueFamily.E,
                 probe_id="E02", probe_file="E02_no_fabrication.md",
                 requires_source=True),
    IssueTypeDef("unfaithful_compression",  IssueFamily.E,
                 probe_id="E03", probe_file="E03_faithful_compression.md",
                 requires_source=True),
    IssueTypeDef("misleading_omission",     IssueFamily.E,
                 probe_id="E04", probe_file="E04_non_misleading_omission.md",
                 requires_source=True),
)


# ================================================================
# DERIVED SETS — computed once from the registry
# ================================================================

def _types_for_family(fam: IssueFamily) -> set[str]:
    return {d.name for d in ISSUE_TYPE_DEFS.values() if d.family == fam}


# Per-family valid types (used by base_judge for LLM output normalization)
VALID_ISSUE_TYPES: dict[str, set[str]] = {
    "A": _types_for_family(IssueFamily.A),
    "B_visual": _types_for_family(IssueFamily.B),
    "C": _types_for_family(IssueFamily.C),
    "D": _types_for_family(IssueFamily.D) | {"spelling_error"},  # D also accepts spelling
    "E": _types_for_family(IssueFamily.E),
}

# Flat union
ALL_VALID_TYPES: frozenset[str] = frozenset(
    t for s in VALID_ISSUE_TYPES.values() for t in s
)

# B-series: eligible for per-slide capping in post-processing
B_SERIES_TYPES: frozenset[str] = frozenset(
    d.name for d in ISSUE_TYPE_DEFS.values() if d.is_b_series
)

# Spatial: pure layout/style issues — skip D/E rejudge when only these changed
SPATIAL_ISSUE_TYPES: frozenset[str] = frozenset(
    d.name for d in ISSUE_TYPE_DEFS.values() if d.is_spatial or d.is_deterministic
)

# Issue type → family string for routing
ISSUE_TYPE_TO_FAMILY: dict[str, str] = {
    d.name: d.family.value for d in ISSUE_TYPE_DEFS.values()
}

# Deterministic: detected by geom_checks/Playwright, not LLM triage
DETERMINISTIC_TYPES: frozenset[str] = frozenset(
    d.name for d in ISSUE_TYPE_DEFS.values() if d.is_deterministic
)

# Unsolvable by single-slide repair
UNSOLVABLE_TYPES: frozenset[str] = frozenset(
    d.name for d in ISSUE_TYPE_DEFS.values() if d.is_unsolvable
)

# Cross-slide: don't split into per-slide copies
CROSS_SLIDE_TYPES: frozenset[str] = frozenset(
    d.name for d in ISSUE_TYPE_DEFS.values() if d.is_cross_slide
)

# Cross-family dedup pairs: when both types appear on the same slide,
# keep only the higher-severity one.
# NOTE: density_imbalance is NOT deduped with overlap/text_overflow here.
# The visual judge prompt already instructs the VLM not to co-report B09
# with B03/B04. Hard-filtering here was killing legitimate element_undersized
# issues (whitespace asymmetry) that are independent of spatial conflicts.
DEDUP_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"fabricated", "numeric_error"}),
    frozenset({"fabricated", "incorrect_claim"}),
    frozenset({"fabricated", "unsupported_causality"}),
    frozenset({"title_content_mismatch", "text_overflow"}),
})

# ================================================================
# BUSINESS LOGIC GROUPS — repair strategy routing
# ================================================================

# High-value types: slides with only minor non-high-value issues get
# deprioritized after turn 2.
HIGH_VALUE_TYPES: frozenset[str] = frozenset({
    "overlap", "out_of_bounds", "text_overflow",
    "container_contract_breach", "fabricated",
    "incorrect_claim", "numeric_error", "entity_error",
})

# Critical content accuracy types: content correctness issues that
# warrant relaxed spatial regression tolerance during repair.
CRITICAL_CONTENT_TYPES: frozenset[str] = frozenset({
    "fabricated", "incorrect_claim", "numeric_error",
    "entity_error", "unfaithful_compression",
})

# Content accuracy types needing mandatory wording corrections
# (superset of CRITICAL_CONTENT_TYPES — includes completeness issues).
CONTENT_ACCURACY_TYPES: frozenset[str] = frozenset({
    "fabricated", "incorrect_claim", "numeric_error",
    "entity_error", "chart_misinterpretation",
    "unfaithful_compression", "missing_entity",
    "missing_context", "missing_point", "missing_evidence",
    "missing_conclusion", "unsupported_causality", "misleading_omission",
})

# Layout-related types: bulk coordinate edits are rejected for these;
# agent should use reflow_layout instead.
LAYOUT_REPAIR_TYPES: frozenset[str] = frozenset({
    "layout_inappropriate", "density_imbalance",
    "text_visual_imbalance",
})

# Subjective issues that get auto-KEEP after persisting N turns.
AUTO_KEEP_TYPES: frozenset[str] = frozenset({
    "poor_flow", "weak_closing",
})


# ================================================================
# SPATIAL DETECTION THRESHOLDS — single source of truth
# ================================================================

class SlideDimensions:
    """Slide geometry constants — single source of truth.

    Standard 16:9 widescreen. All other files import from here.
    """
    # Inches
    WIDTH_IN: float = 13.333
    HEIGHT_IN: float = 7.5
    USABLE_LEFT_IN: float = 0.50
    USABLE_RIGHT_IN: float = 13.00
    USABLE_TOP_IN: float = 0.25
    USABLE_BOTTOM_IN: float = 7.20

    # EMU (1 inch = 914400 EMU)
    EMU_PER_INCH: int = 914400
    WIDTH_EMU: int = 12192000       # 13.333 * 914400
    HEIGHT_EMU: int = 6858000       # 7.5 * 914400

    # HTML viewport (px)
    VIEWPORT_W: int = 1280
    VIEWPORT_H: int = 720
    DEVICE_SCALE_FACTOR: int = 2

    # Conversion factors
    PX_TO_INCH_X: float = 13.333 / 1280
    PX_TO_INCH_Y: float = 7.5 / 720
    PX_TO_EMU: float = 12192000 / 1280  # 9525 EMU/px


class SpatialThresholds:
    """Unified thresholds for overlap/OOB detection across geom_checks and Playwright."""

    OVERLAP_MIN_PCT: float = 0.10       # <10% overlap not reported
    OVERLAP_MAJOR_PCT: float = 0.25     # ≥25% → MAJOR severity
    OOB_MIN_INCHES: float = 0.1         # <0.1" out-of-bounds not reported
    OVERLAP_TRIVIAL_AREA: float = 0.5   # <0.5 sq in overlap tolerated in redeck

    # geom_checks geometry thresholds
    BG_AREA_RATIO: float = 0.85         # ≥85% of slide area → background shape
    BG_WIDTH_RATIO: float = 0.95        # ≥95% width AND ≥40% area → banner/sidebar
    BG_MIN_AREA_RATIO: float = 0.40     # used with BG_WIDTH_RATIO
    CONTAINMENT_RATIO: float = 0.85     # ≥85% intersection → child contained in parent
    ACCENT_LINE_EMU: int = 137160       # 0.15 inch — max thin dimension for accent line
    TITLE_TOP_ZONE_EMU: int = 1828800   # 2 inches — title/subtitle must be in this zone
    TITLE_WIDE_EMU: int = 5486400       # 6 inches — min width for title/subtitle shape
    TITLE_PHANTOM_OVERLAP_EMU: int = 137160  # max phantom overlap between title/subtitle

    # Evidence / source matching
    KEYWORD_MIN_LEN: int = 3            # min chars for cover-subset keyword
    KEYWORD_MIN_LEN_PROP: int = 4       # min chars for primary_proposition keyword
    MAX_EVIDENCE_CHUNKS: int = 12       # max linked evidence chunks per slide
    CHUNK_MAX_CHARS: int = 2500         # truncation limit per evidence chunk
    SOURCE_BUDGET_CHARS: int = 48000    # total char budget for source bundling
    MIN_CONTENT_LEN: int = 50           # skip evidence chunks shorter than this
    TRIAGE_COVERAGE_WARN: float = 0.5   # warn if triage coverage below 50%
    FUZZY_MATCH_CUTOFF: float = 0.4     # difflib cutoff for issue type normalization


# ================================================================
# PROBE REGISTRY — maps probe_id → IssueTypeDef for probe architecture
# ================================================================

PROBE_REGISTRY: dict[str, IssueTypeDef] = {
    d.probe_id: d for d in ISSUE_TYPE_DEFS.values() if d.probe_id
}

VISION_PROBES: frozenset[str] = frozenset(
    d.probe_id for d in ISSUE_TYPE_DEFS.values()
    if d.probe_id and d.requires_vision
)

SPATIAL_PROBES: frozenset[str] = frozenset(
    d.probe_id for d in ISSUE_TYPE_DEFS.values()
    if d.probe_id and d.requires_spatial
)

SOURCE_PROBES: frozenset[str] = frozenset(
    d.probe_id for d in ISSUE_TYPE_DEFS.values()
    if d.probe_id and d.requires_source
)

DECK_LEVEL_PROBES: frozenset[str] = frozenset(
    d.probe_id for d in ISSUE_TYPE_DEFS.values()
    if d.probe_id and d.is_deck_level
)

# ================================================================
# ATOMIC CHECK REGISTRY — two-layer probe architecture
# ================================================================

_ATOMIC_REGISTRY: dict[str, str] | None = None
_ATOMIC_CHECK_DETAILS: dict[str, dict[str, str]] | None = None


def _load_atomic_checks() -> None:
    """Load atomic parent mappings and check text from the generated registry."""
    global _ATOMIC_REGISTRY, _ATOMIC_CHECK_DETAILS
    if _ATOMIC_REGISTRY is not None and _ATOMIC_CHECK_DETAILS is not None:
        return
    import json as _json
    _path = Path(__file__).parent.parent / "prompts" / "probes" / "probe_registry.json"
    _ATOMIC_REGISTRY = {}
    _ATOMIC_CHECK_DETAILS = {}
    if not _path.exists():
        return
    _data = _json.loads(_path.read_text(encoding="utf-8"))
    for _probe_id, _info in _data.items():
        for _check in _info.get("checks", []):
            _check_id = _check["id"]
            _ATOMIC_REGISTRY[_check_id] = _probe_id
            _ATOMIC_CHECK_DETAILS[_check_id] = {
                "probe_id": _probe_id,
                "text": _check.get("text", ""),
                "source": _check.get("source", ""),
            }


def get_atomic_check_registry() -> dict[str, str]:
    """Map check_id (e.g., 'B03.1') → parent probe_id (e.g., 'B03'). Lazy-loaded."""
    _load_atomic_checks()
    assert _ATOMIC_REGISTRY is not None
    return _ATOMIC_REGISTRY


def get_atomic_check_details() -> dict[str, dict[str, str]]:
    """Return check text and parent probe keyed by atomic check ID."""
    _load_atomic_checks()
    assert _ATOMIC_CHECK_DETAILS is not None
    return _ATOMIC_CHECK_DETAILS

# Mutex probe pairs: on the same slide, only the higher-severity issue survives
MUTEX_PROBE_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"B02", "B09"}),   # layout vs density — pick root cause
    frozenset({"B03", "B09"}),   # overlap is root cause, density follows
    frozenset({"B04", "B09"}),   # overflow is root cause
    frozenset({"B06", "B09"}),   # text-visual balance vs density
    frozenset({"B03", "B15"}),   # overlap subsumes container breach
})
