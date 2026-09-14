"""Choose a color-independent material family from observable content needs."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from redeck_style.domain.models import DeckPlan
from redeck_style.style_grammar import resolve_style_archetype
from redeck_style.planning.content_profiler import build_content_profile


FAMILY_FIT = {
    "sans-clean": {"base": 3, "source_figures": 8, "long_titles": 5, "dense_evidence": 2},
    "mono-tech": {"base": 1, "quantitative_evidence": 7, "source_tables": 6, "dense_evidence": 3},
    "mixed-editorial": {"base": 2, "narrative_evidence": 6, "sparse_evidence": 2},
    "serif-classic": {"base": 1, "narrative_evidence": 5, "sparse_evidence": 2},
    "sans-bold": {"base": 1, "sparse_evidence": 5, "long_titles": -3},
    "large-display": {"base": 0, "sparse_evidence": 8, "long_titles": -6, "dense_evidence": -4},
    "small-dense": {"base": -2, "source_tables": 3, "dense_evidence": 2},
}


def summarize_content(profiles):
    content = [profile for profile in profiles if profile.role != "title"] or list(profiles)
    count = max(1, len(content))
    return {
        "base": 1,
        "source_figures": sum(profile.source_kind == "figure" for profile in content) / count,
        "source_tables": sum(profile.source_kind == "table" for profile in content) / count,
        "long_titles": sum(profile.title_length > 68 for profile in content) / count,
        "dense_evidence": sum(profile.density == "high" for profile in content) / count,
        "sparse_evidence": sum(profile.density == "low" and profile.title_length <= 68 for profile in content) / count,
        "quantitative_evidence": sum(
            profile.source_kind == "table" or profile.role in {"results", "comparison", "evaluation"}
            and profile.numeric_count >= 3 for profile in content
        ) / count,
        "narrative_evidence": sum(
            profile.role in {"context", "method", "discussion", "conclusion"} and not profile.source_kind
            for profile in content
        ) / count,
    }


def family_fit(family, summary, requested_archetype=None):
    reasons = {name: round(weight * summary[name], 6)
               for name, weight in FAMILY_FIT.get(family, {}).items() if weight * summary[name]}
    if requested_archetype and resolve_style_archetype(None, "", family) == requested_archetype:
        reasons["requested_archetype_fit"] = 4
    return round(sum(reasons.values()), 6), reasons


def _stable_index(seed, label, length):
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % length


def build_deck_plan(slides, theme, library, seed=42, dialect_id=None, style_archetype=None, profiles=None):
    profiles = profiles if profiles is not None else [build_content_profile(slide) for slide in slides]
    summary = summarize_content(profiles)
    eligible = [dialect_id] if dialect_id else sorted(library.dialects)
    candidates = []
    for candidate_id in eligible:
        library.resolve_dialect(candidate_id)
        families = defaultdict(set)
        typography_ids = {item.id for item in library.query("typography", candidate_id)}
        for item in library.query("background", candidate_id):
            family = item.compatibility.get("typo_family")
            source_id = item.provenance.get("seed_id")
            typography_id = f"typography.{source_id}"
            if family and typography_id in typography_ids and library.compatibility.style_companion(typography_id, item.id):
                families[family].add(source_id)
        for family, members in sorted(families.items()):
            score, reasons = family_fit(family, summary, style_archetype)
            candidates.append({"design_family": candidate_id, "typography_family": family,
                               "score": score, "reasons": reasons, "source_ids": sorted(members)})
    if not candidates:
        raise ValueError("no material family with graph-compatible background/typography bundles")
    best_score = max(candidate["score"] for candidate in candidates)
    best = [candidate for candidate in candidates if candidate["score"] == best_score]
    choice = best[_stable_index(seed, "content-fit-tie", len(best))]
    selected, family, source_ids = choice["design_family"], choice["typography_family"], choice["source_ids"]
    style_archetype = resolve_style_archetype(style_archetype, selected, family)

    return DeckPlan(
        theme_id=theme.id,
        dialect_id=selected,
        style_archetype=style_archetype,
        style_spine={
            "typography_family": family,
            "source_ids": source_ids,
            "policy": "coherent-source-bundle-per-slide",
        },
        slide_order=tuple(slide["slide_id"] for slide in slides),
        rhythm_policy={"avoid_consecutive_macro": True, "vary_focus_every": 2},
        reuse_budget={"layout": 1, "background": 2, "content": 2, "motif": 2},
        seed=seed,
        selection_audit={
            "policy": "content-fit-v1", "content_summary": summary,
            "mode": "legacy-source-group" if selected in library.legacy_source_groups else "explicit" if dialect_id else "content-fit",
            "selected_family": selected, "selected_typography": family,
            "selected_score": choice["score"], "selected_reasons": choice["reasons"],
            "tie_policy": "seed only breaks equal content-fit scores",
            "candidates": [{key: value for key, value in candidate.items() if key != "source_ids"}
                           | {"source_count": len(candidate["source_ids"])}
                           for candidate in sorted(candidates, key=lambda item: (-item["score"], item["design_family"], item["typography_family"]))],
        },
    )
