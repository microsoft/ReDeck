import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from redeck_style.evaluation import coordinator
from redeck_style.evaluation.snapshot import capture_page
from redeck_style.repair import repair_user_prompt
from scripts import codegen, repair


def test_snapshot_retries_only_transient_capture_failure(tmp_path, monkeypatch):
    from playwright.sync_api import Error, Page

    original = Page.screenshot
    attempts = []

    def flaky(page, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise Error("Protocol error (Page.captureScreenshot): Unable to capture screenshot")
        return original(page, **kwargs)

    monkeypatch.setattr(Page, "screenshot", flaky)
    source = tmp_path / "slide.html"
    source.write_text("<html><body><p>Frozen visible content</p></body></html>")
    snapshot = capture_page(source, tmp_path / "slide.png")
    assert len(attempts) == snapshot["screenshot_attempts"] == 2
    assert any(item["text_content"] == "Frozen visible content" for item in snapshot["objects"])


@pytest.mark.parametrize("message,expected", [("Unable to capture screenshot", 3), ("Target page closed", 1)])
def test_snapshot_capture_failure_never_writes_a_pass(tmp_path, monkeypatch, message, expected):
    from playwright.sync_api import Error, Page

    attempts = []

    def fail(page, **kwargs):
        attempts.append(1)
        raise Error(message)

    monkeypatch.setattr(Page, "screenshot", fail)
    source = tmp_path / "slide.html"
    source.write_text("<html><body><p>Frozen visible content</p></body></html>")
    png = tmp_path / "slide.png"
    with pytest.raises(Error, match=message):
        capture_page(source, png)
    assert len(attempts) == expected
    assert not png.with_suffix(".state.json").exists()


@pytest.mark.parametrize("api", codegen.API_CHOICES)
def test_client_respects_explicit_endpoint_and_key(monkeypatch, api):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    calls = []
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs: calls.append(kwargs)))
    codegen.get_client(api)
    assert calls == [{"base_url": "https://example.invalid/v1", "api_key": "fixture-key"}]


@pytest.mark.parametrize("key", [None, "", "   ", "dummy"])
def test_missing_credentials_cannot_silently_target_remote_service(monkeypatch, key):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    if key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", key)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        codegen.get_client()


@pytest.mark.parametrize("endpoint", [None, "", "   "])
def test_client_defaults_to_public_api(monkeypatch, endpoint):
    if endpoint is None:
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    calls = []
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs: calls.append(kwargs)))
    codegen.get_client()
    assert calls == [{"base_url": "https://api.openai.com/v1", "api_key": "fixture-key"}]


@pytest.mark.parametrize("endpoint", ["http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "http://[::1]:8000/v1"])
def test_explicit_loopback_server_can_use_no_key(monkeypatch, endpoint):
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls = []
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs: calls.append(kwargs)))
    codegen.get_client()
    assert calls == [{"base_url": endpoint, "api_key": "dummy"}]


def test_unknown_api_cannot_silently_fall_back(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs: pytest.fail("Unexpected client")))
    with pytest.raises(ValueError, match="Unsupported API route"):
        codegen.get_client("unsupported-route")


def test_offline_extractor_uses_the_shared_public_client(monkeypatch):
    from scripts import extract_components

    client = object()
    monkeypatch.setattr(codegen, "get_client", lambda: client)
    assert extract_components.get_client() is client


def test_blueprint_can_be_resolved_without_machine_specific_paths(tmp_path, monkeypatch):
    path = tmp_path / "runs/custom_trial/turn_00/deck_blueprint.json"
    path.parent.mkdir(parents=True)
    payload = {"slides": [{"slide_id": 1, "primary_proposition": "Fixture evidence", "must_cover_subset": ["A fact"]}]}
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("REDECK_LEGACY_ROOT", str(tmp_path))
    resolved, actual = codegen.resolve_blueprint("custom")
    assert resolved == path and actual == payload


def test_retry_includes_diagnostics_once():
    validity = {"text_collision_count": 1, "text_geometry": [{"selector": "unique-audit-selector"}]}
    prompt = repair_user_prompt("<html/>", validity, repair._diagnostic_feedback(2, validity))
    assert prompt.count("unique-audit-selector") == 1


@pytest.mark.parametrize("identical", [True, False])
def test_visual_payload_deduplicates_only_identical_images(tmp_path, monkeypatch, identical):
    original, current = tmp_path / "original.png", tmp_path / "current.png"
    Image.new("RGB", (16, 16), "white").save(original)
    Image.new("RGB", (16, 16), "white" if identical else "black").save(current)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"verdict":"pass","issues":[]}'))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    repair.call_visual_review(client, "fixture", original, current, {})
    images = [entry for entry in calls[0]["messages"][1]["content"] if entry["type"] == "image_url"]
    assert len(images) == (1 if identical else 2)


def test_snapshot_disables_page_scripts_and_http_resources(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = tmp_path / "slide.html"
        source.write_text(f'<html><body><p>Original text</p><script>document.querySelector("p").textContent="MUTATED";</script>'
                          f'<img src="http://127.0.0.1:{server.server_port}/private-resource"></body></html>')
        snapshot = capture_page(source, tmp_path / "slide.png")
        text = " ".join(item["text_content"] for item in snapshot["objects"])
        assert "Original text" in text and "MUTATED" not in text
        assert requests == []
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_content_provider_consumes_shared_snapshot_without_loading_again(tmp_path, monkeypatch):
    source = tmp_path / "slide.html"
    source.write_text("<html><body>Source fact</body></html>")
    snapshot = {**capture_page(source, tmp_path / "slide.png"), "slide_id": 1}
    monkeypatch.setattr(coordinator, "source_context", lambda *args: {"source_dir": str(tmp_path), "source_hashes": {}, "blueprint": {}})
    monkeypatch.setattr(coordinator, "load_snapshot", lambda *args, **kwargs: pytest.fail("Duplicate snapshot load"))

    def worker(command, **kwargs):
        request = json.loads(Path(command[-1]).read_text())
        assert request["pages"][0]["objects"] == snapshot["objects"]
        records = [{"probe_id": probe_id, "status": "passed", "issues": []} for probe_id in coordinator.DEFAULT_PROBES]
        (Path(request["output_dir"]) / "result.json").write_text(json.dumps({"probes": records}))

    monkeypatch.setattr(coordinator.subprocess, "run", worker)
    report = coordinator.review_pages([snapshot], tmp_path / "review", {"source_run": tmp_path})
    assert report["status"] == "passed"
