import copy
import json
import subprocess
import sys
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from redeck_style.content_repair import SourceCatalog
from redeck_style.execution import request_scope, request_slot
from redeck_style.repair import candidate_decision, spatial_guidance
from scripts import codegen
from test_content_repair import PASS, context


class RequestError(Exception):
    def __init__(self, status, message="request failed", headers=None):
        super().__init__(message)
        self.status_code = status
        self.response = SimpleNamespace(headers=headers or {})


def client_fixture(outcomes):
    calls = []
    remaining = iter(outcomes)

    def create(**kwargs):
        calls.append(kwargs)
        result = next(remaining)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=result))],
                               usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3))

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def test_transport_retries_rate_limit_and_preserves_completion_limit(tmp_path, monkeypatch):
    client, calls = client_fixture([RequestError(429, headers={"retry-after": "3"}), "ok"])
    sleeps = []
    monkeypatch.setattr(codegen.time, "sleep", sleeps.append)
    result = codegen.call_llm(client, "gpt-5.5", "rules", "input", max_output_tokens=4096, log_prefix=tmp_path / "model")
    assert result[:3] == ("ok", 7, 3) and sleeps == [3]
    assert all(call["extra_body"] == {"max_completion_tokens": 4096} for call in calls)
    usage = json.loads(next(tmp_path.glob("*.usage.json")).read_text())
    assert usage["status"] == "completed" and len(usage["attempts"]) == 2
    assert usage["attempts"][0]["http_status"] == 429


def test_transport_parameter_fallback_and_logs_do_not_overwrite(tmp_path):
    client, calls = client_fixture([RequestError(400, "unsupported max_completion_tokens"), "first", "second"])
    codegen.call_llm(client, "gpt-5.5", "rules", "input", log_prefix=tmp_path / "same")
    codegen.call_llm(client, "gpt-5.5", "rules", "input", log_prefix=tmp_path / "same")
    assert calls[1]["max_tokens"] == 16384
    assert len(list(tmp_path.glob("*.request.json"))) == 2
    assert {path.read_text() for path in tmp_path.glob("*.response.txt")} == {"first", "second"}


def test_transport_does_not_retry_auth_errors(tmp_path):
    client, calls = client_fixture([RequestError(401)])
    with pytest.raises(RequestError):
        codegen.call_llm(client, "gpt-5.5", "rules", "input", log_prefix=tmp_path / "failed")
    assert len(calls) == 1
    assert json.loads(next(tmp_path.glob("*.usage.json")).read_text())["status"] == "error"


def test_transport_records_exhausted_reasoning_output_budget():
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""), finish_reason="length")],
        usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4096,
                              completion_tokens_details=SimpleNamespace(reasoning_tokens=4096)))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
    assert codegen.call_llm(client, "gpt-5.5", "rules", "input")[0] == ""
    assert client._redeck_last_call_usage["finish_reason"] == "length"
    assert client._redeck_last_call_usage["reasoning_tokens"] == 4096


def test_visual_review_reserves_output_budget_for_json(tmp_path, monkeypatch):
    from PIL import Image
    from scripts import repair

    png = tmp_path / "slide.png"
    Image.new("RGB", (32, 18), "white").save(png)
    requests = []
    response = {"verdict": "pass", "issues": [], "scope": {"verdict": "preserved", "reason": "same"},
                "typography": {"verdict": "readable", "reason": "same"},
                "composition": {"verdict": "coherent", "reason": "same"}}
    def respond(*args, **kwargs):
        requests.append(kwargs)
        return json.dumps(response), 1, 1, .1
    monkeypatch.setattr(repair, "call_llm", respond)
    assert repair.call_visual_review(None, "gpt-5.5", png, png, {})["valid"]
    assert requests[0]["max_output_tokens"] == 8192


def test_transport_ignores_malformed_retry_after(monkeypatch):
    client, calls = client_fixture([RequestError(429, headers={"retry-after": "invalid"}), "ok"])
    sleeps = []
    monkeypatch.setattr(codegen.time, "sleep", sleeps.append)
    assert codegen.call_llm(client, "gpt-5.5", "rules", "input")[0] == "ok"
    assert len(calls) == 2 and sleeps == [1]


def test_responses_transport_retries_connection_errors(monkeypatch):
    outcomes = iter([urllib.error.URLError("temporary failure"), ("ok", 5, 2)])
    def respond(*args):
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(codegen, "_responses_http", respond)
    monkeypatch.setattr(codegen.time, "sleep", lambda delay: None)
    client = SimpleNamespace()
    assert codegen.call_llm(client, "mai-fixture", "rules", "input")[:3] == ("ok", 5, 2)
    assert len(client._redeck_last_call_usage["attempts"]) == 2


@pytest.mark.parametrize("route", ["probe", "proposal"])
def test_content_routes_preserve_transport_failure_logs(tmp_path, monkeypatch, context, route):
    from scripts import content_repair, content_probe_worker

    transport = {"status": "error", "attempts": [{"http_status": 429, "queue_seconds": .2}]}
    client = SimpleNamespace(_redeck_last_call_usage=transport)
    def fail(*args, **kwargs):
        raise RequestError(429)
    monkeypatch.setattr(codegen, "get_client", lambda api: client)
    monkeypatch.setattr(codegen, "call_llm", fail)
    monkeypatch.setattr(content_repair, "call_llm", fail)
    with pytest.raises(RequestError):
        if route == "probe":
            probe = content_probe_worker.LoggedProbeClient("local", tmp_path, "fixture")
            probe.probe_id, probe.slide_ids = "D02", [1]
            probe.call_text("rules", "input")
        else:
            png = tmp_path / "slide.png"
            png.write_bytes(b"fixture")
            content_repair.propose(client, "fixture", "<html></html>", png, {}, [], SourceCatalog(context),
                                   "", tmp_path / "attempt", True)
    record = json.loads(next(tmp_path.glob("*.usage.json")).read_text())
    assert record["status"] == "error" and record["transport"] == transport


def test_shared_limit_releases_slots_on_exception(tmp_path):
    with request_scope(tmp_path, 1):
        with pytest.raises(RuntimeError):
            with request_slot(.2):
                raise RuntimeError("failed call")
        with request_slot(.2):
            pass


def test_request_slots_are_shared_across_processes(tmp_path):
    script = '''
import json, sys, time
from redeck_style.execution import request_scope, request_slot
with request_scope(sys.argv[1], 2):
    with request_slot(5):
        started = time.monotonic()
        time.sleep(.2)
        print(json.dumps([started, time.monotonic()]))
'''
    processes = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdout=subprocess.PIPE, text=True)
                 for index in range(4)]
    intervals = []
    for process in processes:
        output, _ = process.communicate(timeout=10)
        assert process.returncode == 0
        intervals.append(json.loads(output))
    events = sorted([(start, 1) for start, end in intervals] + [(end, -1) for start, end in intervals])
    active = peak = 0
    for stamp, delta in events:
        active += delta
        peak = max(peak, active)
    assert peak == 2


def test_conditional_guidance_keeps_the_core_contract_small():
    assert spatial_guidance({}, PASS) == ""
    arrows = spatial_guidance({"connector_occlusion_count": 1}, PASS)
    assert "8px" in arrows and "arrowhead visible" in arrows
    chart = spatial_guidance({}, {"issues": [{"description": "Chart labels cross a grid line"}]})
    assert "Never move data points" in chart


def test_source_windows_merge_without_losing_exact_offsets(context):
    catalog = SourceCatalog(context)
    document = catalog.documents["paper_full.md"]
    windows = [{"source_ref": "paper_full.md", "offset": start, "excerpt": document[start:end]}
               for start, end in [(0, 25), (15, 40), (0, 25), (35, len(document))]]
    result = catalog.merge_results(windows)
    assert result == [{"source_ref": "paper_full.md", "offset": 0, "excerpt": document}]
    assert sum(len(item["excerpt"]) for item in catalog.merge_results(windows, 30)) <= 30
    windows[0]["excerpt"] = "not supplied evidence"
    with pytest.raises(ValueError, match="frozen evidence"):
        catalog.merge_results(windows)


def test_source_lookup_retains_previous_primary_evidence_under_budget(tmp_path, monkeypatch):
    from redeck_style.evaluation.snapshot import file_hash
    from scripts import content_repair

    source = tmp_path / "paper_full.md"
    source.write_text("Title evidence. " * 2000)
    catalog = SourceCatalog({"source_dir": str(tmp_path), "source_hashes": {source.name: file_hash(source)}})
    document = source.read_text()

    def search(query, tables_only=False):
        primary = 14000 if query == "mechanism" else 0
        return [{"source_ref": source.name, "offset": offset, "excerpt": document[offset:offset + 2400]}
                for offset in (primary, 3000, 6000, 9000, 18000)]

    requests = []
    responses = iter([{"tool": "search_source", "query": query} for query in ("mechanism", "title", "mechanism", "title")]
                     + [{"tool": "defer", "reason": "fixture complete"}])

    def respond(client, model, system, content):
        requests.append(json.loads(content[0]["text"]))
        return json.dumps(next(responses)), 1, 1, .01

    monkeypatch.setattr(catalog, "search", search)
    monkeypatch.setattr(content_repair, "call_llm", respond)
    png = tmp_path / "slide.png"
    png.write_bytes(b"fixture")
    with pytest.raises(content_repair.ContentRepairDeferred):
        content_repair.propose(None, "fixture", "<html></html>", png, {}, [], catalog, "", tmp_path / "attempt", True)
    for request in requests[1:]:
        assert {0, 14000} <= {result["offset"] for result in request["source_results"]}
        assert sum(len(result["excerpt"]) for result in request["source_results"]) <= 12000
    assert requests[-1]["tool_progress"] == {"call": 5, "remaining_calls": 1,
        "searches": [{"tool": "search_source", "query": query, "matches": 5}
                     for query in ("mechanism", "title", "mechanism", "title")]}


@pytest.mark.parametrize("unsafe", [False, True])
def test_candidate_decision_distinguishes_working_and_selected_versions(unsafe):
    original = {"validity": {"text_collision_count": 1}, "review": {"valid": True, "verdict": "revise", "issues": [{}]},
                "content_verified": False, "content_changed": False}
    candidate = {**copy.deepcopy(original), "content_verified": True, "content_changed": True}
    before = copy.deepcopy(candidate)
    result = candidate_decision(original, original, candidate, editing_content=True, exploring_layout=False,
                                spatial_enabled=True, review_reasons=["unsafe"] if unsafe else [], content_reasons=[], replan_content=False)
    assert result["advance"] is not unsafe
    assert not result["eligible"] and not result["selected"]
    assert candidate == before
