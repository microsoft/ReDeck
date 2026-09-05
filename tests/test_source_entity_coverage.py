"""Source coverage must not depend on held-out evaluation answers."""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.redeck import dispatcher


SOURCE_TEXT = (
    "Source Alpha is the proposed method for learning useful representations. "
    "Source Alpha is evaluated across several tasks with consistent results. "
    "Existing Method is the baseline. Existing Method is already described."
)


def collect_coverage_issues(case_dir, source_store):
    worker = dispatcher.ReDeckWorker(MagicMock())
    compiler = SimpleNamespace(
        slide_codes={1: "<p>Existing Method is the baseline.</p>"},
    )
    slide_issues = {}
    worker._inject_entity_coverage_issues(
        slide_issues,
        compiler,
        source_store,
        [SimpleNamespace(slide_id=1)],
        str(case_dir),
    )
    worker.llm.call_text.assert_not_called()
    return [issue for issues in slide_issues.values() for issue in issues]


@pytest.mark.parametrize("case_name", ["003", "pdf_case_003", "db_003", "custom_case"])
@pytest.mark.parametrize("has_source", [False, True])
def test_coverage_never_accesses_quizbank(tmp_path, monkeypatch, case_name, has_source):
    repository = tmp_path / "repository"
    case_dir = repository / "cases" / case_name
    case_dir.mkdir(parents=True)
    benchmark_dir = repository / "benchmarks"
    quiz = {
        "questions": [{
            "question_id": "held_out_question",
            "gold_answer": "Sentinel Quasar is the correct answer.",
        }],
    }
    for quiz_case in {"003", case_name}:
        quiz_path = benchmark_dir / "quizbank" / quiz_case / "quiz.json"
        quiz_path.parent.mkdir(parents=True, exist_ok=True)
        quiz_path.write_text(json.dumps(quiz), encoding="utf-8")

    monkeypatch.setattr(
        dispatcher, "__file__",
        str(repository / "app" / "modules" / "redeck" / "dispatcher.py"),
    )
    original_exists = Path.exists
    original_open = Path.open
    accesses = []

    def record_exists(path):
        if path.is_relative_to(benchmark_dir):
            accesses.append(path)
        return original_exists(path)

    def record_open(path, *args, **kwargs):
        if path.is_relative_to(benchmark_dir):
            accesses.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", record_exists)
    monkeypatch.setattr(Path, "open", record_open)
    source_store = SimpleNamespace(_raw={"anchored_doc": SOURCE_TEXT}) if has_source else None

    issues = collect_coverage_issues(case_dir, source_store)

    assert accesses == [], "Source coverage accessed held-out benchmark artifacts"
    assert [issue.fix_detail.correct_content for issue in issues] == (
        ["Source Alpha"] if has_source else []
    )
    assert all(issue.issue_id.startswith("C4_src_") for issue in issues)


@pytest.mark.parametrize("source_kind", ["anchored_doc", "atomic_blocks", "paper_file"])
def test_source_coverage_preserves_supported_inputs(tmp_path, source_kind):
    if source_kind == "anchored_doc":
        source_store = SimpleNamespace(_raw={"anchored_doc": SOURCE_TEXT})
    elif source_kind == "atomic_blocks":
        source_store = SimpleNamespace(_raw={"atomic_blocks": [{"content": SOURCE_TEXT}]})
    else:
        source_store = None
        source_dir = tmp_path / "source_pack"
        source_dir.mkdir()
        (source_dir / "paper_full.md").write_text(SOURCE_TEXT, encoding="utf-8")

    issues = collect_coverage_issues(tmp_path, source_store)

    assert len(issues) == 1
    assert issues[0].fix_detail.correct_content == "Source Alpha"
    assert issues[0].affected_slides == [1]
    assert issues[0].issue_type == "missing_entity"
    assert "2 times" in issues[0].evidence.description


def test_source_coverage_limits_and_deduplicates_issues(tmp_path):
    entities = [
        "Source Alpha", "Source Beta", "Source Gamma", "Source Delta",
        "Source Epsilon", "Source Zeta", "Source Eta", "Source Theta",
        "Source Iota", "Source Kappa",
    ]
    source_text = " ".join(
        f"{entity} is described in the paper. {entity} is evaluated in detail."
        for entity in entities
    )

    issues = collect_coverage_issues(
        tmp_path, SimpleNamespace(_raw={"anchored_doc": source_text}),
    )

    assert len(issues) == 8
    assert len({issue.fix_detail.correct_content for issue in issues}) == 8
    assert all(issue.fix_detail.correct_content in entities for issue in issues)


def test_runtime_has_no_held_out_answer_dependencies():
    runtime_dir = Path(__file__).resolve().parents[1] / "app"
    forbidden = {
        "quizbank", "gold_answer", "correct_choice", "answer_key",
        "oracle_scores.json", "oracle_answers.json", "deck_scores.json",
        "deck_answers.json", "quizdeck_eval",
    }
    violations = []
    for path in sorted(runtime_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for marker in forbidden:
                    if marker in node.value.lower():
                        violations.append(f"{path.relative_to(runtime_dir)}:{node.lineno}: {marker}")

    assert violations == [], "Runtime references held-out answers:\n" + "\n".join(violations)
