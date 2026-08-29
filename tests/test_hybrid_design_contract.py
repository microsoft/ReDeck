"""Focused coverage for the canonical hybrid generation and repair mode."""

from unittest.mock import MagicMock

from app.backends.html_codegen.html_codegen_compiler import (
    HTML_CODEGEN_PROMPT_VERSION,
    HtmlCodeGenCompiler,
)
from app.backends.html_codegen.visual_skills import (
    format_visual_skill_references,
    get_visual_skill,
    select_visual_skills,
)
from app.modules.redeck.agent_repair import AgentRepair, AgentState
from app.schemas.blueprint import BlueprintSlide
from app.schemas.evidence import EvidenceState, TableRef
from app.themes import (
    COMPOSITION_VARIANT_VERSION,
    LAYOUT_GRAMMARS,
    THEME_REGISTRY,
    format_html_design_contract,
    select_composition_variant,
    select_layout_grammar,
)


class CapturingLLM:
    def __init__(self):
        self.calls = []

    def call_text(self, **kwargs):
        self.calls.append(kwargs)
        return """```html
<!DOCTYPE html><html><head><style>:root {
--canvas:#FFF8F5; --ink:#29434C; --primary:#D95F68;
}</style></head><body><h1>Result</h1></body></html>
```"""


def _slide(**overrides):
    data = {
        "slide_id": 2,
        "role": "results",
        "primary_proposition": "Model A reaches 81.2% while Model B reaches 76.4%",
        "narrative_position": "body",
        "must_cover_subset": ["Accuracy 81.2%", "Latency 42 ms"],
    }
    data.update(overrides)
    return BlueprintSlide(**data)


def test_layout_contract_and_variants_cover_content_signals():
    assert len(LAYOUT_GRAMMARS) == 8
    assert select_layout_grammar("title").grammar_id == "editorial"
    assert select_layout_grammar("method", has_images=True).grammar_id == "figure_led"
    assert select_layout_grammar("results", has_table=True).grammar_id == "data_led"
    assert select_layout_grammar(
        "comparison", content_text="Compare option A versus option B"
    ).grammar_id == "comparative_field"
    assert select_layout_grammar(
        "context", content_text="Talk roadmap from motivation to results"
    ).grammar_id == "editorial"

    grammar = select_layout_grammar("results", has_images=True)
    variants = {
        select_composition_variant(
            grammar,
            slide_role="results",
            slide_index=index,
            has_images=True,
            content_text="Accuracy improves 19% and latency drops 48%",
            image_aspect=2.0,
        ).variant_id
        for index in range(7, 11)
    }
    assert len(variants) >= 3
    assert COMPOSITION_VARIANT_VERSION == "composition_variants.v1"


def test_design_contract_uses_style_palette_and_anti_card_hierarchy():
    contract = format_html_design_contract(
        THEME_REGISTRY["coral_tide"], select_layout_grammar("conclusion")
    )
    assert "--canvas: #FFF8F5" in contract
    assert "--primary: #D95F68" in contract
    assert "Layout Grammar" in contract
    assert "never nest cards" in contract.lower()
    assert "Express each fact once" in contract


def test_compiler_prompt_uses_one_contract_and_small_skill_set():
    compiler = HtmlCodeGenCompiler(CapturingLLM(), theme_id="coral_tide")
    compiler._theme = THEME_REGISTRY["coral_tide"]
    evidence = EvidenceState(tables=[TableRef(
        table_id="table_1",
        source_file="paper.pdf",
        content="Model | Accuracy\nA | 81.2%\nB | 76.4%",
        caption="Benchmark accuracy",
    )])
    prompt, has_images = compiler._build_slide_prompt(
        _slide(linked_evidence_ids=["table_1"], layout_hint="table-focus"),
        evidence,
        image_dir=None,
        available_images=[],
        total_slides=5,
    )

    assert has_images is False
    assert compiler._codegen_prompt_name == "slide_html_codegen_anticard"
    assert HTML_CODEGEN_PROMPT_VERSION == "slide_html_codegen.hybrid.v1"
    assert "Layout Grammar" in prompt
    assert "Composition Variant" in prompt
    assert "Slide-Specific Complexity Budget" in prompt
    assert "Retrieved HTML Visual Skills" in prompt
    assert 2 <= len(compiler._slide_skills[2]) <= 3
    assert "Non-Card Component Library" not in prompt


def test_no_image_agenda_stays_editorial_without_fake_geometry():
    compiler = HtmlCodeGenCompiler(CapturingLLM(), theme_id="coral_tide")
    compiler._theme = THEME_REGISTRY["coral_tide"]
    prompt, _ = compiler._build_slide_prompt(
        _slide(
            role="context",
            primary_proposition="Talk roadmap moves from motivation to evidence",
            must_cover_subset=["Problem", "Method", "Evidence"],
            layout_hint="three-column",
        ),
        EvidenceState(),
        image_dir=None,
        available_images=[],
        total_slides=5,
    )
    assert compiler._slide_grammars[2].grammar_id == "editorial"
    assert "No-Image Editorial Discipline" in prompt
    assert "Do not use inline SVG" in prompt
    assert "`phase_path`" not in prompt
    assert "`process_topology`" not in prompt


def test_repair_prompt_preserves_design_lineage(tmp_path):
    llm = CapturingLLM()
    compiler = HtmlCodeGenCompiler(llm, theme_id="coral_tide")
    compiler._theme = THEME_REGISTRY["coral_tide"]
    grammar = select_layout_grammar("results", has_table=True)
    compiler._slide_grammars[2] = grammar
    compiler._slide_variants[2] = select_composition_variant(
        grammar, slide_role="results", slide_index=2, has_table=True
    )
    compiler._slide_skills[2] = [get_visual_skill("quantitative_table_signal")]
    compiler.slide_codes[2] = (
        "<!DOCTYPE html><html><head><style>:root { --canvas:#FFF8F5; "
        "--ink:#29434C; --primary:#D95F68; }</style></head>"
        "<body><h1>Result</h1></body></html>"
    )

    assert compiler.repair_slide(
        2,
        issues=[{"severity": "major", "description": "Table is clipped"}],
        blueprint_slide=_slide(),
        evidence=EvidenceState(),
        case_dir=tmp_path,
    ) is not None
    repair_prompt = llm.calls[-1]["user_content"]
    assert "Layout Grammar" in repair_prompt
    assert "Composition Variant" in repair_prompt
    assert "`quantitative_table_signal`" in repair_prompt
    assert "PRESERVE STYLE" in repair_prompt


def test_visual_skill_selection_is_small_and_local():
    skills = select_visual_skills(
        select_layout_grammar("method", has_images=True),
        slide_role="method",
        content_text="A four-stage visual pipeline",
        has_images=True,
        has_table=False,
        limit=3,
    )
    assert 2 <= len(skills) <= 3
    context = format_visual_skill_references(skills)
    assert "{{" in context
    assert "width:1280px" not in context.replace(" ", "")
    assert "position: absolute" not in context

    process_skills = select_visual_skills(
        select_layout_grammar(
            "method", content_text="A three-stage pipeline transforms inputs into outputs"
        ),
        slide_role="method",
        content_text="A three-stage pipeline transforms inputs into outputs",
        has_images=False,
        has_table=False,
        evidence_item_count=3,
        limit=3,
    )
    process_ids = [skill.skill_id for skill in process_skills]
    assert "process_topology" in process_ids
    assert "two_dimension_synthesis" not in process_ids


def test_layout_only_repair_enforces_cumulative_text_loss_budget():
    repair = AgentRepair(MagicMock(), repair_config={"text_loss_budget": 1})
    repair._test_compile = MagicMock(return_value=True)
    original = (
        "<html><body><p>essential context supports conclusion clearly</p>"
        "</body></html>"
    )
    state = AgentState(
        original_code=original,
        current_code=original,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"text_overflow"},
        text_loss_budget=1,
    )

    _, changed = repair._tool_apply_edits({
        "edits": [{"search": "essential ", "replace": ""}],
    }, state)
    assert changed is True
    assert state.cumulative_words_lost == 1

    message, changed = repair._tool_apply_edits({
        "edits": [{"search": "context ", "replace": ""}],
    }, state)
    assert changed is False
    assert "CSS-only" in message
    assert "context" in state.current_code


def test_layout_only_repair_never_drops_value_bearing_tokens():
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    original = "<html><body><p>Accuracy reaches 81.2% on AV2</p></body></html>"
    state = AgentState(
        original_code=original,
        current_code=original,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"text_overflow"},
    )
    message, changed = repair._tool_apply_edits({
        "edits": [{"search": "81.2% on AV2", "replace": ""}],
    }, state)
    assert changed is False
    assert "value-bearing" in message
    assert state.current_code == original


def test_rollback_returns_to_immediately_previous_checkpoint():
    repair = AgentRepair(MagicMock())
    repair._test_compile = MagicMock(return_value=True)
    original = "<html><body><p style='color:red'>Text remains here</p></body></html>"
    state = AgentState(
        original_code=original,
        current_code=original,
        checkpoints=[original],
        slide_id=1,
        codegen_compiler=MagicMock(),
        case_dir=".",
        issue_types={"low_contrast"},
    )
    repair._tool_apply_edits({"edits": [{"search": "color:red", "replace": "color:blue"}]}, state)
    after_first = state.current_code
    repair._tool_apply_edits({"edits": [{"search": "color:blue", "replace": "color:black"}]}, state)

    repair._tool_rollback({"steps": 1}, state)
    assert state.current_code == after_first
