import ast
import io
import re
import tokenize
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def runtime_sources():
    return sorted(path for directory in ("app", "redeck_style", "scripts")
                  for path in (ROOT / directory).rglob("*.py"))


def test_runtime_has_no_retired_answer_bank_or_keyword_stuffing_hooks():
    forbidden = {"gold_answer", "quizbank", "quiz.json", "quiz_path", "quiz_data", "quiz_case_id",
                 "unique_quiz_missing", "_inject_entity_coverage_issues", "_find_best_slide_for_entity"}
    findings = []
    for path in runtime_sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Name):
                value = node.id
            elif isinstance(node, ast.Attribute):
                value = node.attr
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                value = node.name
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
            else:
                continue
            if value in forbidden or value.startswith(("C4_quiz_", "C4_src_")):
                findings.append((str(path.relative_to(ROOT)), node.lineno, value))
    assert not findings


def test_runtime_has_no_debugger_calls_or_temporary_comment_markers():
    findings = []
    for path in runtime_sources():
        text = path.read_text()
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            name = ast.unparse(node.func)
            if name in {"breakpoint", "pdb.set_trace", "ipdb.set_trace", "debugpy.breakpoint"}:
                findings.append((str(path.relative_to(ROOT)), node.lineno, name))
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT and re.search(r"\b(?:TODO|FIXME|HACK)\b", token.string):
                findings.append((str(path.relative_to(ROOT)), token.start[0], token.string))
    assert not findings

