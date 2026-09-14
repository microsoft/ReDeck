"""Compile content profiles and typed vocab into a bounded creative brief.

The planner chooses visual direction and ingredients.  It intentionally does
not manufacture a page-sized arrangement of rectangles: final composition is
the realizer's responsibility.
"""

from __future__ import annotations

import hashlib
from collections import Counter

from redeck_style.domain.constraints import MIN_BODY_PX, MIN_LABEL_PX, title_size_ceiling
from redeck_style.domain.density import density_policy

from redeck_style.domain.models import (
    CompositionIntent,
    DesignGuardrails,
    SlideDesignProgram,
    VocabSelection,
)


ROLE_MACROS = {
    "title": {"single-center", "asymmetric-hero-left", "asymmetric-hero-right"},
    "context": {"left-sidebar", "left-title-right-body", "top-header-body", "L-shape"},
    "method": {"L-shape", "stacked-strips", "left-title-right-body", "two-column-equal"},
    "results": {"asymmetric-hero-left", "asymmetric-hero-right", "grid-2x2", "top-header-body"},
    "comparison": {"two-column-equal", "three-column", "grid-2x2", "L-shape"},
    "evaluation": {"grid-2x2", "grid-3x2", "L-shape", "top-header-body"},
    "conclusion": {"single-center", "stacked-strips", "asymmetric-hero-left"},
}


COMPOSITION_RECIPES = {
    "title": (
        ("editorial-hero", "title", "focal-point then supporting line", "one dominant type mass with a small counterweight", "asymmetric", "expansive"),
        ("offset-thesis", "title", "edge anchor into title then metadata", "one off-centre title block balanced by negative space", "off-axis", "expansive"),
    ),
    "context": (
        ("narrative-spine", "claim", "claim then supporting evidence", "one strong anchor with an open evidence field", "asymmetric", "moderate"),
        ("contrast-field", "claim", "large claim then contrasting evidence field", "one broad field opposed by a compact anchor", "asymmetric", "moderate"),
    ),
    "method": (
        ("method-landscape", "process", "mechanism then supporting detail", "one coherent system view with subordinate evidence", "asymmetric", "compact"),
        ("mechanism-cutaway", "process", "central mechanism then orbiting evidence", "one mechanism mass with subordinate annotations", "radial", "moderate"),
    ),
    "results": (
        ("evidence-hero", "metric", "headline result to proof to qualifier", "one dominant result opposed by a dense proof field", "asymmetric", "compact"),
        ("ranked-evidence", "comparison", "ranked scan then conclusion", "repeated evidence rhythm with one deliberate break", "rhythmic", "compact"),
    ),
    "comparison": (
        ("comparative-axis", "comparison", "shared axis across alternatives", "parallel evidence groups with one emphasized winner", "balanced", "compact"),
        ("ranked-evidence", "comparison", "ranked scan then conclusion", "repeated evidence rhythm with one deliberate break", "rhythmic", "compact"),
    ),
    "evaluation": (
        (
            "controlled-variable-stage",
            "comparison",
            "fixed conditions to changing variable to measurement scope",
            "a quiet invariant base opposed by one oversized changing-variable event",
            "asymmetric fulcrum",
            "moderate",
        ),
        ("evidence-hero", "metric", "headline result to proof to qualifier", "one dominant result opposed by a dense proof field", "asymmetric", "compact"),
    ),
    "conclusion": (
        ("closing-thesis", "claim", "takeaway to implications", "one dominant thesis with a quiet implication trail", "centered", "expansive"),
        ("takeaway-field", "claim", "primary takeaway then implications", "one headline balanced by a varied open evidence rhythm", "asymmetric", "moderate"),
    ),
    "discussion": (
        ("argument-field", "claim", "claim to tensions to implication", "one central argument with contrasting edge notes", "asymmetric", "moderate"),
    ),
}


class SlideProgramPlanner:
    def __init__(self, library, deck_plan, information_density="balanced"):
        density_policy(information_density, "context")
        self.information_density = information_density
        self.library = library
        self.deck_plan = deck_plan
        self.usage = Counter()
        self.previous_macro = None

    def _jitter(self, slide_id, item_id):
        value = hashlib.sha256(
            f"{self.deck_plan.seed}:{slide_id}:{item_id}".encode()
        ).digest()
        return int.from_bytes(value[:4], "big") / 2**32

    def _pick(
        self, kind, profile, predicate=None, prefer_anchor=False,
        strict_predicate=False, compatible_content=None,
    ):
        candidates = self.library.query(
            kind, self.deck_plan.dialect_id, profile.role, profile.density
        )
        if compatible_content:
            candidates = [item for item in candidates
                          if self.library.compatibility.supports_content(item.id, compatible_content)]
        if prefer_anchor and profile.design_anchor_id:
            anchored = [
                item for item in candidates
                if item.provenance.get("seed_id") == profile.design_anchor_id
                and (not strict_predicate or not predicate or predicate(item))
            ]
            if anchored:
                candidates = anchored
        if predicate:
            filtered = [item for item in candidates if predicate(item)]
            candidates = filtered if strict_predicate else (filtered or candidates)
        if not candidates:
            raise ValueError(f"no {kind} vocab for dialect {self.deck_plan.dialect_id}")
        budget_key = "motif" if kind == "decoration" else kind
        budget = self.deck_plan.reuse_budget.get(budget_key, 2)
        return max(
            candidates,
            key=lambda item: (
                12 if prefer_anchor and profile.design_anchor_id
                and item.provenance.get("seed_id") == profile.design_anchor_id else 0,
                (6 if self.usage[item.id] < budget else -20 * self.usage[item.id])
                + (8 if profile.role in item.compatibility.get("role_affinity", []) else 0)
                + (3 if profile.density in item.compatibility.get("density", []) else 0),
                self._jitter(profile.slide_id, item.id),
            ),
        )

    def _composition(self, profile, layout):
        recipes = COMPOSITION_RECIPES.get(profile.role, COMPOSITION_RECIPES["context"])
        recipe = recipes[int(self._jitter(profile.slide_id, "composition") * len(recipes)) % len(recipes)]
        strategy, focal, reading, massing, tension, whitespace = recipe
        focal_event = {
            "title": "type-mass",
            "context": "evidence-tension",
            "method": "central-decision",
            "results": "result-gap",
            "comparison": "rank-break",
            "evaluation": "changing-variable",
            "conclusion": "closing-thesis",
        }.get(profile.role, "claim-turn")

        if profile.source_kind == "figure" or profile.asset_mode == "preserve":
            strategy = "figure-as-scene"
            focal = "figure"
            reading = "figure first, then anchored callouts, then conclusion"
            massing = "one large uncropped figure integrated with a compact annotation system"
            tension = "figure-led asymmetric"
            whitespace = "moderate"
            focal_event = "source-figure"
        elif profile.source_kind == "table":
            strategy = "data-monument"
            focal = "metric"
            reading = "dominant comparison to highlighted row to supporting evidence"
            massing = "one oversized result or contrast paired with one coherent supporting table field"
            tension = "ranked"
            whitespace = "compact"
            focal_event = "result-gap"

        if density_policy(self.information_density, profile.role)["rich_content"]:
            whitespace = "compact, with readable separation between evidence layers"
            massing = (
                "a substantial evidence field with compact claim and source-grounded annotations; "
                "allocate space to distinct facts, comparisons and qualifications rather than oversized repeated slogans"
            )
            if profile.source_kind == "table" and profile.asset_mode != "preserve":
                focal = "comparison"
                reading = "comparison field to highlighted result to experimental scope"

        if profile.source_kind == "table" and profile.asset_mode in {"table", "chart"}:
            focal = profile.asset_mode
            reading = f"source {profile.asset_mode} to highlighted evidence to qualification"
            massing = f"one readable {profile.asset_mode} evidence field with compact source-grounded annotations"

        required_roles = ["title", "body"]
        if focal not in required_roles:
            required_roles.append(focal)
        if profile.source_kind:
            required_roles.append("figure" if profile.asset_mode == "preserve" else
                                  "chart" if profile.asset_mode == "chart" else profile.source_kind)
        return CompositionIntent(
            strategy=strategy,
            focal_role=focal,
            focal_event=focal_event,
            focal_dominance="unmistakable",
            reading_path=reading,
            massing=massing,
            tension=tension,
            whitespace=whitespace,
            required_roles=tuple(dict.fromkeys(required_roles)),
            avoid=(
                "uniform card grid",
                "dashboard chrome unless the evidence genuinely requires a dashboard",
                "header plus generic two-column default",
                "decoration detached from the main composition",
                "nested frame inside panel inside card",
                "full-canvas graph-paper texture as the main visual idea",
                "literal reconstruction of the inspiration layout",
            ),
            layout_inspiration_id=layout.id,
            layout_family=layout.program.get("macro", "unknown"),
        )

    def _style_source(self, profile):
        source_ids = self.deck_plan.style_spine["source_ids"]
        return max(source_ids, key=lambda source_id: (
            -self.usage[f"background.{source_id}"], self._jitter(profile.slide_id, f"style-source:{source_id}")
        ))

    def _from_style_source(self, kind, profile, source_id, required=True):
        candidates = [
            item for item in self.library.query(
                kind, self.deck_plan.dialect_id, profile.role, profile.density
            )
            if item.provenance.get("seed_id") == source_id
            and (kind == "typography" or self.library.compatibility.style_companion(f"typography.{source_id}", item.id))
        ]
        if kind == "decoration":
            plain = [item for item in candidates if item.id == f"decoration.{source_id}"]
            candidates = plain or [
                item for item in candidates if ".signature-system." in item.id
            ] or candidates
        if candidates:
            return candidates[0]
        if required:
            raise ValueError(f"style source {source_id} has no {kind} vocab")
        return None

    def _content_parameters(self, profile, content_kind):
        policy = density_policy(self.information_density, profile.role)
        parameters = {
            "evidence_ids": list(profile.evidence_ids),
            "content_kind": content_kind,
        }
        if profile.source_kind:
            parameters["source_kind"] = profile.source_kind
            parameters["asset_mode"] = profile.asset_mode
        if profile.source_kind == "figure" or profile.asset_mode == "preserve":
            parameters.update({
                "asset_priority": "primary-evidence",
                "asset_fit": "contain",
                "suggested_canvas_share": "35-60%",
            })
        elif profile.source_kind == "table":
            dense_source = profile.source_row_count > 8
            parameters.update({
                "row_count": profile.source_row_count,
                "column_count": profile.source_col_count,
                "table_mode": (
                    "claim-aligned-excerpt" if dense_source or policy["rich_content"]
                    else "one coherent evidence field"
                ),
                "max_display_rows": policy["table_row_limit"] if dense_source else profile.source_row_count,
                "include_context_rows": policy["rich_content"],
                "omitted_rows_policy": "omit or summarize as a count; never fabricate aggregates",
                "highlight_policy": "emphasize only evidence named in the claim",
            })
        elif content_kind == "big-numbers-KPI":
            parameters["suggested_repeat_count"] = max(2, min(4, profile.numeric_count))
        return parameters

    def plan(self, profile):
        style_source = self._style_source(profile)
        background = self._from_style_source("background", profile, style_source)
        typography = self._from_style_source("typography", profile, style_source)
        preferred_content_kind = (
            "title-only" if profile.role == "title" else
            "diagram-boxes" if profile.asset_mode == "preserve" else
            "data-table" if profile.source_kind == "table" else
            "diagram-boxes" if profile.source_kind == "figure" else None
        )
        content = self._pick(
            "content", profile,
            lambda item: item.compatibility.get("content_kind") == preferred_content_kind
            if preferred_content_kind else
            item.compatibility.get("content_kind") in profile.representation_needs,
            prefer_anchor=True,
            strict_predicate=bool(preferred_content_kind),
        )
        macro_set = ROLE_MACROS.get(profile.role, set())
        layout = self._pick(
            "layout", profile,
            lambda item: item.program.get("macro") in macro_set
            and item.program.get("macro") != self.previous_macro,
            prefer_anchor=True, compatible_content=content.id,
        )

        selected = [
            VocabSelection(
                background.id, "background", "adapt",
                "Establish the canvas field; preserve its technique, not its exact geometry.",
            ),
            VocabSelection(
                typography.id, "typography", "adapt",
                "Use its typographic gesture and hierarchy while fitting the actual title.",
                {
                    "title_max_lines": 3 if profile.title_length > 80 else 2,
                    "title_size_ceiling_px": title_size_ceiling(profile.role, profile.title_length),
                    "allow_wrapping": True,
                },
            ),
            VocabSelection(
                content.id, "content", "adapt",
                "Use as an executable content grammar, freely recomposed around the evidence. "
                "Do not inherit generic card shells or place a primary figure inside nested frames.",
                self._content_parameters(profile, content.compatibility.get("content_kind")),
            ),
        ]

        separator = self._from_style_source("separator", profile, style_source, required=False)
        if separator and profile.role != "title":
            selected.append(VocabSelection(
                separator.id, "separator", "optional",
                "Use only if it strengthens the reading path or joins two visual masses.",
            ))
        motif = self._from_style_source("decoration", profile, style_source, required=False)
        if motif and profile.density != "high":
            selected.append(VocabSelection(
                motif.id, "decoration", "optional",
                "Integrate once into the composition as a counterweight or depth cue; omit if ornamental.",
                {"opacity": "subordinate", "placement": "chosen from actual negative space"},
            ))

        source_ids = {layout.provenance.get("seed_id")}
        for selection in selected:
            item = self.library.items[selection.vocab_id]
            source_ids.add(item.provenance.get("seed_id"))
            self.usage[item.id] += 1
        self.usage[layout.id] += 1
        self.previous_macro = layout.program.get("macro", "unknown")

        return SlideDesignProgram(
            schema_version="2.0.0",
            slide_id=profile.slide_id,
            content_profile=profile,
            theme_id=self.deck_plan.theme_id,
            dialect_id=self.deck_plan.dialect_id,
            style_archetype=self.deck_plan.style_archetype,
            information_density=self.information_density,
            composition=self._composition(profile, layout),
            vocab=tuple(selected),
            guardrails=DesignGuardrails(
                safe_margin_px=32,
                min_body_px=MIN_BODY_PX,
                min_label_px=MIN_LABEL_PX,
                max_decoration_systems=1,
            ),
            provenance={
                "source_ids": sorted(source for source in source_ids if source),
                "artifact_schema": "1.1.0",
                "planning_policy": "content-fit-graph-v1",
                "compatibility_policy": self.library.graph["policy"],
                "style_source_id": style_source,
            },
            diagnostics=({"kind": "material-compatibility",
                          "policy": self.library.graph["policy"],
                          "selected_edges": self.library.compatibility.selection_edges(
                              layout.id, [self.library.items[selection.vocab_id] for selection in selected]
                          )},),
        )

    def plan_deck(self, profiles):
        return {profile.slide_id: self.plan(profile) for profile in profiles}
