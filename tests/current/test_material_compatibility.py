import copy
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from redeck_style.library import RuntimeLibrary
from redeck_style.library.compatibility import CompatibilityGraph
from redeck_style.pipeline import ProgramPipeline
from redeck_style.validation import validate_program
from scripts.build_runtime_library import compile_material_groups


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def library():
    return RuntimeLibrary()


def content_slides(role, evidence, **extra):
    return [{"slide_id": index, "role": role, "primary_proposition": "Evidence overview",
             "must_cover_subset": evidence, **extra} for index in range(1, 4)]


def build(library, slides, figures=None, **options):
    return ProgramPipeline(library, library.resolve_theme("gray-mono", "light"), slides, figures, **options)


def test_default_groups_are_non_color_material_families(library):
    assert len(library.dialects) == 7
    assert len(library.legacy_source_groups) == 30
    assert all(group_id.startswith("type-") for group_id in library.dialects)
    for group in library.dialects.values():
        assert group.rules["color_independent"]
        assert "palette" not in group.rules
        for item in library.query("typography", group.id):
            assert item.compatibility["typo_family"] == group.rules["typography_family"]
    assert len(library.query("content", "type-sans-clean")) == 262
    assert len(library.query("layout", "type-sans-clean")) == 335


def test_source_palette_changes_do_not_reclassify_materials():
    materials = [{"id": "background.example", "kind": "background", "provenance": {"seed_id": "example"},
                  "compatibility": {"dialect_ids": ["old-palette"]}}]
    first = copy.deepcopy(materials)
    second = copy.deepcopy(materials)
    catalog = {"example": {"dims": {"typo": "sans-clean", "palette": "blue", "lum": "dark"}}}
    first_groups = compile_material_groups(first, catalog)
    catalog["example"]["dims"].update(palette="orange", lum="light")
    assert first_groups == compile_material_groups(second, catalog)
    assert first[0]["compatibility"] == second[0]["compatibility"]
    assert first[0]["provenance"] != second[0]["provenance"]


def test_content_not_seed_drives_default_family(library):
    narrative = content_slides("context", ["A grounded explanation.", "Supporting context.", "An explicit limitation."])
    quantitative = content_slides("results", ["Accuracy is 91% against 82%.", "Recall is 88% against 79%.", "The test covers 200 tasks."])
    for seed in (7, 42, 73):
        assert build(library, narrative, seed=seed).deck_plan.dialect_id == "type-mixed-editorial"
        assert build(library, quantitative, seed=seed).deck_plan.dialect_id == "type-mono-tech"
    audit = build(library, quantitative).deck_plan.selection_audit
    assert audit["mode"] == "content-fit"
    assert audit["selected_reasons"]["quantitative_evidence"] > 0
    assert len(audit["candidates"]) == 7
    program = build(library, quantitative).programs[1]
    assert {edge["relation"] for edge in program.diagnostics[0]["selected_edges"]} == {
        "supports-content", "realizes", "style-companion", "requires-port", "provides-port"
    }


def test_source_figure_pressure_changes_material_family(library):
    slides = content_slides("context", ["A mechanism.", "A limitation.", "Supporting evidence."], assigned_figure_id="figure")
    figures = {"figure": {"kind": "figure", "path": "/tmp/source.png", "width": 900, "height": 600}}
    plan = build(library, slides, figures).deck_plan
    assert plan.dialect_id == "type-sans-clean"
    assert plan.selection_audit["content_summary"]["source_figures"] == 1


def test_theme_does_not_change_selection_or_graph(library):
    slides = content_slides("results", ["91% versus 82% over 200 tasks."])
    first = build(library, slides)
    second = ProgramPipeline(library, library.resolve_theme("teal-cool", "light"), slides)
    assert first.deck_plan.selection_audit == second.deck_plan.selection_audit
    for slide_id, program in first.programs.items():
        assert replace(program, theme_id=second.deck_plan.theme_id) == second.programs[slide_id]


def test_explicit_family_and_legacy_group_remain_available(library):
    slides = content_slides("results", ["91% versus 82% over 200 tasks."])
    explicit = build(library, slides, dialect_id="type-serif-classic")
    assert explicit.deck_plan.dialect_id == "type-serif-classic"
    assert explicit.deck_plan.selection_audit["mode"] == "explicit"
    legacy = build(library, slides, dialect_id="teal-cool_light")
    assert legacy.deck_plan.selection_audit["mode"] == "legacy-source-group"
    for program in legacy.programs.values():
        for selection in program.vocab:
            if selection.kind in {"background", "typography", "separator", "decoration"}:
                assert library.items[selection.vocab_id].provenance["source_palette"] == "teal-cool"


def test_graph_has_typed_relations_and_no_unknown_endpoints(library):
    counts = Counter(edge["relation"] for edge in library.graph["edges"])
    assert set(counts) == {"style-companion", "supports-content", "realizes", "requires-port", "provides-port"}
    assert all(count > 0 for count in counts.values())
    for edge in library.graph["edges"]:
        assert edge["source"] in library.compatibility.nodes
        assert edge["target"] in library.compatibility.nodes
        assert edge["reason"]


def test_graph_removal_changes_layout_selection(library):
    slides = content_slides("results", ["91% versus 82% over 200 tasks."])
    previous = build(library, slides).programs[1].composition.layout_inspiration_id
    payload = copy.deepcopy(library.graph)
    payload["edges"] = [edge for edge in payload["edges"]
                        if not (edge["source"] == previous and edge["relation"] == "supports-content")]
    library.compatibility = CompatibilityGraph(payload, library.items)
    current = build(library, slides).programs[1]
    assert current.composition.layout_inspiration_id != previous
    validate_program(current, library)


def test_missing_style_edge_is_rejected_not_just_logged(library):
    program = build(library, content_slides("context", ["One grounded statement."])).programs[1]
    background = next(item.vocab_id for item in program.vocab if item.kind == "background")
    payload = copy.deepcopy(library.graph)
    payload["edges"] = [edge for edge in payload["edges"]
                        if not (edge["target"] == background and edge["relation"] == "style-companion")]
    library.compatibility = CompatibilityGraph(payload, library.items)
    with pytest.raises(ValueError, match="style companion edge missing"):
        validate_program(program, library)


def test_cross_source_style_mix_is_rejected(library):
    program = build(library, content_slides("context", ["One grounded statement."])).programs[1]
    original = next(item for item in program.vocab if item.kind == "background")
    replacement = next(item for item in library.query("background", program.dialect_id) if item.id != original.vocab_id)
    changed = replace(program, vocab=tuple(replace(item, vocab_id=replacement.id) if item.kind == "background" else item for item in program.vocab))
    with pytest.raises(ValueError, match="style companion edge missing"):
        validate_program(changed, library)


@pytest.mark.parametrize("defect", ["empty-policy", "unknown-target", "duplicate-edge", "missing-port"])
def test_invalid_graph_fails_closed(library, defect):
    payload = copy.deepcopy(library.graph)
    if defect == "empty-policy":
        payload.pop("policy")
    elif defect == "unknown-target":
        payload["edges"][0]["target"] = "missing-material"
    elif defect == "duplicate-edge":
        payload["edges"].append(payload["edges"][0])
    else:
        index = next(index for index, edge in enumerate(payload["edges"]) if edge["relation"] == "requires-port")
        payload["edges"].pop(index)
    with pytest.raises(ValueError):
        CompatibilityGraph(payload, library.items)


def test_full_packaged_decks_have_graph_compatible_programs(library):
    for path in sorted((ROOT / "examples/blueprints").glob("*_real_document.json")):
        slides = json.loads(path.read_text())["slides"]
        for family_id in library.dialects:
            pipeline = build(library, slides, dialect_id=family_id)
            for program in pipeline.programs.values():
                assert validate_program(program, library) is program
