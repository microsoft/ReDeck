from dataclasses import replace

import pytest

from redeck_style.domain.density import density_policy
from redeck_style.library import RuntimeLibrary
from redeck_style.pipeline import ProgramPipeline
from redeck_style.rendering.prompt_renderer import _semantic_architecture, _table_display_plan
from redeck_style.validation import validate_program


SLIDE = {
    "slide_id": 1, "role": "results", "primary_proposition": "Model Orion improves the benchmark.",
    "must_cover_subset": ["Orion reaches 0.9 on the benchmark.", "All models use the same evaluation protocol."],
    "assigned_figure_id": "benchmark",
}
FIGURE = {
    "kind": "table", "row_count": 12, "col_count": 2, "caption": "Benchmark",
    "rows": [["Baselines", None], *[[f"Baseline {index}", str(index / 10)] for index in range(1, 5)],
             ["Refiners", None], ["Orion", "0.9"], *[[f"Refiner {index}", str(index / 10)] for index in range(2, 6)],
             [None, None]],
}
SUPPORT = [
    "All benchmark models use patient-separated evaluation to prevent leakage between training and evaluation.",
    "The benchmark includes recordings from multiple hospitals with different measurement devices.",
    "The evaluation protocol reports results over three repeated trials for each model.",
    "The authors limit the benchmark conclusions to the measured cohort rather than all clinical settings.",
]


@pytest.fixture(scope="module")
def library():
    return RuntimeLibrary()


def pipeline(library, mode="balanced", slide=None, figures=None):
    return ProgramPipeline(library, library.resolve_theme("teal-cool", "light"), [slide or SLIDE],
                           {"benchmark": FIGURE} if figures is None else figures, information_density=mode)


def test_density_is_independent_of_style_and_readability(library):
    balanced, rich = pipeline(library), pipeline(library, "evidence-rich")
    assert balanced.deck_plan == rich.deck_plan
    before, after = balanced.programs[1], rich.programs[1]
    assert before.theme_id == after.theme_id
    assert before.dialect_id == after.dialect_id
    assert before.guardrails == after.guardrails
    assert before.content_profile == after.content_profile
    assert [item.vocab_id for item in before.vocab] == [item.vocab_id for item in after.vocab]
    assert after.to_dict()["information_density"] == "evidence-rich"
    assert after.composition.focal_role == "comparison"
    assert validate_program(after, library) is after


def test_rich_mode_expands_evidence_not_card_quotas(library):
    balanced = _semantic_architecture(pipeline(library).programs[1], SLIDE, SUPPORT)
    rich = _semantic_architecture(pipeline(library, "evidence-rich").programs[1], SLIDE, SUPPORT)
    assert len(balanced["optional_source_detail_reservoir"]) == 2
    assert len(rich["optional_source_detail_reservoir"]) == 4
    assert balanced["content_budget"]["maximum_optional_source_details"] == 1
    assert rich["content_budget"]["maximum_optional_source_details"] == 3
    assert rich["content_budget"]["target_distinct_source_details"] == 2
    assert rich["required_evidence"] == balanced["required_evidence"]
    assert "never fabricate facts" in rich["content_budget"]["evidence_rich_policy"]
    assert "62-78%" in rich["content_budget"]["target_content_coverage"]


@pytest.mark.parametrize("available", [0, 1])
def test_source_shortfall_never_creates_mandatory_filler(library, available):
    program = pipeline(library, "evidence-rich").programs[1]
    architecture = _semantic_architecture(program, SLIDE, SUPPORT[:available])
    budget = architecture["content_budget"]
    assert budget["target_distinct_source_details"] == available
    assert budget["maximum_optional_source_details"] == available
    assert "keep whitespace" in budget["evidence_rich_policy"]


def test_title_does_not_become_a_dense_report(library):
    slide = {**SLIDE, "role": "title", "assigned_figure_id": None}
    balanced = pipeline(library, slide=slide, figures={}).programs[1]
    rich = pipeline(library, "evidence-rich", slide=slide, figures={}).programs[1]
    assert balanced.composition == rich.composition
    budget = _semantic_architecture(rich, slide, SUPPORT)["content_budget"]
    assert budget["maximum_optional_source_details"] == 0
    assert budget["target_distinct_source_details"] == 0


def test_rich_non_numeric_content_does_not_invent_data_or_arrows(library):
    slide = {"slide_id": 1, "role": "discussion", "primary_proposition": "Inclusion depends on autonomy.",
             "must_cover_subset": ["Participation matters.", "Language is cultural."]}
    program = pipeline(library, "evidence-rich", slide=slide, figures={}).programs[1]
    architecture = _semantic_architecture(program, slide, [])
    assert architecture["content_budget"]["minimum_numeric_marks"] == 0
    assert architecture["connector_policy"]["eligible_relations"] == []
    assert "Do not add charts to non-numeric arguments" in architecture["content_budget"]["evidence_rich_policy"]


def test_table_adds_verbatim_context_and_excludes_group_headers():
    balanced = _table_display_plan(FIGURE, ["Orion 0.9"], 6)
    rich = _table_display_plan(FIGURE, ["Orion 0.9"], 8, include_context_rows=True)
    assert balanced["display_row_count"] == 1
    assert rich["display_row_count"] == 8
    assert rich["source_raw_row_count"] == 12
    assert rich["source_row_count"] == 9
    assert rich["omitted_row_count"] == 1
    assert rich == _table_display_plan(FIGURE, ["Orion 0.9"], 8, include_context_rows=True)
    assert {"Baselines", "Refiners"} == {row["source_group"] for row in rich["rows"]}
    for row in rich["rows"]:
        assert row["cells"] == FIGURE["rows"][row["source_row_index"]]
    assert balanced["rows"][0] in rich["rows"]


def test_empty_or_unmatched_table_is_bounded():
    assert _table_display_plan({"rows": []}, ["claim"], 8, True)["display_row_count"] == 0
    result = _table_display_plan(FIGURE, ["unmatched"], 3, True)
    assert result["display_row_count"] == 3
    assert result["omitted_row_count"] == 6


def test_policy_reaches_planner_and_prompt(library):
    rich = pipeline(library, "evidence-rich")
    selection = next(item for item in rich.programs[1].vocab if item.kind == "content")
    assert selection.parameters["max_display_rows"] == 8
    assert selection.parameters["include_context_rows"] is True
    prompt = rich.prompt_for(SLIDE, " ".join(SUPPORT))
    assert '"information_density": "evidence-rich"' in prompt
    assert '"mode": "claim-and-context-excerpt"' in prompt
    assert "contextual comparison rows" in prompt
    assert "Never increase density by reducing body scale" in prompt
    assert '"source_row_count": 9' in prompt


def test_invalid_density_is_rejected(library):
    with pytest.raises(ValueError, match="Unknown information density"):
        density_policy("artificial-overlap", "results")
    with pytest.raises(ValueError, match="Unknown information density"):
        pipeline(library, "artificial-overlap")
    with pytest.raises(ValueError, match="unsupported information density"):
        validate_program(replace(pipeline(library).programs[1], information_density="invalid"), library)
