from types import SimpleNamespace

from app.backends.python_pptx.html_codegen_compiler import HtmlCodeGenCompiler


class RecordingLLM:
    def __init__(self):
        self.calls = []

    def call_text(self, **kwargs):
        self.calls.append(kwargs)
        return "<!doctype html><html><body>ok</body></html>"


def test_regen_uses_repair_model(monkeypatch):
    llm = RecordingLLM()
    compiler = HtmlCodeGenCompiler(
        llm,
        model="weak-generator",
        repair_model="strong-repair",
    )
    monkeypatch.setattr(
        compiler,
        "_build_slide_prompt",
        lambda *args, **kwargs: ("regen prompt", False),
    )

    html, info = compiler._generate_code_only(
        SimpleNamespace(slide_id=3),
        SimpleNamespace(),
        None,
        [],
    )

    assert info["status"] == "ok"
    assert "<body>ok</body>" in html
    assert llm.calls[0]["model"] == "strong-repair"
    assert llm.calls[0]["module_name"] == "slide_html_regen"


def test_regen_defaults_to_generation_model(monkeypatch):
    llm = RecordingLLM()
    compiler = HtmlCodeGenCompiler(llm, model="legacy-model")
    monkeypatch.setattr(
        compiler,
        "_build_slide_prompt",
        lambda *args, **kwargs: ("regen prompt", False),
    )

    compiler._generate_code_only(
        SimpleNamespace(slide_id=4),
        SimpleNamespace(),
        None,
        [],
    )

    assert llm.calls[0]["model"] == "legacy-model"
