import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from redeck_style.library import RuntimeLibrary
from redeck_style.pipeline import ProgramPipeline
from redeck_style.validation.source_assets import audit_source_assets
from scripts import codegen


@pytest.fixture(scope="module")
def library():
    return RuntimeLibrary()


@pytest.fixture
def materials():
    slides = [
        {"slide_id": 1, "role": "results", "primary_proposition": "Method B improves the measured result",
         "must_cover_subset": ["Method A scores 0.6; Method B scores 0.8."], "assigned_figure_id": "table1"},
        {"slide_id": 2, "role": "method", "primary_proposition": "The source shows the architecture",
         "must_cover_subset": ["The architecture has two stages."], "assigned_figure_id": "figure1"},
        {"slide_id": 3, "role": "conclusion", "primary_proposition": "The result has a limited scope",
         "must_cover_subset": ["Only the supplied comparison is supported."]},
    ]
    assets = {
        "table1": {"kind": "table", "path": "/tmp/source-table.png", "caption": "Measured results",
                   "width": 800, "height": 400, "row_count": 2, "col_count": 2,
                   "rows": [["Method A", "0.6"], ["Method B", "0.8"]]},
        "figure1": {"kind": "figure", "path": "/tmp/source-figure.png", "width": 800, "height": 400},
    }
    return slides, assets


def build(library, materials, **options):
    slides, assets = materials
    return ProgramPipeline(library, library.resolve_theme("gray-mono", "light"), slides, assets, **options)


def test_auto_preserves_existing_default_and_records_policy(library, materials):
    default = build(library, materials)
    explicit = build(library, materials, asset_mode="auto")
    for slide in materials[0]:
        assert default.programs[slide["slide_id"]].to_dict() == explicit.programs[slide["slide_id"]].to_dict()
        assert default.prompt_for(slide) == explicit.prompt_for(slide)
    assert default.asset_presentations[1]["mode"] == "auto"
    assert default.asset_presentations[2]["mode"] == "preserve"
    assert default.asset_presentations[3]["mode"] == "none"
    assert "Default to the chart with direct exact-value labels" in default.prompt_for(materials[0][0])


@pytest.mark.parametrize("mode,mark", [("preserve", "source-figure"), ("table", "data-table"), ("chart", "grouped-bar-chart")])
def test_forced_mode_changes_plan_and_prompt(library, materials, mode, mark):
    pipeline = build(library, materials, asset_policy={"table1": mode})
    program = pipeline.programs[1]
    prompt = pipeline.prompt_for(materials[0][0])
    assert program.content_profile.asset_mode == mode
    assert f'"primary_mark": "{mark}"' in prompt
    assert "Default to the chart" not in prompt
    content = next(item for item in program.vocab if item.kind == "content")
    assert content.parameters["asset_mode"] == mode
    if mode == "preserve":
        assert '<img src="/tmp/source-table.png"' in prompt
        assert "screenshot is not an input" not in prompt
        assert "Display table data:" not in prompt
        assert "do not redraw or crop its data" in prompt
        assert program.composition.strategy == "figure-as-scene"
        assert "table" not in program.composition.required_roles
        assert "table_mode" not in content.parameters
    else:
        assert '<img src="/tmp/source-table.png"' not in prompt
        assert "screenshot is not an input" in prompt
        assert "0.6" in prompt and "0.8" in prompt
        assert program.composition.focal_role == mode
        if mode == "chart":
            assert "table" not in program.composition.required_roles
            assert "supporting table field" not in prompt


def test_per_asset_overrides_support_mixed_deck(library, materials):
    pipeline = build(library, materials, asset_mode="preserve", asset_policy={"table1": "chart"})
    assert pipeline.asset_presentations[1]["policy_source"] == "asset-override"
    assert pipeline.asset_presentations[1]["requested_mode"] == "chart"
    assert pipeline.asset_presentations[2]["mode"] == "preserve"
    assert pipeline.asset_presentations[3]["mode"] == "none"
    assert '"primary_mark": "grouped-bar-chart"' in pipeline.prompt_for(materials[0][0])
    assert '<img src="/tmp/source-figure.png"' in pipeline.prompt_for(materials[0][1])


def test_selected_slides_only_receive_requested_mode(library, materials):
    pipeline = build(library, materials, asset_mode="chart", selected_slide_ids=[1])
    assert pipeline.programs[1].content_profile.asset_mode == "chart"
    assert pipeline.asset_presentations[2]["selected"] is False
    assert pipeline.programs[2].content_profile.asset_mode == "preserve"


@pytest.mark.parametrize("mode", ["table", "chart"])
def test_cannot_reconstruct_figure_without_table_data(library, materials, mode):
    with pytest.raises(ValueError, match="requires an extracted table"):
        build(library, materials, asset_policy={"figure1": mode})


@pytest.mark.parametrize("mode", ["table", "chart"])
def test_forced_data_modes_require_source_rows(library, materials, mode):
    materials[1]["table1"]["rows"] = []
    with pytest.raises(ValueError, match="requires extracted source rows"):
        build(library, materials, asset_policy={"table1": mode})


def test_forced_chart_rejects_unplottable_selected_data(library, materials):
    materials[1]["table1"]["rows"] = [["Method A", "qualitative"], ["Method B", "qualitative"]]
    pipeline = build(library, materials, asset_policy={"table1": "chart"})
    with pytest.raises(ValueError, match="chart mode requires plottable"):
        pipeline.prompt_for(materials[0][0])
    table = build(library, materials, asset_policy={"table1": "table"})
    assert '"primary_mark": "data-table"' in table.prompt_for(materials[0][0])


@pytest.mark.parametrize("policy,error", [([], "must be an object"), ({"typo": "auto"}, "Unknown asset ID"),
                                         ({"table1": "raster"}, "Unsupported asset mode"),
                                         ({"table1": ["chart"]}, "Unsupported asset mode")])
def test_invalid_policy_is_not_silently_ignored(library, materials, policy, error):
    with pytest.raises(ValueError, match=error):
        build(library, materials, asset_policy=policy)


def test_preserve_table_inspects_image_even_with_valid_rows(library, materials, tmp_path):
    pipeline = build(library, materials, asset_policy={"table1": "preserve"})
    slides, assets = materials
    assets["table1"]["path"] = str(tmp_path / "missing.png")
    result = audit_source_assets(slides[:1], assets, pipeline.asset_presentations)
    assert result[0]["issues"] == ["unavailable-image"]
    image = tmp_path / "table.png"
    Image.new("RGB", (800, 400), "white").save(image)
    assets["table1"]["path"] = str(image)
    assert audit_source_assets(slides[:1], assets, pipeline.asset_presentations)[0]["issues"] == []
    image.write_bytes(b"invalid image")
    assert audit_source_assets(slides[:1], assets, pipeline.asset_presentations)[0]["issues"] == ["unreadable-image"]
    assert audit_source_assets(slides[:1], assets) == []


def prepare_cli(monkeypatch, tmp_path, materials):
    slides, assets = materials
    (tmp_path / "example" / "source_pack").mkdir(parents=True)
    (tmp_path / "example" / "source_pack" / "paper_full.md").write_text("Grounded source evidence.")
    monkeypatch.setattr(codegen, "load_case", lambda directory: ("", assets))
    monkeypatch.setattr(codegen, "resolve_blueprint", lambda *args: (Path("example.json"), {"slides": slides}))
    monkeypatch.setattr(codegen, "get_client", lambda *args: pytest.fail("Preflight must not contact a model"))
    return ["codegen.py", "--case", "example", "--cases-root", str(tmp_path), "--out", str(tmp_path / "run")]


def test_cli_dry_run_writes_all_selected_prompts_and_policy(monkeypatch, tmp_path, materials):
    command = prepare_cli(monkeypatch, tmp_path, materials)
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"table1": "table"}))
    monkeypatch.setattr(sys, "argv", command + ["--dry-run", "--asset-mode", "preserve", "--asset-policy", str(policy), "--slides", "1,3"])
    codegen.main()
    output = tmp_path / "run"
    manifest = json.loads((output / "run_manifest.json").read_text())
    assert manifest["asset_mode"] == "preserve"
    assert manifest["asset_policy"] == {"table1": "table"}
    assert '"primary_mark": "data-table"' in (output / "prompts/slide_01.txt").read_text()
    assert (output / "prompts/slide_03.txt").exists()
    assert not (output / "prompts/slide_02.txt").exists()
    presentations = json.loads((output / "asset_presentation.json").read_text())
    assert presentations["1"]["mode"] == "table"
    assert presentations["2"]["selected"] is False


def test_cli_checks_every_selected_chart_before_any_model_call(monkeypatch, tmp_path, materials):
    materials[0][1]["assigned_figure_id"] = "table2"
    materials[1]["table2"] = {**materials[1]["table1"], "rows": [["Method A", "qualitative"]]}
    command = prepare_cli(monkeypatch, tmp_path, materials)
    monkeypatch.setattr(sys, "argv", command + ["--asset-mode", "chart"])
    with pytest.raises(SystemExit) as error:
        codegen.main()
    assert error.value.code == 2
    assert not list((tmp_path / "run/slide_code").glob("*.html"))


def test_cli_preserve_missing_table_image_fails_before_model(monkeypatch, tmp_path, materials):
    materials[1]["table1"]["path"] = ""
    command = prepare_cli(monkeypatch, tmp_path, materials)
    monkeypatch.setattr(sys, "argv", command + ["--asset-mode", "preserve", "--slides", "1"])
    with pytest.raises(SystemExit, match="Source asset preflight failed"):
        codegen.main()
    audit = json.loads((tmp_path / "run/source_asset_audit.json").read_text())
    assert audit[0]["asset_id"] == "table1" and audit[0]["issues"] == ["unavailable-image"]


@pytest.mark.parametrize("policy", [None, [], "preserve"])
def test_cli_policy_file_requires_object(monkeypatch, tmp_path, materials, policy):
    command = prepare_cli(monkeypatch, tmp_path, materials)
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps(policy))
    monkeypatch.setattr(sys, "argv", command + ["--asset-policy", str(policy_file), "--dry-run"])
    with pytest.raises(SystemExit) as error:
        codegen.main()
    assert error.value.code == 2
