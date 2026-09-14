"""Load versioned, runtime-safe design artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from redeck_style.domain.models import DesignDialect, Theme, VocabItem
from redeck_style.library.compatibility import CompatibilityGraph, STYLE_KINDS


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS = ROOT / "pattern_library" / "artifacts"
DEFAULT_THEMES = ROOT / "pattern_library" / "metadata" / "theme_library.json"


class RuntimeLibrary:
    def __init__(self, artifact_dir=None, theme_path=None):
        artifact_dir = Path(artifact_dir or DEFAULT_ARTIFACTS)
        vocab_payload = self._read(artifact_dir / "vocab_library.v1.json", "1.")
        dialect_payload = self._read(artifact_dir / "dialect_library.v1.json", "1.")
        graph_payload = self._read(artifact_dir / "compatibility_graph.v1.json", "1.")
        if len({payload.get("source_hash") for payload in (vocab_payload, dialect_payload, graph_payload)}) != 1:
            raise ValueError("runtime artifacts come from different builds; rebuild them together")
        self.items = {
            item["id"]: VocabItem(
                id=item["id"],
                kind=item["kind"],
                program=item["program"],
                interface=item["interface"],
                parameters=item["parameters"],
                compatibility=item["compatibility"],
                provenance=item["provenance"],
                invariants=tuple(item.get("invariants", [])),
            )
            for item in vocab_payload["items"]
        }
        self.dialects = {
            item["id"]: DesignDialect(
                id=item["id"],
                tags=tuple(item.get("tags", [])),
                allowed_kinds=tuple(item["allowed_kinds"]),
                exclusions=tuple(item.get("exclusions", [])),
                rules=item.get("rules", {}),
            )
            for item in dialect_payload["items"]
        }
        self.graph = graph_payload
        self.compatibility = CompatibilityGraph(graph_payload, self.items)
        self.legacy_source_groups = {
            item["id"]: DesignDialect(
                id=item["id"], tags=tuple(item.get("tags", [])),
                allowed_kinds=tuple(item["allowed_kinds"]), exclusions=tuple(item.get("exclusions", [])),
                rules={**item["rules"], "selection_basis": "legacy-source-palette"},
            ) for item in dialect_payload.get("legacy_source_groups", [])
        }
        themes = json.loads(Path(theme_path or DEFAULT_THEMES).read_text())["themes"]
        self.themes = {
            item["id"]: Theme(
                id=item["id"],
                palette_name=item["palette_name"],
                luminance=item["luminance"],
                tokens=item["tokens"],
            )
            for item in themes
        }

    @staticmethod
    def _read(path, major):
        if not path.exists():
            raise FileNotFoundError(
                f"missing compiled artifact {path}; run scripts/build_runtime_library.py"
            )
        payload = json.loads(path.read_text())
        version = str(payload.get("schema_version", ""))
        if not version.startswith(major):
            raise ValueError(f"unsupported artifact schema {version} in {path}")
        return payload

    def resolve_theme(self, palette_name, luminance):
        theme_id = f"{palette_name}_{luminance}"
        if theme_id not in self.themes:
            available = ", ".join(sorted(self.themes))
            raise ValueError(f"unknown theme {theme_id}; available: {available}")
        return self.themes[theme_id]

    def resolve_dialect(self, dialect_id):
        if dialect_id in self.legacy_source_groups:
            return self.legacy_source_groups[dialect_id]
        try:
            return self.dialects[dialect_id]
        except KeyError as error:
            raise ValueError(f"unknown design dialect: {dialect_id}") from error

    def query(self, kind, dialect_id, role=None, density=None):
        dialect = self.resolve_dialect(dialect_id)
        if kind not in dialect.allowed_kinds:
            return []
        candidates = []
        for item in self.items.values():
            if item.kind != kind:
                continue
            dialects = item.compatibility.get("dialect_ids", [])
            if item.id in dialect.exclusions:
                continue
            if dialect_id in self.legacy_source_groups and kind in STYLE_KINDS:
                if (item.provenance.get("source_palette") != dialect.rules["palette"]
                        or item.provenance.get("source_luminance") != dialect.rules["luminance"]):
                    continue
            elif "*" not in dialects and dialect_id not in dialects:
                continue
            score = 0
            roles = item.compatibility.get("role_affinity", [])
            densities = item.compatibility.get("density", [])
            if role and role in roles:
                score += 8
            if density and density in densities:
                score += 3
            candidates.append((score, item))
        return [item for _, item in sorted(candidates, key=lambda pair: (-pair[0], pair[1].id))]
