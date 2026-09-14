"""Convert evidence into a style-free content profile."""

from __future__ import annotations

import re

from redeck_style.domain.models import ContentProfile, EvidenceRelation


DIRECTED_RELATIONS = frozenset({"precedes", "causes", "transforms-into", "feeds", "depends-on"})
RELATION_KINDS = DIRECTED_RELATIONS | {"compared-with", "combined-with", "qualifies"}


def evidence_relations(slide, evidence_ids):
    """Explicit, quoted content edges; list position and role are never evidence.

    Quotes must occur in the slide's supplied factual content. This checks
    provenance, not entailment: the realizer must still verify the relation.
    """
    text = " ".join(str(value) for value in [slide.get("primary_proposition", ""), *slide.get("must_cover_subset", [])])
    normalized = " ".join(text.split()).casefold()
    valid_ids = set(evidence_ids)
    result = []
    for edge in slide.get("evidence_relations", []):
        if not isinstance(edge, dict):
            raise ValueError("Evidence relation must be an object")
        source, target = edge.get("from"), edge.get("to")
        kind, quote = edge.get("relation"), edge.get("evidence_quote", "")
        if source not in valid_ids or target not in valid_ids or source == target or kind not in RELATION_KINDS:
            raise ValueError("Evidence relation needs distinct existing evidence IDs and a supported kind")
        if not isinstance(quote, str) or len(quote.strip()) < 12 or " ".join(quote.split()).casefold() not in normalized:
            raise ValueError("Evidence relation needs a verbatim quote from supplied slide evidence")
        relation = EvidenceRelation(source, target, kind, quote)
        if relation not in result:
            result.append(relation)
    return tuple(result)


ROLE_NEEDS = {
    "title": ("title-only",),
    "context": ("bullet-text", "diagram-boxes"),
    "method": ("diagram-boxes", "bullet-text"),
    "results": ("bar-chart", "data-table", "big-numbers-KPI"),
    "comparison": ("comparison-columns", "data-table", "bar-chart"),
    "evaluation": ("data-table", "big-numbers-KPI", "bar-chart"),
    "conclusion": ("bullet-text", "big-numbers-KPI"),
    "discussion": ("bullet-text", "comparison-columns", "diagram-boxes"),
}


def build_content_profile(slide, figures=None):
    figures = figures or {}
    role = slide.get("role", "context")
    items = slide.get("must_cover_subset", [])
    evidence_ids = tuple(f"slide-{slide['slide_id']}-evidence-{index}" for index in range(len(items)))
    relations = evidence_relations(slide, evidence_ids)
    text = " ".join([slide.get("primary_proposition", ""), *map(str, items)]).lower()
    numeric_count = len(re.findall(r"(?<![a-z])\d+(?:\.\d+)?%?", text))
    figure_id = slide.get("assigned_figure_id")
    has_figure = bool(figure_id and figure_id in figures)
    source_asset = figures.get(figure_id, {}) if has_figure else {}
    source_row_count = (
        int(source_asset.get("row_count") or len(source_asset.get("rows", [])))
        if source_asset.get("kind") == "table" else 0
    )
    needs = list(ROLE_NEEDS.get(role, ("bullet-text",)))
    if has_figure or any(word in text for word in ("figure", "chart", "curve", "distribution")):
        needs = ["bar-chart", "diagram-boxes", *needs]
    if any(word in text for word in ("table", "benchmark", "compare", "versus")):
        needs = ["data-table", "comparison-columns", *needs]
    if any(edge.kind in DIRECTED_RELATIONS for edge in relations):
        needs = ["process-arrows", "diagram-boxes", *needs]
    if numeric_count >= 3:
        needs = ["big-numbers-KPI", "data-table", *needs]
    needs = tuple(dict.fromkeys(needs))
    content_item_count = max(len(items), source_row_count)
    density = "high" if content_item_count >= 5 or numeric_count >= 4 else "medium" if content_item_count >= 3 else "low"
    return ContentProfile(
        slide_id=slide["slide_id"],
        role=role,
        evidence_ids=evidence_ids,
        item_count=content_item_count,
        numeric_count=numeric_count,
        representation_needs=needs,
        density=density,
        has_figure=has_figure,
        source_kind=source_asset.get("kind", ""),
        source_row_count=source_row_count,
        source_col_count=int(source_asset.get("col_count") or 0),
        design_anchor_id=slide.get("design_anchor_id", ""),
        title_length=len(slide.get("primary_proposition", "")),
        evidence_relations=relations,
    )
