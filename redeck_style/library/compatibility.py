"""Typed material compatibility, independent from palette and page geometry."""

from collections import defaultdict


GRAPH_POLICY = "typed-material-compatibility-v1"
STYLE_KINDS = frozenset({"background", "typography", "separator", "decoration"})
EDGE_TYPES = frozenset({"style-companion", "supports-content", "realizes", "requires-port", "provides-port"})


class CompatibilityGraph:
    def __init__(self, payload, items):
        if payload.get("policy") != GRAPH_POLICY:
            raise ValueError("runtime compatibility graph is outdated; run scripts/build_runtime_library.py")
        nodes = payload.get("nodes", [])
        self.nodes = {node["id"]: node["kind"] for node in nodes}
        if len(self.nodes) != len(nodes):
            raise ValueError("duplicate compatibility graph node")
        for item in items.values():
            if self.nodes.get(item.id) != item.kind:
                raise ValueError(f"missing or mistyped compatibility node: {item.id}")
        self.adjacency = defaultdict(set)
        self.edges = {}
        for edge in payload.get("edges", []):
            source, target, relation = edge["source"], edge["target"], edge["relation"]
            if source not in self.nodes or target not in self.nodes or relation not in EDGE_TYPES:
                raise ValueError(f"invalid compatibility edge: {edge}")
            key = (source, relation, target)
            if key in self.edges:
                raise ValueError(f"duplicate compatibility edge: {key}")
            source_kind, target_kind = self.nodes[source], self.nodes[target]
            valid = (
                relation == "style-companion" and source_kind == "typography"
                and target_kind in STYLE_KINDS - {"typography"}
                and items[source].provenance.get("seed_id") == items[target].provenance.get("seed_id")
                or relation == "supports-content" and source_kind == "layout" and target_kind == "content-kind"
                or relation == "realizes" and source_kind == "content" and target_kind == "content-kind"
                or relation in {"requires-port", "provides-port"} and source in items and target_kind == "port"
            )
            if not valid:
                raise ValueError(f"mistyped compatibility edge: {key}")
            self.edges[key] = edge
            self.adjacency[(source, relation)].add(target)
        for item in items.values():
            for direction in ("requires", "provides"):
                expected = {f"port:{port}" for port in item.interface.get(direction, {}).get("ports", [])}
                if self.targets(item.id, f"{direction}-port") != expected:
                    raise ValueError(f"graph/interface mismatch: {item.id} {direction}")
            if item.kind == "content":
                expected = {f"content-kind:{item.compatibility['content_kind']}"}
                if self.targets(item.id, "realizes") != expected:
                    raise ValueError(f"graph/content-kind mismatch: {item.id}")

    def targets(self, source, relation):
        return self.adjacency.get((source, relation), frozenset())

    def style_companion(self, typography_id, material_id):
        return material_id in self.targets(typography_id, "style-companion")

    def supports_content(self, layout_id, content_id):
        return bool(self.targets(layout_id, "supports-content") & self.targets(content_id, "realizes"))

    def selection_edges(self, layout_id, materials):
        selected = {layout_id, *(item.id for item in materials)}
        content_kinds = set().union(*(self.targets(item.id, "realizes") for item in materials if item.kind == "content"))
        result = []
        for source in sorted(selected):
            for relation in sorted(EDGE_TYPES):
                for target in sorted(self.targets(source, relation)):
                    if target in selected or target in content_kinds or self.nodes[target] == "port":
                        result.append(dict(self.edges[(source, relation, target)]))
        return result

    def selection_errors(self, layout_id, selections):
        errors = []
        content = [item for item in selections if item.kind == "content"]
        typography = [item for item in selections if item.kind == "typography"]
        if self.nodes.get(layout_id) != "layout":
            return [f"unknown layout in compatibility graph: {layout_id}"]
        for item in content:
            if not self.supports_content(layout_id, item.id):
                errors.append(f"layout/content not supported by graph: {layout_id} / {item.id}")
        if len(typography) == 1:
            for item in selections:
                if item.kind in STYLE_KINDS - {"typography"} and not self.style_companion(typography[0].id, item.id):
                    errors.append(f"style companion edge missing: {typography[0].id} / {item.id}")
        material_ids = [layout_id, *(item.id for item in selections)]
        provided = set().union(*(self.targets(item_id, "provides-port") for item_id in material_ids))
        for item_id in material_ids:
            for port in sorted(self.targets(item_id, "requires-port") - provided):
                errors.append(f"unfulfilled compatibility port: {item_id} requires {port}")
        return errors
