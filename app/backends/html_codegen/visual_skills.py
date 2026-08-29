"""Composable HTML visual skills for slide code generation.

The public demo contains useful component-level idioms, but its complete pages
are too specific to use as templates.  This module retrieves a small number of
local code references from content signals.  The generator remains responsible
for the page composition and may adapt or omit a retrieved skill when the
evidence does not support it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from ...themes import LayoutGrammar


VISUAL_SKILL_LIBRARY_VERSION = "demo_visual_skills.v6"
_SKILL_DIR = Path(__file__).parent.parent.parent / "prompts" / "codegen" / "visual_skills"


@dataclass(frozen=True)
class VisualSkill:
    """Metadata and code reference for one local, composable visual idiom."""

    skill_id: str
    name: str
    semantic_use: str
    required_evidence: str
    composition_affordances: str
    incompatible_with: tuple[str, ...]
    density_cost: str
    compatible_grammars: tuple[str, ...]
    structural_invariants: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    requires_images: bool = False
    requires_table: bool = False
    min_numeric: int = 0

    @property
    def code_reference(self) -> str:
        """Load the compact HTML/CSS/SVG fragment shipped with this skill."""

        path = _SKILL_DIR / f"{self.skill_id}.html"
        return path.read_text(encoding="utf-8").strip()


VISUAL_SKILLS: tuple[VisualSkill, ...] = (
    VisualSkill(
        skill_id="editorial_header",
        name="Editorial Header Field",
        semantic_use="Connect an eyebrow, concise thesis, and context line as one hierarchy.",
        required_evidence="A supported slide thesis and, when available, one concise context line.",
        composition_affordances="Can span the page or occupy one side of an asymmetric composition; it does not prescribe the body grid.",
        incompatible_with=(),
        density_cost="low",
        compatible_grammars=(
            "editorial", "figure_led", "data_led", "comparative_field",
            "process_system", "timeline_roadmap", "evidence_dashboard", "structured_cards",
        ),
        structural_invariants=(
            "The thesis appears once; eyebrow, headline, and context line form one hierarchy.",
            "Numeric hero treatments belong to a separately retrieved metric skill, not this header.",
        ),
        failure_modes=("Do not split one thesis sentence into redundant term/direction/framing modules.",),
    ),
    VisualSkill(
        skill_id="figure_evidence_frame",
        name="Inspectable Figure With Evidence Keys",
        semantic_use="Make a real source figure dominant and connect two to four observations to visible regions.",
        required_evidence="At least one supplied image with a trustworthy caption or description.",
        composition_affordances="Supports sidecar, full-width band, centered stage, right-hand proof object, and strip variants; the figure keeps its natural aspect ratio.",
        incompatible_with=("process_topology",),
        density_cost="medium",
        compatible_grammars=("figure_led", "data_led", "evidence_dashboard"),
        structural_invariants=(
            "The source image remains the largest inspectable object and keeps its natural aspect ratio.",
            "Use only one macro modifier and one annotation system for the figure.",
            "Annotation copy uses a dedicated class; inline emphasis inside it must remain inline.",
        ),
        failure_modes=("Do not use broad descendant span selectors that turn inline highlights into block elements.",),
        roles=("method", "results", "analysis", "qualitative", "case_study"),
        requires_images=True,
    ),
    VisualSkill(
        skill_id="process_topology",
        name="Content-Specific Process Topology",
        semantic_use="Explain stages, components, transformations, feedback, or structural relationships with an inline SVG system.",
        required_evidence="Named stages/components and an evidence-supported relationship among them.",
        composition_affordances="Supports linear, branching, converging, or contained topologies; surrounding annotations remain free-form.",
        incompatible_with=("figure_evidence_frame",),
        density_cost="medium",
        compatible_grammars=("process_system", "editorial", "structured_cards"),
        structural_invariants=("Every visible node and connector represents a supplied entity or relationship.",),
        failure_modes=("Do not derive multiple pseudo-stages by splitting one sentence into isolated keywords.",),
        roles=("method", "architecture", "overview"),
        keywords=(
            "process", "pipeline", "workflow", "architecture", "system", "stage",
            "component", "mechanism", "cycle", "graph", "network", "structure",
        ),
    ),
    VisualSkill(
        skill_id="hero_metric_rail",
        name="Hero Metric And Supporting Rail",
        semantic_use="Turn one decisive value and up to three supporting facts into a varied, shared evidence band.",
        required_evidence="One to four supported values with distinct semantic roles; do not duplicate the same value.",
        composition_affordances="Works horizontally or vertically and can attach to a chart, table, figure, or editorial field.",
        incompatible_with=(),
        density_cost="low",
        compatible_grammars=("data_led", "evidence_dashboard", "editorial", "timeline_roadmap"),
        structural_invariants=("Each metric has a distinct semantic role and the lead value is shown only once.",),
        roles=("title", "opening", "results", "evaluation", "comparison", "conclusion", "roadmap"),
        min_numeric=1,
    ),
    VisualSkill(
        skill_id="ranked_evidence_rows",
        name="Ranked Evidence Rows",
        semantic_use="Present findings or contributions as aligned, numbered statements with optional right-edge evidence values.",
        required_evidence="Two to five parallel findings, contributions, risks, or outcomes.",
        composition_affordances="Rows can occupy a full field or balance a hero value; rules and baselines provide structure without cards.",
        incompatible_with=("quantitative_table_signal",),
        density_cost="medium",
        compatible_grammars=("evidence_dashboard", "structured_cards", "editorial"),
        structural_invariants=("Rows share one alignment and each row contains a distinct supported finding.",),
        roles=("results", "evaluation", "conclusion", "discussion", "overview", "context"),
        keywords=("finding", "contribution", "outcome", "risk", "insight", "takeaway"),
    ),
    VisualSkill(
        skill_id="quantitative_table_signal",
        name="Quantitative Table With Signal",
        semantic_use="Preserve dense lookup values while using selective emphasis, numeric alignment, and a compact interpretation region.",
        required_evidence="A supplied table or genuinely tabular evidence with comparable rows and columns.",
        composition_affordances="The table can dominate the body or share space with a narrow insight rail; it is not wrapped in a decorative card.",
        incompatible_with=("ranked_evidence_rows", "comparison_bar_field", "shared_comparison_field"),
        density_cost="high",
        compatible_grammars=("data_led", "evidence_dashboard"),
        structural_invariants=(
            "Keep supplied rows and columns aligned; highlight cells, not entire arbitrary regions.",
            "Table labels and IDs from prompt metadata are not visible slide content.",
        ),
        roles=("results", "evaluation", "comparison", "ablation", "setup"),
        requires_table=True,
    ),
    VisualSkill(
        skill_id="comparison_bar_field",
        name="Direct-Labeled Comparison Bars",
        semantic_use="Expose rank, magnitude, gap, or threshold across three to seven numeric alternatives.",
        required_evidence="At least three comparable values with consistent units.",
        composition_affordances="The bar field may be wide or paired with a factor/interpretation rail; labels and values remain direct.",
        incompatible_with=("quantitative_table_signal", "shared_comparison_field"),
        density_cost="medium",
        compatible_grammars=("evidence_dashboard", "data_led", "comparative_field"),
        structural_invariants=("All bars share a stated scale and direct labels use the supplied unit.",),
        roles=("results", "evaluation", "comparison", "ablation"),
        keywords=("rank", "benchmark", "accuracy", "latency", "cost", "performance", "score"),
        min_numeric=3,
    ),
    VisualSkill(
        skill_id="shared_comparison_field",
        name="Shared-Criteria Comparison Field",
        semantic_use="Compare alternatives against the same criteria, axis, or baseline instead of using isolated cards.",
        required_evidence="Two to four alternatives and at least two supported comparison dimensions or ordered attributes.",
        composition_affordances="Criteria may form rows, columns, a continuum, or a matrix; the preferred/combined option receives focused emphasis.",
        incompatible_with=("quantitative_table_signal", "comparison_bar_field"),
        density_cost="medium",
        compatible_grammars=("comparative_field", "structured_cards"),
        structural_invariants=(
            "Every alternative is evaluated on the same visible criteria rows.",
            "Focused cells stay aligned with peer cells; no sparse option expands across empty rows.",
        ),
        failure_modes=("Do not turn a short preferred option into a large mostly empty feature card.",),
        roles=("comparison", "evaluation", "overview", "context"),
        keywords=("compare", "comparison", "versus", "alternative", "trade-off", "tradeoff", "hybrid"),
    ),
    VisualSkill(
        skill_id="two_dimension_synthesis",
        name="Two-Dimension Synthesis Field",
        semantic_use="Show two complementary attributes and a third alternative that explicitly combines both.",
        required_evidence="Two distinct attributes plus an evidence-supported combined, hybrid, or integrated alternative.",
        composition_affordances="The axes may be horizontal rows or a compact coordinate field; all three alternatives remain peers.",
        incompatible_with=("shared_comparison_field", "comparison_bar_field", "quantitative_table_signal"),
        density_cost="medium",
        compatible_grammars=("comparative_field", "process_system"),
        structural_invariants=(
            "Use exactly the supplied attributes as the shared dimensions.",
            "The combined alternative marks both dimensions but does not become a large empty panel.",
        ),
        failure_modes=("Do not add arrows or imply causality unless the evidence states a transformation.",),
        roles=("comparison", "overview", "method"),
        keywords=("hybrid", "combine", "combines", "combined", "integrate", "integrated", "both"),
    ),
    VisualSkill(
        skill_id="phase_path",
        name="Continuous Phase Path",
        semantic_use="Show chronology, phases, milestones, and outcomes on one continuous progression.",
        required_evidence="Three to six ordered phases or dated milestones.",
        composition_affordances="Phase widths and annotation heights can vary; supporting metrics may sit outside the path.",
        incompatible_with=(),
        density_cost="medium",
        compatible_grammars=("timeline_roadmap", "process_system"),
        structural_invariants=("All phases share one chronological path; widths reflect known duration or deliberate emphasis.",),
        roles=("roadmap", "timeline", "overview", "method"),
        keywords=("phase", "timeline", "roadmap", "milestone", "quarter", "year", "sequence"),
    ),
    VisualSkill(
        skill_id="evidence_annotation",
        name="Evidence Annotation",
        semantic_use="Attach one compact interpretation or scope note to another visual without creating a card.",
        required_evidence="One supported interpretation, definition, limitation, or scope statement.",
        composition_affordances="Can align to any grid edge, sit below a dominant object, or become a narrow side annotation.",
        incompatible_with=(),
        density_cost="low",
        compatible_grammars=(
            "editorial", "figure_led", "data_led", "comparative_field",
            "process_system", "timeline_roadmap", "evidence_dashboard", "structured_cards",
        ),
        structural_invariants=("The annotation attaches to a relevant visual edge and does not repeat the title.",),
    ),
)


_SKILL_BY_ID = {skill.skill_id: skill for skill in VISUAL_SKILLS}

_GRAMMAR_PREFERENCES: dict[str, tuple[str, ...]] = {
    "editorial": ("hero_metric_rail",),
    "figure_led": ("figure_evidence_frame",),
    "data_led": ("quantitative_table_signal", "figure_evidence_frame", "comparison_bar_field", "hero_metric_rail"),
    "comparative_field": ("two_dimension_synthesis", "shared_comparison_field", "comparison_bar_field", "hero_metric_rail"),
    "process_system": ("process_topology", "phase_path"),
    "timeline_roadmap": ("phase_path", "hero_metric_rail"),
    "evidence_dashboard": ("comparison_bar_field", "ranked_evidence_rows", "hero_metric_rail"),
    "structured_cards": ("ranked_evidence_rows", "shared_comparison_field", "process_topology"),
}


def _numeric_count(text: str) -> int:
    return len(re.findall(r"(?<![A-Za-z])[$]?[0-9][0-9,.]*(?:%|ms|s|x|M|B|K)?", text))


def _is_talk_agenda(text: str) -> bool:
    return any(token in text for token in (
        "talk roadmap", "presentation roadmap", "deck roadmap", "outline", "agenda",
    ))


def _has_explicit_phase_evidence(text: str) -> bool:
    temporal_markers = (
        "timeline", "milestone", "phase", "chronolog", "duration", "dated",
        "year", "month", "q1", "q2", "q3", "q4",
    )
    process_markers = ("stage", "step", "iteration", "round")
    return any(token in text for token in temporal_markers) or (
        any(token in text for token in process_markers)
        and any(token in text for token in ("then", "after", "before", "next", "sequence"))
    )


def select_visual_skills(
    grammar: LayoutGrammar,
    *,
    slide_role: str,
    content_text: str,
    has_images: bool,
    has_table: bool,
    evidence_item_count: int = 0,
    limit: int = 3,
) -> list[VisualSkill]:
    """Retrieve two to four compatible local skills from general content signals."""

    limit = max(2, min(limit, 4))
    role = (slide_role or "").lower()
    text = content_text.lower()
    numeric_count = _numeric_count(content_text)
    no_visual_evidence = not has_images and not has_table
    selected = [_SKILL_BY_ID["editorial_header"]]
    preferences = _GRAMMAR_PREFERENCES.get(grammar.grammar_id, ())
    preference_score = {
        skill_id: (len(preferences) - index) * 10
        for index, skill_id in enumerate(preferences)
    }

    ranked: list[tuple[int, str, VisualSkill]] = []
    for skill in VISUAL_SKILLS:
        if skill.skill_id in {"editorial_header", "evidence_annotation"}:
            continue
        if skill.requires_images and not has_images:
            continue
        if skill.requires_table and not has_table:
            continue
        if numeric_count < skill.min_numeric:
            continue
        if (
            grammar.grammar_id == "data_led"
            and has_images
            and not has_table
            and skill.skill_id == "comparison_bar_field"
        ):
            continue
        if skill.skill_id == "phase_path":
            if _is_talk_agenda(text) or not _has_explicit_phase_evidence(text):
                continue
        if skill.skill_id == "two_dimension_synthesis":
            if evidence_item_count < 3 or not any(token in text for token in (
                "hybrid", "combine", "combines", "combined", "integrate",
                "integrated", "both",
            )):
                continue
        if skill.skill_id == "shared_comparison_field":
            if evidence_item_count < 2 or not any(token in text for token in (
                "compare", "comparison", "versus", " vs ", "alternative",
                "trade-off", "tradeoff",
            )):
                continue
        if skill.skill_id == "ranked_evidence_rows" and evidence_item_count < 2:
            continue
        if (
            skill.skill_id == "process_topology"
            and no_visual_evidence
            and (
                grammar.grammar_id == "editorial"
                or evidence_item_count < 3
                or not any(token in text for token in (
                    "architecture", "pipeline", "workflow", "stage", "component",
                    "branch", "input", "output", "residual", "interpolat",
                ))
            )
        ):
            continue
        if (
            skill.skill_id == "hero_metric_rail"
            and no_visual_evidence
            and role in {"context", "comparison"}
            and numeric_count < 2
        ):
            continue

        score = preference_score.get(skill.skill_id, 0)
        if grammar.grammar_id in skill.compatible_grammars:
            score += 8
        if role in skill.roles:
            score += 4
        score += min(6, sum(2 for keyword in skill.keywords if keyword in text))
        if skill.requires_images and has_images:
            score += 8
        if skill.requires_table and has_table:
            score += 8
        if skill.min_numeric and numeric_count >= skill.min_numeric:
            score += 3
        if score >= 10:
            ranked.append((score, skill.skill_id, skill))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    for _, _, skill in ranked:
        if len(selected) >= limit:
            break
        if any(
            existing.skill_id in skill.incompatible_with
            or skill.skill_id in existing.incompatible_with
            for existing in selected
        ):
            continue
        selected.append(skill)

    if len(selected) == 1:
        selected.append(_SKILL_BY_ID["evidence_annotation"])

    return selected


def format_visual_skill_references(skills: list[VisualSkill], *, include_code: bool = True) -> str:
    """Format retrieved skills as prompt context, not mandatory templates."""

    if not skills:
        return ""
    lines = [
        f"## Retrieved HTML Visual Skills ({VISUAL_SKILL_LIBRARY_VERSION})",
        "",
        "These are local component idioms extracted from strong slide implementations. "
        "They are references, not a page template:",
        "- Borrow element language and hierarchy; do not copy sample content or whole-page coordinates.",
        "- Choose only the fragments that fit the supplied evidence. You may combine, reshape, or omit a fragment.",
        "- Keep the selected Design Contract palette and create the overall page composition yourself.",
        "- Replace every `{{...}}` placeholder with supplied evidence. Never render a placeholder or invent a value.",
    ]
    for skill in skills:
        lines.extend([
            "",
            f"### `{skill.skill_id}` - {skill.name}",
            f"- Semantic use: {skill.semantic_use}",
            f"- Required evidence: {skill.required_evidence}",
            f"- Composition affordances: {skill.composition_affordances}",
            f"- Structural invariants: {'; '.join(skill.structural_invariants) if skill.structural_invariants else 'none'}",
            f"- Failure modes: {'; '.join(skill.failure_modes) if skill.failure_modes else 'none'}",
            f"- Incompatible with: {', '.join(skill.incompatible_with) if skill.incompatible_with else 'none'}",
            f"- Density cost: {skill.density_cost}",
        ])
        if include_code:
            lines.extend(["", "```html", skill.code_reference, "```"])
    return "\n".join(lines)


def get_visual_skill(skill_id: str) -> VisualSkill:
    """Return one registered skill by ID."""

    return _SKILL_BY_ID[skill_id]
