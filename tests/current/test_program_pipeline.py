import json
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from redeck_style.library import RuntimeLibrary
from redeck_style.pipeline import ProgramPipeline
from redeck_style.validation import validate_program
from redeck_style.style_grammar import STYLE_GRAMMARS, _active_operations
from redeck_style.rendering.prompt_renderer import _design_kernel, _visual_encoding_plan, _semantic_architecture
from redeck_style.planning.content_profiler import build_content_profile
from scripts.codegen import (
    build_group_prompt,
    extract_html_documents,
    load_case,
    resolve_blueprint,
    resolve_slide_assets,
)
from scripts.codegen import SYSTEM_PROMPT
from scripts.codegen import bams_repair_feedback


ROOT = Path(__file__).resolve().parents[2]


class ProgramPipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = RuntimeLibrary()
        cls.blueprint = json.loads(
            (ROOT / "tests" / "fixtures" / "planner_blueprint.json").read_text()
        )
        cls.theme = cls.library.resolve_theme("blue-corporate", "dark")

    def build(self, figures=None):
        return ProgramPipeline(
            self.library, self.theme, self.blueprint["slides"], figures or {}, seed=42
        )

    def test_one_valid_bounded_brief_per_slide(self):
        pipeline = self.build()
        self.assertEqual(len(pipeline.programs), len(self.blueprint["slides"]))
        for program in pipeline.programs.values():
            self.assertIs(validate_program(program, self.library), program)
            self.assertEqual(program.schema_version, "2.0.0")
            self.assertEqual(sum(p.kind == "background" for p in program.vocab), 1)
            self.assertEqual(sum(p.kind == "typography" for p in program.vocab), 1)
            self.assertEqual(sum(p.kind == "content" for p in program.vocab), 1)

    def test_program_does_not_freeze_page_geometry(self):
        pipeline = self.build()
        for program in pipeline.programs.values():
            payload = program.to_dict()
            self.assertNotIn("regions", payload)
            self.assertNotIn("relations", payload)
            self.assertNotIn("primitives", payload)
            self.assertNotIn("budgets", payload)
            serialized = json.dumps(payload)
            self.assertNotRegex(serialized, r'"(?:x_pct|y_pct|w_pct|h_pct|target_region|z_layer)"')

    def test_title_uses_title_content_grammar(self):
        program = self.build().programs[1]
        content = next(selection for selection in program.vocab if selection.kind == "content")
        self.assertEqual(content.parameters["content_kind"], "title-only")

    def test_evidence_order_never_creates_causal_or_comparison_edges(self):
        program = self.build().programs[2]
        for role in ("context", "method", "evaluation", "results", "comparison", "conclusion"):
            slide = {"slide_id": 2, "role": role, "primary_proposition": "Evidence overview",
                     "must_cover_subset": ["Private workflow logs are scarce.", "Synthetic context is useful.", "Multiple environments are covered."]}
            profile = build_content_profile(slide)
            brief = _semantic_architecture(replace(program, content_profile=profile), slide, [])
            self.assertEqual({edge["relation"] for edge in brief["relations"]}, {"supported-by"})
            self.assertEqual(brief["connector_policy"]["eligible_relations"], [])
            self.assertNotIn("process-arrows", profile.representation_needs)
            for grammar in STYLE_GRAMMARS.values():
                ops = _active_operations(replace(program, content_profile=profile), grammar["operations"])
                self.assertFalse({"cross-zone-bridge", "directional-marker"} & {op["op"] for op in ops})

    def test_regeneration_feedback_includes_connector_geometry_failures(self):
        feedback = bams_repair_feedback({"status": "layout-invalid", "layout_validity": {
            "overflow_count": 0, "text_clip_count": 0,
            "connector_rule_collision_count": 1, "connector_occlusion_count": 1}})
        self.assertIn("1 arrow/separator conflicts", feedback)
        self.assertIn("1 hidden arrow endpoints", feedback)
        self.assertIn("including rule endpoints", feedback)

    def test_explicit_grounded_process_retains_directed_vocabulary(self):
        slide = {"slide_id": 2, "role": "method", "primary_proposition": "Retrieval feeds ranking.",
                 "must_cover_subset": ["Retrieval finds candidates.", "Ranking orders candidates."],
                 "evidence_relations": [{"from": "slide-2-evidence-0", "to": "slide-2-evidence-1",
                                         "relation": "feeds", "evidence_quote": "Retrieval feeds ranking."}]}
        profile = build_content_profile(slide)
        program = replace(self.build().programs[2], content_profile=profile)
        architecture = _semantic_architecture(program, slide, [])
        self.assertIn("process-arrows", profile.representation_needs)
        self.assertEqual(architecture["connector_policy"]["eligible_relations"], slide["evidence_relations"])
        self.assertEqual(_visual_encoding_plan(program, architecture)["primary_mark"], "grounded-relation-diagram")
        ops = _active_operations(program, [{"op": "directional-marker"}])
        self.assertEqual(ops[0]["op"], "directional-marker")
        slide["evidence_relations"][0]["evidence_quote"] = "An invented relationship not in the document."
        with self.assertRaisesRegex(ValueError, "verbatim quote"):
            build_content_profile(slide)
        slide["evidence_relations"][0]["to"] = "missing"
        with self.assertRaisesRegex(ValueError, "existing evidence IDs"):
            build_content_profile(slide)

    def test_planning_is_deterministic(self):
        first = {key: value.to_dict() for key, value in self.build().programs.items()}
        second = {key: value.to_dict() for key, value in self.build().programs.items()}
        self.assertEqual(first, second)

    def test_historical_asset_aliases_resolve_without_blueprint_rewrite(self):
        case_dir = self.asset_case("A016", "figure_01", ".png")
        _, figures = load_case(case_dir)
        self.assertIn("A016", figures)
        self.assertEqual(figures["A016"]["kind"], "figure")
        slides = resolve_slide_assets([
            {"slide_id": 1, "assigned_figure_id": "", "linked_evidence_ids": ["B1", "A016"]},
        ], figures)
        self.assertEqual(slides[0]["assigned_figure_id"], "A016")

    def test_case_loader_accepts_non_png_source_figures(self):
        case_dir = self.asset_case("A005", "fig_p1_img2", ".jpeg")
        _, figures = load_case(case_dir)
        self.assertTrue(figures["fig_p1_img2"]["path"].endswith(".jpeg"))
        self.assertTrue(figures["A005"]["path"].endswith(".jpeg"))

    def asset_case(self, alias, figure_id, extension):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        case_dir = Path(directory.name)
        figures = case_dir / "source_pack/figures"
        figures.mkdir(parents=True)
        (figures / f"{figure_id}{extension}").write_bytes(b"fixture")
        (figures / f"{figure_id}.json").write_text(json.dumps({"figure_id": figure_id, "caption": "Synthetic asset"}))
        (case_dir / "source_pack/source_store.json").write_text(json.dumps({
            "assets": [{"asset_id": alias, "image_path": f"figures/{figure_id}{extension}"}],
        }))
        return case_dir

    def test_deck_style_spine_keeps_visual_vocab_coherent(self):
        pipeline = self.build()
        allowed_sources = set(pipeline.deck_plan.style_spine["source_ids"])
        self.assertTrue(allowed_sources)
        for program in pipeline.programs.values():
            style_source = program.provenance["style_source_id"]
            self.assertIn(style_source, allowed_sources)
            for selection in program.vocab:
                if selection.kind in {"background", "typography", "separator", "decoration"}:
                    self.assertEqual(
                        self.library.items[selection.vocab_id].provenance.get("seed_id"),
                        style_source,
                    )

    def test_prompt_has_one_authority_and_explicit_realization_freedom(self):
        pipeline = self.build()
        prompt = pipeline.prompt_for(self.blueprint["slides"][4])
        self.assertEqual(prompt.count("## SLIDE DESIGN PROGRAM"), 1)
        self.assertIn("BOUNDED CREATIVE BRIEF", prompt)
        self.assertIn("Let the argument determine how the scaffold bends", prompt)
        self.assertIn("ADJUSTABLE BAMS COMPOSITION SCAFFOLD", prompt)
        self.assertIn('"adjustable_grid"', prompt)
        self.assertIn("resize, merge, span, or omit tracks", prompt)
        self.assertIn("EXECUTABLE DESIGN KERNEL", prompt)
        self.assertIn("Typed evidence architecture", prompt)
        self.assertIn('"relations"', prompt)
        self.assertIn("data-ink='connector'", prompt)
        self.assertIn("optional data-ink operations", prompt)
        self.assertIn("Keep the page canvas flat", prompt)
        self.assertNotIn("radial-gradient", prompt)
        self.assertNotIn("data-repeat=", prompt)
        self.assertNotIn('"content_representation"', prompt)
        self.assertNotIn('"layout_tendency"', prompt)
        self.assertNotIn('"focal_event"', prompt)
        self.assertIn('"massing"', prompt)
        self.assertNotIn("StyleSpec", prompt)
        self.assertNotIn("SCENE-NATIVE", prompt)
        self.assertNotIn("BAMS PNG", prompt)
        self.assertNotIn("image_url", prompt)
        self.assertNotIn("target_region", prompt)
        self.assertNotIn("x_pct", prompt)

    def test_prompt_density_is_evidence_based_not_component_count(self):
        pipeline = self.build()
        prompt = pipeline.prompt_for(self.blueprint["slides"][4], "")
        self.assertIn('"content_budget"', prompt)
        self.assertIn('"maximum_optional_source_details"', prompt)
        self.assertIn('"minimum_numeric_marks"', prompt)
        self.assertIn('"target_content_coverage"', prompt)
        self.assertIn('"functional_negative_space"', prompt)
        self.assertIn("Never increase density by reducing body scale", prompt)
        self.assertNotRegex(
            prompt,
            r"(?:minimum|required|max(?:imum)?)_(?:box|card|component|unit)_count",
        )

    def test_prompt_has_executable_cross_element_style_grammar(self):
        pipeline = self.build()
        prompt = pipeline.prompt_for(self.blueprint["slides"][4], "")
        self.assertIn("EXECUTABLE RELATIONAL STYLE GRAMMAR", prompt)
        self.assertIn('"active_operations"', prompt)
        self.assertIn('"priority": "dominant"', prompt)
        self.assertIn('"priority": "supporting"', prompt)
        self.assertIn('"maximum_dominant_filled_fields": 1', prompt)
        self.assertIn("data-style-role", prompt)
        self.assertIn("data-flow='open'", prompt)

    def test_style_operations_rotate_between_slides(self):
        pipeline = self.build()
        operation_sets = []
        for slide in self.blueprint["slides"][:4]:
            prompt = pipeline.prompt_for(slide, "")
            raw = re.search(
                r'"active_operations":\s*(\[.*?\])\s*,\s*"surface_policy"',
                prompt,
                re.DOTALL,
            ).group(1)
            operation_sets.append(tuple(item["op"] for item in json.loads(raw)))
        self.assertGreater(len(set(operation_sets)), 1)

    def test_instrument_does_not_invent_measurements_for_prose(self):
        program = self.build().programs[1]
        profile = replace(program.content_profile, role="context", numeric_count=0,
                          has_figure=False, item_count=3)
        program = replace(program, content_profile=profile)
        for slide_id in range(1, 9):
            selected = _active_operations(replace(program, slide_id=slide_id),
                                          STYLE_GRAMMARS["technical-instrument"]["operations"])
            self.assertEqual([item["op"] for item in selected], ["indexed-rail"])
            self.assertTrue(all("optional" in item["usage"] for item in selected))

    def test_source_figure_is_not_given_competing_chromatic_devices(self):
        program = self.build().programs[1]
        profile = replace(program.content_profile, has_figure=True, source_kind="figure",
                          item_count=4, title_length=60)
        program = replace(program, content_profile=profile)
        self.assertEqual(_active_operations(program, STYLE_GRAMMARS["chromatic-system"]["operations"]), [])
        # Native table charts still retain semantic multicolor capability.
        native = replace(program, content_profile=replace(profile, source_kind="table"))
        self.assertTrue(_active_operations(native, STYLE_GRAMMARS["chromatic-system"]["operations"]))

    def test_series_color_is_shared_across_mark_types(self):
        css = _design_kernel(self.build().programs[1], self.library)["css"]
        for role in ("bar", "dot", "series-line"):
            rule = re.search(r"\[data-chart-role='" + role + r"'\]\{([^}]+)\}", css).group(1)
            self.assertIn("var(--series-color,var(--accent-primary))", rule)
            self.assertNotIn("accent-signal", rule)
            self.assertNotIn("accent-tertiary", rule)

    def test_kernel_does_not_transplant_decorative_shadows_or_diamonds(self):
        for program in self.build().programs.values():
            css = _design_kernel(program, self.library)["css"]
            self.assertIn("text-shadow:none", css)
            self.assertNotIn("--kernel-display-shadow", css)
            self.assertNotIn("--kernel-shadow", css)
            self.assertNotIn("rotate(45deg)", css)
        for grammar in STYLE_GRAMMARS.values():
            self.assertNotIn("box-shadow", "\n".join(grammar["css"].values()))

    def test_prompt_binds_elements_and_color_to_evidence(self):
        prompt = self.build().prompt_for(self.blueprint["slides"][4])
        self.assertIn('"color_encoding"', prompt)
        self.assertIn('"element_binding"', prompt)
        self.assertIn("there is no minimum number", prompt)
        self.assertNotIn("Combine two or three", prompt)
        self.assertIn("not a requirement to use every hue", SYSTEM_PROMPT)

    def test_empty_table_does_not_require_a_fabricated_chart(self):
        program = self.build().programs[1]
        architecture = {"relations": [], "required_evidence": [
            {"id": "counts", "text": "2,272 turns and 8.59 hours per simulation"},
        ]}
        encoding = _visual_encoding_plan(program, architecture,
                                         {"kind": "table", "col_count": 0}, {"rows": []})
        self.assertFalse(encoding["required"])
        self.assertEqual(encoding["primary_mark"], "direct-labeled-metrics")
        self.assertEqual(encoding["numeric_groups"][0]["values"][0]["label"], "2,272")
        self.assertIn("unlike units", encoding["scale_rule"])

    def test_prompt_limits_panelization(self):
        prompt = self.build().prompt_for(self.blueprint["slides"][4], "")
        self.assertIn("Keep at least one substantial evidence sequence", prompt)
        self.assertIn("one dominant filled evidence field is the normal maximum", prompt)
        self.assertIn("never a paragraph-length thesis", prompt)

    def test_long_thesis_does_not_activate_filled_field(self):
        pipeline = ProgramPipeline(
            self.library,
            self.theme,
            self.blueprint["slides"],
            {},
            seed=42,
            style_archetype="chromatic-system",
        )
        slide = self.blueprint["slides"][-1]
        self.assertGreater(len(slide["primary_proposition"]), 105)
        prompt = pipeline.prompt_for(slide, "")
        raw = re.search(
            r'"active_operations":\s*(\[.*?\])\s*,\s*"surface_policy"',
            prompt,
            re.DOTALL,
        ).group(1)
        self.assertFalse(any(item.get("creates_surface") for item in json.loads(raw)))

    def test_separator_length_cannot_become_rule_thickness(self):
        pipeline = ProgramPipeline(
            self.library,
            self.library.resolve_theme("teal-cool", "medium"),
            self.blueprint["slides"],
            {},
            seed=7,
            dialect_id="teal-cool_medium",
        )
        prompt = pipeline.prompt_for(self.blueprint["slides"][6])
        match = re.search(r"--kernel-rule-weight:([^;]+)", prompt)
        self.assertIsNotNone(match)
        self.assertRegex(match.group(1), r"^[1-5](?:\.\d+)?px$")

    def test_style_archetype_is_explicit_and_independent_from_theme(self):
        pipeline = ProgramPipeline(
            self.library,
            self.library.resolve_theme("earth-warm", "light"),
            self.blueprint["slides"],
            {},
            seed=7,
            dialect_id="teal-cool_medium",
            style_archetype="display-architecture",
        )
        self.assertEqual(pipeline.deck_plan.theme_id, "earth-warm_light")
        self.assertEqual(pipeline.deck_plan.dialect_id, "teal-cool_medium")
        self.assertEqual(pipeline.deck_plan.style_archetype, "display-architecture")
        self.assertIn('"archetype": "display-architecture"', pipeline.prompt_for(self.blueprint["slides"][1]))

    def test_default_dialect_is_independent_from_theme(self):
        dark = ProgramPipeline(
            self.library,
            self.library.resolve_theme("blue-corporate", "dark"),
            self.blueprint["slides"],
            {},
            seed=23,
        )
        light = ProgramPipeline(
            self.library,
            self.library.resolve_theme("earth-warm", "light"),
            self.blueprint["slides"],
            {},
            seed=23,
        )
        self.assertEqual(dark.deck_plan.dialect_id, light.deck_plan.dialect_id)
        self.assertEqual(dark.deck_plan.style_archetype, light.deck_plan.style_archetype)

    def test_prompt_retrieves_slide_specific_supporting_evidence(self):
        pipeline = self.build()
        source = (
            "EEG signals vary across patients and are affected by noise and artifacts. "
            "A completely unrelated sentence discusses culinary recipes and ingredients. "
            "Noisy channel graphs can contain redundant edges that degrade representation learning."
        )
        prompt = pipeline.prompt_for(self.blueprint["slides"][1], source)
        self.assertIn('"optional_source_detail_reservoir"', prompt)
        self.assertIn("redundant edges", prompt)
        self.assertNotIn("culinary recipes", prompt)

    def test_supporting_evidence_deduplicates_near_duplicate_sentences(self):
        pipeline = self.build()
        repeated = (
            "The graph contains redundant edges and noisy connectivity across patients. "
            "The graph contains redundant edges and noisy connectivity across all patients. "
            "Graph errors degrade downstream representation learning and seizure detection."
        )
        prompt = pipeline.prompt_for(self.blueprint["slides"][1], repeated)
        self.assertEqual(prompt.count("The graph contains redundant edges"), 1)

    def test_runtime_does_not_reference_raw_seed_files(self):
        runtime_files = list((ROOT / "redeck_style").rglob("*.py"))
        source = "\n".join(path.read_text() for path in runtime_files)
        self.assertNotIn("style_seeds_v4", source)
        self.assertNotRegex(source, r"seed_\*\.html")
        self.assertNotIn("bams-vision", source.lower())

    def test_all_evidence_is_assigned_to_content_grammar(self):
        pipeline = self.build()
        for program in pipeline.programs.values():
            assigned = {
                evidence_id
                for selection in program.vocab if selection.kind == "content"
                for evidence_id in selection.parameters["evidence_ids"]
            }
            self.assertEqual(assigned, set(program.content_profile.evidence_ids))

    def test_source_table_remains_semantic_and_geometry_free(self):
        figures = {
            "tbl_p6_tbl2": {
                "kind": "table", "path": "/tmp/table.png", "caption": "Table 2",
                "row_count": 9, "col_count": 3,
                "rows": [["Judge", "0.1", "0.2"]] * 9,
            }
        }
        pipeline = self.build(figures)
        program = pipeline.programs[7]
        content = next(item for item in program.vocab if item.kind == "content")
        self.assertEqual(content.parameters["row_count"], 9)
        self.assertEqual(content.parameters["table_mode"], "claim-aligned-excerpt")
        self.assertEqual(program.composition.strategy, "data-monument")
        prompt = pipeline.prompt_for(self.blueprint["slides"][6])
        self.assertIn('"row_count": 9', prompt)
        self.assertIn('"Judge"', prompt)
        self.assertNotIn("<img src=", prompt)

    def test_dense_table_prompt_selects_claim_aligned_source_rows(self):
        figures = {
            "tbl_p6_tbl1": {
                "kind": "table", "path": "/tmp/table.png", "caption": "benchmark",
                "row_count": 10, "col_count": 4,
                "rows": [
                    ["Conventional methods", None, None, None],
                    ["Distance", "0.6508", "0.8225", "0.7049"],
                    ["Generative Graph Learner", "0.7351", "0.9039", "0.7625"],
                    ["LLM refiners", None, None, None],
                    ["GPT-4.1", "0.7792", "0.9236", "0.7933"],
                    ["GPT-5-mini", "0.7859", "0.9275", "0.8024"],
                    ["GPT-5", "0.7907", "0.9315", "0.8058"],
                    ["Other A", "0.74", "0.90", "0.77"],
                    ["Other B", "0.75", "0.91", "0.78"],
                    ["Other C", "0.76", "0.92", "0.79"],
                ],
            }
        }
        pipeline = self.build(figures)
        prompt = pipeline.prompt_for(self.blueprint["slides"][5])
        self.assertIn('"mode": "claim-aligned-excerpt"', prompt)
        self.assertIn('"cells": [\n        "Generative Graph Learner"', prompt)
        self.assertIn('"cells": [\n        "GPT-5"', prompt)
        self.assertNotIn('"Distance",\n        "0.6508"', prompt)
        self.assertIn("Display these rows, not the full source table", prompt)

    def test_table_prompt_includes_executable_chart_data(self):
        figures = {
            "tbl_p6_tbl2": {
                "kind": "table", "path": "/tmp/table.png",
                "caption": "Table 2: Graph-level reasoning characteristics of different LLMs.",
                "row_count": 4, "col_count": 3,
                "rows": [
                    ["Mistral 7B", "0.4213", "0.0576"],
                    ["GPT-4o", "0.3826", "0.0314"],
                    ["GPT-5", "0.3741", "0.0265"],
                ],
            }
        }
        pipeline = self.build(figures)
        prompt = pipeline.prompt_for(self.blueprint["slides"][6])
        self.assertIn("Executable visual-encoding plan", prompt)
        self.assertIn('"primary_mark": "aligned-dot-plot"', prompt)
        self.assertIn('"series": "Graph sparsity"', prompt)
        self.assertIn('"label": "0.4213"', prompt)
        self.assertIn('"plot_percent_of_one": 42.13', prompt)
        self.assertIn("Default to the chart with direct exact-value labels", prompt)
        self.assertIn("never repeat the same rows and measures", prompt)

    def test_method_prompt_does_not_invent_a_flow_from_role(self):
        pipeline = self.build()
        prompt = pipeline.prompt_for(self.blueprint["slides"][3])
        self.assertIn('"primary_mark": "annotated-evidence-field"', prompt)
        self.assertNotIn('"decision-funnel"', prompt)
        self.assertIn('"required": false', prompt)
        self.assertIn("When `required` is true", prompt)

    def test_source_figure_is_primary_without_fixed_region(self):
        figures = {"fig_p7_fig4": {"kind": "figure", "path": "/tmp/figure.png"}}
        pipeline = self.build(figures)
        program = pipeline.programs[9]
        content = next(item for item in program.vocab if item.kind == "content")
        self.assertEqual(program.composition.strategy, "figure-as-scene")
        self.assertEqual(content.parameters["asset_priority"], "primary-evidence")
        self.assertEqual(content.parameters["suggested_canvas_share"], "35-60%")
        self.assertNotIn("asset_region", content.parameters)

    def test_figure_prompt_exposes_intrinsic_aspect_ratio(self):
        figures = {
            "fig_p7_fig4": {
                "kind": "figure", "path": "/tmp/figure.png",
                "width": 2870, "height": 490, "caption": "wide pipeline",
            }
        }
        pipeline = self.build(figures)
        prompt = pipeline.prompt_for(self.blueprint["slides"][8])
        self.assertIn("2870×490px", prompt)
        self.assertIn("aspect ratio 5.86:1", prompt)
        self.assertIn("do not build a tall frame", prompt)

    def test_anchor_is_inspiration_not_geometry_contract(self):
        pipeline = self.build()
        slide_five = pipeline.programs[5]
        slide_seven = pipeline.programs[7]
        self.assertEqual(slide_five.composition.layout_inspiration_id, "layout.seed_075")
        self.assertEqual(slide_seven.composition.layout_inspiration_id, "layout.seed_217")
        for program in (slide_five, slide_seven):
            for selection in program.vocab:
                self.assertNotIn("box_pct", selection.parameters)
                self.assertNotIn("target_region", selection.parameters)

    def test_evaluation_composition_centers_the_controlled_variable(self):
        program = self.build().programs[5]
        self.assertEqual(program.composition.strategy, "controlled-variable-stage")
        self.assertEqual(program.composition.focal_event, "changing-variable")
        self.assertEqual(program.composition.tension, "asymmetric fulcrum")

    def test_blueprint_resolution_uses_explicit_test_fixture(self):
        fixture = ROOT / "tests" / "fixtures" / "planner_blueprint.json"
        path, payload = resolve_blueprint("planner-fixture", explicit_path=fixture)
        self.assertEqual(path, fixture.resolve())
        self.assertTrue(all(slide.get("must_cover_subset") for slide in payload["slides"]))

    def test_grouped_response_preserves_document_order(self):
        response = (
            "<!doctype html><html><body>one</body></html>\n"
            "<!-- SLIDE_SEPARATOR -->\n"
            "<!doctype html><html><body>two</body></html>"
        )
        documents = extract_html_documents(response, 2)
        self.assertEqual(len(documents), 2)
        self.assertIn("one", documents[0])
        self.assertIn("two", documents[1])

    def test_grouped_prompt_includes_human_feedback(self):
        pipeline = self.build()
        prompt = build_group_prompt(
            pipeline,
            self.blueprint["slides"][1:3],
            visual_feedback={"2": "Increase explanatory density without shrinking type."},
        )
        self.assertIn("VISUAL REPAIR FEEDBACK", prompt)
        self.assertIn("Slide 2: Increase explanatory density", prompt)

    def test_system_prompt_guards_wrapping_heading_geometry(self):
        self.assertIn("HEADING GEOMETRY", SYSTEM_PROMPT)
        self.assertIn("normal document flow", SYSTEM_PROMPT)
        self.assertIn("36–44px", SYSTEM_PROMPT)
        self.assertIn("TEXT COLLISIONS", SYSTEM_PROMPT)

    def test_system_prompt_guards_source_figure_geometry(self):
        self.assertIn("SOURCE FIGURE GEOMETRY", SYSTEM_PROMPT)
        self.assertIn("figure { margin: 0 }", SYSTEM_PROMPT)

    def test_system_prompt_preserves_readable_type_and_functional_whitespace(self):
        self.assertIn("body copy must be at least 15px", SYSTEM_PROMPT)
        self.assertIn("50–72% of the usable canvas", SYSTEM_PROMPT)
        self.assertIn("18–32% functional negative space", SYSTEM_PROMPT)
        self.assertIn("express each fact once", SYSTEM_PROMPT)

    def test_system_prompt_rejects_decorative_canvas_gradients(self):
        self.assertIn("SURFACE DISCIPLINE", SYSTEM_PROMPT)
        self.assertIn("flat `var(--surface-canvas)`", SYSTEM_PROMPT)
        self.assertNotIn("background:linear-gradient(...)", SYSTEM_PROMPT)

    def test_repair_feedback_names_surface_gradient_violations(self):
        feedback = bams_repair_feedback({
            "status": "layout-invalid",
            "layout_validity": {
                "overflow_count": 0,
                "text_clip_count": 0,
                "text_collision_count": 2,
                "text_collision_roles": ["h1 ↔ p"],
                "overflow_roles": [],
                "clipped_roles": [],
                "gradient_violation_count": 1,
                "gradient_roles": ["slide"],
            },
        })
        self.assertIn("Remove decorative gradients from: slide", feedback)
        self.assertIn("2 text collisions", feedback)
        self.assertIn("h1 ↔ p", feedback)

    def test_long_content_title_gets_compact_kernel_size(self):
        prompt = self.build().prompt_for(self.blueprint["slides"][1])
        self.assertIn("--kernel-title-size:38px", prompt)

    def test_long_title_slide_obeys_program_title_ceiling(self):
        prompt = self.build().prompt_for(self.blueprint["slides"][0])
        self.assertIn("--kernel-title-size:42px", prompt)
        self.assertIn("hard ceiling for the main heading", prompt)


if __name__ == "__main__":
    unittest.main()
