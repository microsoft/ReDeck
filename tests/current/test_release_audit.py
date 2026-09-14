import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_cli_does_not_label_style_advisories_as_hard_defects():
    from scripts.repair import format_issue_transition

    text = format_issue_transition({
        "initial_issue_counts": {"repair_blocking": 70, "style_advisory": 2, "raw_total": 72},
        "final_issue_counts": {"repair_blocking": 0, "style_advisory": 2, "raw_total": 2},
    })
    assert text == "blockers 70 -> 0; style advisories 2 -> 2; raw findings 72 -> 2"


def test_current_import_boundary_excludes_historical_repair_and_templates():
    code = '''
import sys
from scripts import generate, repair, content_probe_worker
from app.modules.evaluators.probe_runner import ProbeRunner
for name in sys.modules:
    assert not name.startswith(("app.orchestrator", "app.backends", "app.modules.redeck", "app.style_patterns",
                                "app.modules.evaluators.base_judge", "app.modules.evaluators.visual_judge")), name
'''
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, text=True)


def test_wheel_uses_explicit_package_data_not_sdist_archive_manifest():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    setuptools = project["tool"]["setuptools"]
    assert setuptools["include-package-data"] is False
    assert "redeck-legacy" not in project["project"]["scripts"]
    assert "prompts/**/*.md" in setuptools["package-data"]["app"]
    assert "prompts/probes/probe_registry.json" in setuptools["package-data"]["app"]
    assert "artifacts/*.json" in setuptools["package-data"]["pattern_library"]
    assert not any(dependency.startswith("python-pptx") for dependency in project["project"]["dependencies"])


def test_release_omits_retired_engines_and_experiment_tools():
    removed = ("app/legacy_main.py", "app/orchestrator", "app/backends", "app/modules/redeck",
               "app/modules/repairs", "app/style_patterns", "scripts/legacy",
               "configs", "README.paper.md", "scripts/run_validation_matrix.py",
               "scripts/repair_suite.py", "examples/blueprints", "examples/visual_feedback",
               "app/modules/evaluators/base_judge.py", "app/modules/evaluators/visual_judge.py",
               "app/prompts/evaluator/visual_judge.system.md",
               "app/prompts/probes/B19_whitespace_asymmetry.md", "app/prompts/probes/probe_translations.zh.json",
               "app/schemas/compile_manifest.py", "app/schemas/eval_unit.py", "app/schemas/render_result.py",
               "app/schemas/repair_unit.py", "app/schemas/turn_summary.py", "app/schemas/verify_report.py",
               "demo/video-player.js", "redeck-video/eslint.config.mjs")
    assert all(not (ROOT / name).exists() for name in removed)
    assert not list((ROOT / "scripts").glob("build_*gallery.py"))


def test_case_id_does_not_load_a_bundled_experimental_blueprint(tmp_path):
    from scripts.codegen import resolve_blueprint

    with pytest.raises(FileNotFoundError, match="supply --blueprint"):
        resolve_blueprint("db_003", probe_root=tmp_path)


@pytest.mark.parametrize("relative", [".venv/bin/python", "local.pfx", "local.p12", "local.jks", "local.keystore", "offline/seed.html"])
def test_sensitive_and_offline_inputs_are_ignored(tmp_path, relative):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text((ROOT / ".gitignore").read_text())
    result = subprocess.run(["git", "-c", "core.excludesfile=/dev/null", "check-ignore", "--no-index", relative],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, relative
