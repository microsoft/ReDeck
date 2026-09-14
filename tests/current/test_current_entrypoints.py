import argparse
import importlib
import re
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from redeck_style import cli, compat, paths
from scripts import codegen, generate, repair


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "examples/validation/content_repair_smoke"
README_COMMANDS = [
    shlex.split(line.strip())[1:]
    for block in re.findall(r"```bash\n(.*?)```", (ROOT / "README.md").read_text(), re.DOTALL)
    for line in block.replace("\\\n", " ").splitlines()
    if line.strip().startswith("redeck ")
]


@pytest.mark.parametrize("command", README_COMMANDS)
def test_readme_commands_match_current_argument_parsers(command, monkeypatch):
    class ParsedArguments(Exception):
        pass

    parse_args = argparse.ArgumentParser.parse_args

    def stop_after_parsing(parser, *args, **kwargs):
        parsed = parse_args(parser, *args, **kwargs)
        if hasattr(parsed, "api"):
            assert parsed.api == "openai"
        raise ParsedArguments

    module = importlib.import_module(cli.COMMANDS[command[0]])
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", stop_after_parsing)
    with pytest.raises(ParsedArguments):
        module.main(command[1:])


@pytest.mark.parametrize("command", [command for command in README_COMMANDS
                                     if command[0] == "generate" and "--pdf" not in command])
def test_readme_generation_examples_build_prompts_without_api(command, tmp_path, monkeypatch):
    monkeypatch.setattr(codegen, "get_client", lambda *args: pytest.fail("Unexpected model call"))
    arguments = list(command[1:])
    output = tmp_path / "generation"
    for option, value in (("--case", FIXTURE.name), ("--cases-root", str(FIXTURE.parent)),
                          ("--blueprint", str(FIXTURE / "blueprint.json")), ("--out", str(output))):
        if option in arguments:
            arguments[arguments.index(option) + 1] = value
        else:
            arguments.extend([option, value])
    if "--repair" in arguments:
        arguments.remove("--repair")
    if "--dry-run" not in arguments:
        arguments.append("--dry-run")
    generate.main(arguments)
    assert (output / "run_manifest.json").is_file()
    assert (output / "prompts/system.txt").is_file()
    assert list((output / "prompts").glob("slide_*.txt"))


def test_bundled_probes_and_local_cases_are_defaults(monkeypatch, tmp_path):
    for name in ("REDECK_PROBE_ROOT", "REDECK_LEGACY_ROOT", "REDECK_CASES_ROOT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.resolve_probe_root() == ROOT
    assert paths.resolve_cases_root() == tmp_path / "cases"
    from app.modules.evaluators.probe_runner import ProbeRunner
    assert ROOT in Path(sys.modules[ProbeRunner.__module__].__file__).parents


def test_bundled_example_source_context_is_independent_of_working_directory(tmp_path, monkeypatch):
    from redeck_style.evaluation.coordinator import source_context

    monkeypatch.chdir(tmp_path)
    context = source_context(FIXTURE, ROOT)
    assert context["source_dir"] == str(FIXTURE / "source_pack")
    assert context["blueprint"]["total_slides"] == 1


@pytest.mark.parametrize("command", cli.COMMANDS)
def test_cli_dispatches_to_one_current_implementation(monkeypatch, command):
    calls = []
    monkeypatch.setattr(cli.importlib, "import_module", lambda name: SimpleNamespace(main=lambda args: calls.append((name, args))))
    cli.main([command, "--help"])
    assert calls == [(cli.COMMANDS[command], ["--help"])]


def test_compat_loop_translates_to_shared_budget(monkeypatch):
    calls = []
    monkeypatch.setattr(compat, "main", calls.append)
    compat.run("repair", ["--dir", "slides", "--max-turns", "4", "--spatial-only"])
    assert calls == [["repair", "--dir", "slides", "--attempts", "4", "--probe-routes", "spatial", "--content-repair", "off"]]


def test_old_experiment_configs_are_not_silently_ignored():
    with pytest.raises(SystemExit, match="Historical"):
        compat.run("generate", ["--configs", "old_ablation"])


def test_repair_alias_has_one_six_candidate_budget(tmp_path, monkeypatch):
    source = tmp_path / "example.html"
    source.write_text("<p>Synthetic fixture</p>")
    calls = []
    monkeypatch.setattr(repair, "run_repair_jobs", lambda *args, **kwargs: calls.append(args) or [])
    repair.main(["--dir", str(tmp_path), "-o", str(tmp_path / "repair"), "--probe-routes", "spatial"])
    assert len(calls) == 1 and calls[0][3] == 6
    assert calls[0][0][0]["source"] == str(source)


@pytest.mark.parametrize("budget", ["0", "7"])
def test_repair_rejects_out_of_contract_budgets(budget):
    with pytest.raises(SystemExit):
        repair.main(["missing.html", "-o", "unused", "--attempts", budget])


def test_dry_generation_uses_bundled_library_without_api(tmp_path, monkeypatch):
    monkeypatch.setattr(codegen, "get_client", lambda *args: pytest.fail("Dry run must not call a model"))
    output = tmp_path / "generation"
    generate.main(["--case", FIXTURE.name, "--cases-root", str(FIXTURE.parent), "--blueprint", str(FIXTURE / "blueprint.json"),
                   "--out", str(output), "--dry-run"])
    assert (output / "run_manifest.json").is_file()
    assert list(output.rglob("*.prompt.txt")) or list(output.rglob("*.txt"))


def test_generation_and_repair_share_probe_configuration(tmp_path, monkeypatch):
    generation_calls, repair_calls = [], []
    monkeypatch.setattr(codegen, "main", generation_calls.append)
    monkeypatch.setattr(repair, "main", repair_calls.append)
    generate.main(["--case", FIXTURE.name, "--cases-root", str(FIXTURE.parent), "--blueprint", str(FIXTURE / "blueprint.json"), "--out", str(tmp_path / "run"),
                   "--repair", "--judge-model", "fixture-judge", "--probe-execution", "serial", "--probe-routes", "spatial",
                   "--content-workers", "1", "--probe-cache", "off"])
    for arguments in [generation_calls[0], repair_calls[0]]:
        assert arguments[arguments.index("--judge-mode") + 1] == "off"
        assert arguments[arguments.index("--judge-model") + 1] == "fixture-judge"
        assert arguments[arguments.index("--content-workers") + 1] == "1"
        assert arguments[arguments.index("--probe-cache") + 1] == "off"
    assert repair_calls[0][-2:] == ["--probe-routes", "spatial"]


def test_unknown_design_flags_fail_before_planning(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "prepare_blueprint", lambda *args: pytest.fail("Invalid CLI must not call the planner"))
    with pytest.raises(SystemExit):
        generate.main(["--case", FIXTURE.name, "--out", str(tmp_path / "run"), "--unknown-design-flag"])


def test_planning_uses_shared_transport_and_validates_json(tmp_path, monkeypatch):
    from app.schemas.blueprint import DeckBlueprint

    monkeypatch.setattr(codegen, "get_client", lambda api: object())
    monkeypatch.setattr(codegen, "call_llm", lambda *args, **kwargs: ((FIXTURE / "blueprint.json").read_text(), 10, 20, 0.1))
    blueprint = generate.PlanningClient("local", tmp_path).call_json(
        system_prompt="Plan", user_content="Source", response_model=DeckBlueprint, model="fixture", max_tokens=1000,
    )
    assert len(blueprint.slides) == 1


def test_failed_planning_cannot_silently_generate_a_skeleton(tmp_path, monkeypatch):
    monkeypatch.setattr(codegen, "get_client", lambda api: object())

    def fail(*args, **kwargs):
        raise RuntimeError("Planner unavailable")

    monkeypatch.setattr(codegen, "call_llm", fail)
    with pytest.raises(RuntimeError, match="Planner unavailable"):
        generate.prepare_blueprint(FIXTURE.name, FIXTURE.parent, tmp_path / "planning", "fixture", "local", [1, 1])


def test_pdf_preparation_uses_existing_extractor_and_current_codegen(tmp_path, monkeypatch):
    import fitz

    pdf = tmp_path / "source.pdf"
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "Synthetic validation: 48 correct predictions among 100 examples. Accuracy is 48%.")
        document.save(pdf)
    monkeypatch.setattr(codegen, "get_client", lambda api: object())
    monkeypatch.setattr(codegen, "call_llm", lambda *args, **kwargs: ((FIXTURE / "blueprint.json").read_text(), 10, 20, 0.1))
    calls = []
    monkeypatch.setattr(codegen, "main", calls.append)
    output = tmp_path / "run"
    generate.main(["--pdf", str(pdf), "--case", "pdf_fixture", "--cases-root", str(tmp_path / "cases"),
                   "--pages", "1", "--out", str(output)])
    assert "48 correct predictions" in (tmp_path / "cases/pdf_fixture/source_pack/paper_full.md").read_text()
    brief = (tmp_path / "cases/pdf_fixture/task_brief.md").read_text()
    assert "HTML/CSS" in brief and "PPTX" not in brief
    assert (output / "planning/deck_blueprint.json").is_file()
    assert len(calls) == 1
