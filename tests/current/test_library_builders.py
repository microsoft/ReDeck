import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import pytest

from app.schemas.issue_types import PROBE_REGISTRY
from scripts import build_probe_registry, build_runtime_library, extract_patterns
from scripts.build_style_library import build_library
from scripts.build_theme_library import build_theme_library


ROOT = Path(__file__).resolve().parents[2]


class LibraryBuilderTest(unittest.TestCase):
    def test_style_builder_needs_only_bams_catalog_and_components(self):
        result = build_library(
            ROOT / "pattern_library" / "metadata" / "pattern_catalog.json",
            ROOT / "pattern_library" / "metadata" / "seed_components.json",
        )
        self.assertEqual(result["spec_count"], 345)
        self.assertEqual(result["family_count"], 69)

    def test_raw_components_use_source_slots_not_runtime_theme_names(self):
        components = (ROOT / "pattern_library" / "metadata" / "seed_components.json").read_text()
        self.assertNotIn("--bg-dark", components)
        self.assertNotIn("--bg-light", components)
        self.assertNotIn("var(--accent)", components)
        self.assertIn("--source-accent", components)

    def test_theme_builder_accepts_color_only_sources(self):
        source = [{
            "id": "sample_light",
            "palette_name": "sample",
            "luminance": "light",
            "palette": {
                "bg_dark": "#111111",
                "bg_light": "#f5f5f5",
                "accent": "#cc3300",
                "text_dark": "#101010",
                "text_light": "#ffffff",
            },
        }]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "palettes.json"
            path.write_text(json.dumps(source))
            result = build_theme_library(path)
        self.assertEqual(result["theme_count"], 1)
        self.assertEqual(result["themes"][0]["palette_name"], "sample")
        self.assertNotIn("components", result["themes"][0])


def test_probe_builder_uses_current_definitions_and_bundled_checks():
    registry, total = build_probe_registry.build_registry()
    assert set(registry) == set(PROBE_REGISTRY)
    assert "B20" in registry and "B19" not in registry
    assert total == sum(len(info["checks"]) for info in registry.values())
    for probe_id, info in registry.items():
        assert info["issue_type"] == PROBE_REGISTRY[probe_id].name
        assert info["family"] == PROBE_REGISTRY[probe_id].family.value
        assert info["checks"]
    bundled = json.loads((ROOT / "app/prompts/probes/probe_registry.json").read_text())
    assert registry == bundled


def test_runtime_builder_help_and_output_are_explicit(tmp_path, monkeypatch):
    calls = []

    def build(output_dir, seeds_dir):
        calls.append((output_dir, seeds_dir))
        return 3, 2

    monkeypatch.setattr(build_runtime_library, "build", build)
    with pytest.raises(SystemExit) as exit_info:
        build_runtime_library.main(["--help"])
    assert exit_info.value.code == 0 and not calls
    output = tmp_path / "artifacts"
    seeds = tmp_path / "seeds"
    build_runtime_library.main(["--out", str(output), "--seeds-dir", str(seeds)])
    assert calls == [(output, seeds)]


@pytest.mark.parametrize("has_seed", [False, True])
def test_runtime_builder_rejects_incomplete_seed_library_without_writing(tmp_path, has_seed):
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    if has_seed:
        (seeds / "seed_000.html").write_text("<svg viewBox='0 0 200 200'></svg>")
    output = tmp_path / "artifacts"
    output.mkdir()
    existing = output / "vocab_library.v1.json"
    existing.write_text("preserved")
    with pytest.raises(FileNotFoundError, match="complete authorized seeds"):
        build_runtime_library.build(output, seeds)
    assert existing.read_text() == "preserved"
    assert list(output.iterdir()) == [existing]


def test_probe_builder_writes_only_requested_output_without_count_quota(tmp_path, monkeypatch, capsys):
    definition = replace(PROBE_REGISTRY["D02"], probe_id="Q01", probe_file="Q01_custom.md")
    monkeypatch.setattr(build_probe_registry, "PROBE_REGISTRY", {"Q01": definition})
    probes = tmp_path / "probes"
    probes.mkdir()
    (probes / definition.probe_file).write_text("# Numeric check\n\n## Fail if\n1. A value differs from source.\n")
    output = tmp_path / "compiled/registry.json"
    build_probe_registry.main(["--probes-dir", str(probes), "--out", str(output)])
    registry = json.loads(output.read_text())
    assert registry["Q01"]["checks"] == [{"id": "Q01.1", "text": "A value differs from source.", "source": "fail_if"}]
    captured = capsys.readouterr()
    assert "1 atomic checks" in captured.out and not captured.err
    assert not (probes / "probe_registry.json").exists()


@pytest.mark.parametrize("content", [None, "# Missing conditions\n"])
def test_probe_builder_does_not_publish_incomplete_registry(tmp_path, monkeypatch, content):
    definition = PROBE_REGISTRY["D02"]
    monkeypatch.setattr(build_probe_registry, "PROBE_REGISTRY", {"D02": definition})
    if content is not None:
        (tmp_path / definition.probe_file).write_text(content)
    output = tmp_path / "registry.json"
    output.write_text("preserved")
    with pytest.raises((FileNotFoundError, ValueError)):
        build_probe_registry.main(["--probes-dir", str(tmp_path), "--out", str(output)])
    assert output.read_text() == "preserved"


def test_pattern_extractor_uses_current_catalog_and_explicit_paths(tmp_path):
    assert extract_patterns.LIBRARY_JSON == ROOT / "pattern_library/metadata/pattern_catalog.json"
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "seed_fixture.html").write_text("<html><style>.slide{display:grid;color:#112233}</style><body><div class='slide'>Fixture</div></body></html>")
    source = tmp_path / "source.json"
    source.write_text(json.dumps([{"id": "seed_fixture", "dims": {"content": "comparison-columns"}}]))
    output = tmp_path / "extracted/catalog.json"
    extract_patterns.main(["--seeds-dir", str(seeds), "--catalog", str(source), "--out", str(output)])
    catalog = json.loads(output.read_text())
    assert len(catalog) == 1
    assert catalog[0]["id"] == "seed_fixture"
    assert catalog[0]["dims"] == {"content": "comparison-columns"}


@pytest.mark.parametrize("has_seed", [False, True])
def test_pattern_extractor_rejects_missing_inputs_before_overwriting(tmp_path, has_seed):
    if has_seed:
        (tmp_path / "seed_unknown.html").write_text("<html><body>Fixture</body></html>")
    catalog = tmp_path / "catalog.json"
    catalog.write_text("[]")
    with pytest.raises(SystemExit):
        extract_patterns.main(["--seeds-dir", str(tmp_path), "--catalog", str(catalog), "--out", str(catalog)])
    assert catalog.read_text() == "[]"


if __name__ == "__main__":
    unittest.main()
