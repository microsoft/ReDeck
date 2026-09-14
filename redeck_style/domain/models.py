"""Canonical runtime data models.

The runtime contract deliberately stops before page geometry.  It tells the
realizer what the page must communicate, which composition forces should be
present, and which executable vocab it may draw from.  The realizer owns the
final scene graph and coordinates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceRelation:
    source: str
    target: str
    kind: str
    evidence_quote: str


@dataclass(frozen=True)
class ContentProfile:
    slide_id: int
    role: str
    evidence_ids: tuple[str, ...]
    item_count: int
    numeric_count: int
    representation_needs: tuple[str, ...]
    density: str
    has_figure: bool = False
    source_kind: str = ""
    source_row_count: int = 0
    source_col_count: int = 0
    design_anchor_id: str = ""
    title_length: int = 0
    evidence_relations: tuple[EvidenceRelation, ...] = ()
    asset_mode: str = "auto"


@dataclass(frozen=True)
class Theme:
    id: str
    palette_name: str
    luminance: str
    tokens: dict[str, str]


@dataclass(frozen=True)
class VocabItem:
    id: str
    kind: str
    program: dict[str, Any]
    interface: dict[str, Any]
    parameters: dict[str, Any]
    compatibility: dict[str, Any]
    provenance: dict[str, Any]
    invariants: tuple[str, ...] = ()


@dataclass(frozen=True)
class DesignDialect:
    id: str
    tags: tuple[str, ...]
    allowed_kinds: tuple[str, ...]
    exclusions: tuple[str, ...]
    rules: dict[str, Any]


@dataclass(frozen=True)
class DeckPlan:
    theme_id: str
    dialect_id: str
    style_archetype: str
    style_spine: dict[str, Any]
    slide_order: tuple[int, ...]
    rhythm_policy: dict[str, Any]
    reuse_budget: dict[str, int]
    seed: int
    selection_audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompositionIntent:
    """Typed visual intent, not a frozen arrangement of rectangles."""

    strategy: str
    focal_role: str
    focal_event: str
    focal_dominance: str
    reading_path: str
    massing: str
    tension: str
    whitespace: str
    required_roles: tuple[str, ...]
    avoid: tuple[str, ...]
    layout_inspiration_id: str
    layout_family: str


@dataclass(frozen=True)
class VocabSelection:
    """One executable design ingredient and how strongly it should bind."""

    vocab_id: str
    kind: str
    mode: str
    purpose: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DesignGuardrails:
    safe_margin_px: int
    min_body_px: int
    min_label_px: int
    max_decoration_systems: int
    evidence_scope: str = "must-cover"
    preserve_figure_aspect_ratio: bool = True


@dataclass(frozen=True)
class SlideDesignProgram:
    """A bounded creative brief and the sole per-slide visual authority.

    Unlike schema 1, this object contains no region coordinates, attachment
    boxes, z-layers, or DOM quotas.  Those details belong to realization.
    """

    schema_version: str
    slide_id: int
    content_profile: ContentProfile
    theme_id: str
    dialect_id: str
    style_archetype: str
    composition: CompositionIntent
    vocab: tuple[VocabSelection, ...]
    guardrails: DesignGuardrails
    provenance: dict[str, Any]
    diagnostics: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    information_density: str = "balanced"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
