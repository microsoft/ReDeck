#!/usr/bin/env python3
"""Compile legacy extraction outputs into the typed runtime artifacts.

This is an offline migration builder. Runtime modules never read the legacy
StyleSpec, layout, component, or source-page files.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from redeck_style.library.compatibility import GRAPH_POLICY, STYLE_KINDS

META = ROOT / "pattern_library" / "metadata"
OUT = ROOT / "pattern_library" / "artifacts"


ROLE_BY_CONTENT = {
    "title-only": ["title"],
    "quote-block": ["title", "conclusion"],
    "bullet-text": ["context", "conclusion", "discussion"],
    "diagram-boxes": ["context", "method", "discussion"],
    "process-arrows": ["method"],
    "timeline-nodes": ["method"],
    "bar-chart": ["results", "evaluation", "comparison"],
    "data-table": ["results", "evaluation", "comparison"],
    "big-numbers-KPI": ["results", "evaluation", "conclusion"],
    "comparison-columns": ["comparison", "discussion"],
    "icon-grid": ["context", "conclusion"],
}


def _hash(paths):
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _payload(items, source_hash):
    return {
        "schema_version": "1.1.0",
        "builder_version": "runtime-library-v2",
        "source_hash": source_hash,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }


def _base_item(item_id, kind, program, dialect_ids, seed_id, roles=None, density=None, **extra):
    requires = {"tokens": [], "ports": []}
    provides = {"roles": [], "ports": []}
    if kind == "layout":
        provides["ports"] = ["title_zone", "evidence_zone", "boundary", "negative_space"]
    elif kind == "content":
        requires["ports"] = ["evidence_zone"]
        provides["ports"] = ["annotation_edge"]
    elif kind == "typography":
        requires["ports"] = ["title_zone"]
    elif kind == "separator":
        requires["ports"] = ["boundary"]
    elif kind == "decoration":
        requires["ports"] = ["negative_space"]
    compatibility = {
        "dialect_ids": dialect_ids,
        "role_affinity": roles or [],
        "density": density or ["low", "medium", "high"],
        **extra,
    }
    return {
        "id": item_id,
        "kind": kind,
        "program": program,
        "interface": {"requires": requires, "provides": provides},
        "parameters": {},
        "compatibility": compatibility,
        "provenance": {"seed_id": seed_id, "source_hash": hashlib.sha256(json.dumps(program, sort_keys=True).encode()).hexdigest()},
        "invariants": [],
    }


def _content_program(kind, extracted_css):
    """Add a reusable internal structure without retaining source text or page DOM."""
    programs = {
        "big-numbers-KPI": {
            "css": """.metric-system{display:grid;grid-template-columns:repeat(var(--metric-count,5),minmax(0,1fr));height:100%}.metric-unit{position:relative;padding:10px 16px;text-align:center;border-left:1px solid color-mix(in srgb,var(--ink-canvas) 22%,transparent)}.metric-unit:first-child{border-left:0}.metric-icon{width:54px;height:54px;margin:0 auto 14px;border:1px solid var(--accent-secondary);border-radius:50%;display:grid;place-items:center}.metric-value{font:400 clamp(42px,4.6vw,66px)/.95 Georgia,serif;color:var(--ink-canvas)}.metric-label{margin-top:12px;font:700 13px/1.15 'Segoe UI',Arial,sans-serif;letter-spacing:.7px;text-transform:uppercase;color:var(--accent-tertiary)}.metric-note{margin-top:13px;font:13px/1.25 'Segoe UI',Arial,sans-serif;color:var(--ink-canvas)}""",
            "html": """<div class="metric-system" style="--metric-count:5"><div class="metric-unit" data-repeat="metric"><div class="metric-icon"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="10" fill="none" stroke="currentColor"/></svg></div><div class="metric-value">VALUE</div><div class="metric-label">LABEL</div><div class="metric-note">QUALIFIER</div></div><!-- repeat 3–6 evidence-backed units --></div>""",
        },
        "data-table": {
            "css": """.matrix-system{display:grid;grid-template-columns:repeat(var(--matrix-count,2),minmax(0,1fr));gap:20px;height:100%;color:var(--ink-canvas)}.matrix-panel{min-width:0;display:grid;grid-template-rows:58px 28px minmax(0,1fr);color:var(--ink-canvas);border:1px solid color-mix(in srgb,var(--ink-canvas) 24%,transparent);border-radius:12px;background:linear-gradient(145deg,color-mix(in srgb,var(--surface-muted) 92%,transparent),color-mix(in srgb,var(--surface-canvas) 88%,transparent));padding:10px 12px 12px;box-shadow:inset 0 1px color-mix(in srgb,var(--ink-canvas) 8%,transparent)}.matrix-heading{display:grid;grid-template-columns:38px 1fr auto;align-items:center;gap:10px;border-bottom:1px solid color-mix(in srgb,var(--ink-canvas) 16%,transparent)}.matrix-heading svg{width:34px;height:34px;padding:7px;border-radius:50%;background:color-mix(in srgb,var(--ink-canvas) 10%,transparent)}.matrix-heading-copy{display:grid;gap:3px}.matrix-eyebrow{font:700 9px/1 'Segoe UI',Arial,sans-serif;letter-spacing:1.15px;text-transform:uppercase;color:var(--accent-tertiary)}.matrix-title{font:750 15px/1.05 'Segoe UI',Arial,sans-serif;letter-spacing:.45px;text-transform:uppercase;color:var(--ink-canvas)}.matrix-index{font:500 11px/1 Georgia,serif;color:color-mix(in srgb,var(--ink-canvas) 58%,transparent)}.matrix-columns{display:grid;grid-template-columns:minmax(0,1fr) 36%;align-items:center;padding:0 10px;font:700 9px/1 'Segoe UI',Arial,sans-serif;letter-spacing:.9px;text-transform:uppercase;color:color-mix(in srgb,var(--ink-canvas) 62%,transparent);background:color-mix(in srgb,var(--ink-canvas) 7%,transparent)}.matrix-columns span:last-child{text-align:right}.matrix-rows{display:grid;grid-template-rows:repeat(var(--row-count),minmax(0,1fr));min-height:0}.matrix-row{display:grid;grid-template-columns:minmax(0,1fr) 36%;align-items:center;gap:12px;padding:3px 10px;color:var(--ink-canvas);border-bottom:1px solid color-mix(in srgb,var(--ink-canvas) 13%,transparent)}.matrix-row:last-child{border-bottom:0}.matrix-row.is-key{background:linear-gradient(90deg,color-mix(in srgb,var(--accent-signal) 13%,transparent),transparent)}.matrix-model{min-width:0;display:grid;grid-template-columns:8px minmax(0,1fr);gap:9px;align-items:center}.family-marker{width:6px;height:22px;border-radius:4px;background:var(--accent-secondary)}.matrix-row.is-key .family-marker{background:var(--accent-signal)}.model-copy{min-width:0;display:grid;gap:2px}.model-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:650 11.5px/1.05 'Segoe UI',Arial,sans-serif;color:var(--ink-canvas)}.model-detail{font:500 8.5px/1 'Segoe UI',Arial,sans-serif;letter-spacing:.55px;text-transform:uppercase;color:color-mix(in srgb,var(--ink-canvas) 48%,transparent)}.measure-cell{position:relative;height:24px;display:grid;align-items:center;justify-items:end}.measure-track{position:absolute;left:0;right:0;bottom:2px;height:2px;background:color-mix(in srgb,var(--ink-canvas) 12%,transparent)}.measure-fill{display:block;width:var(--measure-pct);height:100%;background:var(--accent-primary)}.measure-value{position:relative;font:750 13px/1 'Segoe UI',Arial,sans-serif;font-variant-numeric:tabular-nums;color:var(--ink-canvas)}.matrix-row.is-key .measure-value{color:var(--accent-signal)}""",
            "html": """<div class="matrix-system" style="--matrix-count:2"><section class="matrix-panel" data-repeat="measure-panel"><header class="matrix-heading"><svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="11" fill="none" stroke="currentColor"/><path d="M9 19l5-5 4 3 5-7" fill="none" stroke="currentColor"/></svg><div class="matrix-heading-copy"><span class="matrix-eyebrow">MEASURE FAMILY</span><strong class="matrix-title">MEASURE</strong></div><span class="matrix-index">01</span></header><div class="matrix-columns"><span>Structural judge</span><span>Value</span></div><div class="matrix-rows" style="--row-count:ROW_COUNT"><div class="matrix-row" data-repeat="source-row"><div class="matrix-model"><i class="family-marker"></i><div class="model-copy"><strong class="model-name">PRIMARY LABEL</strong><span class="model-detail">SECONDARY LABEL</span></div></div><div class="measure-cell"><span class="measure-value">VALUE</span><span class="measure-track"><i class="measure-fill" style="--measure-pct:VALUE%"></i></span></div></div><!-- repeat every supplied source row; selected evidence rows use class is-key --></div></section><!-- in metric-split-panels mode repeat one panel per numeric measure --></div>""",
        },
        "comparison-columns": {
            "css": """.comparison-system{display:grid;grid-template-columns:repeat(var(--column-count,2),minmax(0,1fr));gap:1px;background:color-mix(in srgb,var(--ink-canvas) 20%,transparent)}.comparison-column{background:var(--surface-canvas);padding:18px}.comparison-column h3{margin:0 0 14px;font:700 16px/1.1 'Segoe UI',Arial,sans-serif}.comparison-row{display:grid;grid-template-columns:36% 1fr;gap:12px;padding:11px 0;border-top:1px solid color-mix(in srgb,var(--ink-canvas) 16%,transparent)}""",
            "html": """<div class="comparison-system" style="--column-count:2"><section class="comparison-column"><h3>GROUP</h3><div class="comparison-row" data-repeat="comparison"><strong>CRITERION</strong><span>EVIDENCE</span></div></section><!-- repeat columns as required --></div>""",
        },
        "process-arrows": {
            "css": """.process-system{display:grid;grid-template-columns:repeat(var(--step-count,3),1fr);gap:22px}.process-step{position:relative;border-top:3px solid var(--accent-primary);padding:16px 12px}.process-step:not(:last-child):after{content:'→';position:absolute;right:-20px;top:42%;color:var(--accent-secondary);font-size:24px}.step-index{font:800 11px/1 'Segoe UI',Arial,sans-serif;color:var(--accent-secondary)}""",
            "html": """<div class="process-system" style="--step-count:3"><section class="process-step" data-repeat="step"><div class="step-index">01</div><h3>STAGE</h3><p>EVIDENCE</p></section><!-- repeat ordered stages --></div>""",
        },
        "bullet-text": {
            "css": """.evidence-list{display:grid;gap:12px}.evidence-item{display:grid;grid-template-columns:36px 1fr;gap:12px;padding:10px 0;border-top:1px solid color-mix(in srgb,var(--ink-canvas) 16%,transparent)}.evidence-index{font:700 11px/1 'Segoe UI',Arial,sans-serif;color:var(--accent-secondary)}""",
            "html": """<div class="evidence-list"><div class="evidence-item" data-repeat="evidence"><span class="evidence-index">01</span><div><strong>CLAIM</strong><p>SUPPORT</p></div></div><!-- repeat evidence items --></div>""",
        },
    }
    program = dict(programs.get(kind, {"css": extracted_css}))
    if extracted_css and kind not in programs:
        program["css"] = extracted_css
    return program


def _regions(layout):
    curated = {
        "seed_075": [
            {"role": "title", "x": 19, "y": 8, "w": 58, "h": 13},
            {"role": "sidebar", "x": 0, "y": 0, "w": 15.5, "h": 100},
            {"role": "narrative", "x": 19, "y": 22, "w": 34, "h": 22},
            {"role": "metric", "x": 18, "y": 48, "w": 58, "h": 25},
            {"role": "support", "x": 16, "y": 80, "w": 84, "h": 20},
        ],
        "seed_217": [
            {"role": "title", "x": 3.5, "y": 6, "w": 72, "h": 12},
            {"role": "table", "x": 3.5, "y": 24, "w": 93, "h": 61},
            {"role": "footer", "x": 3.5, "y": 92, "w": 93, "h": 5},
        ],
    }
    if layout["id"] in curated:
        return curated[layout["id"]]
    zones = layout.get("zones", [])
    dimension_pool = {}
    for zone in zones:
        role = zone.get("slot", "body")
        dimension_pool.setdefault(role, {}).update(
            {key: zone[key] for key in ("w", "h") if key in zone}
        )
    panel_dims = dimension_pool.get("panel", {})
    compiled = []
    for zone in zones:
        role = zone.get("slot", "body")
        if role in {"footer", "zone"} and not ("x" in zone and "y" in zone):
            continue
        item = {"role": "body" if role in {"panel", "zone"} else role}
        item.update({key: zone[key] for key in ("x", "y", "w", "h") if key in zone})
        if role == "zone":
            item.update({key: value for key, value in panel_dims.items() if key not in item})
        compiled.append(item)
    return compiled


def _resolve_style_tokens(code, tokens):
    replacements = {
        "--style-font-title": tokens.get("font_title", "'Segoe UI',Arial,sans-serif"),
        "--style-font-body": tokens.get("font_body", "'Segoe UI',Arial,sans-serif"),
        "--style-title-size": tokens.get("title_size", "44px"),
        "--style-title-weight": tokens.get("title_weight", "700"),
        "--style-title-line-height": tokens.get("title_line_height", "1.08"),
        "--style-title-tracking": tokens.get("title_tracking", "0"),
        "--style-title-shadow": tokens.get("title_shadow", "none"),
        "--style-corner-radius": tokens.get("corner_radius", "0px"),
        "--style-border-width": tokens.get("border_width", "1px"),
        "--style-surface-shadow": tokens.get("surface_shadow", "none"),
    }
    for name, value in replacements.items():
        code = code.replace(f"var({name})", value)
    return code


def _temper_background(code):
    """Keep repeated texture subordinate to content on dark canvases."""
    code = code.replace(
        "linear-gradient(var(--accent-primary) 1px,var(--surface-canvas) 1px)",
        "linear-gradient(color-mix(in srgb,var(--accent-primary) 10%,transparent) 1px,transparent 1px)",
    )
    code = code.replace(
        "linear-gradient(90deg,var(--accent-primary) 1px,var(--surface-canvas) 1px)",
        "linear-gradient(90deg,color-mix(in srgb,var(--accent-primary) 10%,transparent) 1px,transparent 1px)",
    )
    code = code.replace(
        "background-size:12px 12px,12px 12px",
        "background-size:36px 36px,36px 36px",
    )
    code = code.replace(
        "radial-gradient(circle at 80% 12%,var(--accent-primary),var(--surface-canvas) 28%)",
        "radial-gradient(circle at 80% 12%,color-mix(in srgb,var(--accent-primary) 34%,var(--surface-canvas)),var(--surface-canvas) 28%)",
    )
    return code


def compile_material_groups(items, catalog):
    sources = defaultdict(set)
    for item in items:
        source_id = item["provenance"]["seed_id"]
        dimensions = catalog[source_id]["dims"]
        family = dimensions["typo"]
        family_id = f"type-{family}"
        item["compatibility"]["dialect_ids"] = [family_id] if item["kind"] in STYLE_KINDS else ["*"]
        item["provenance"]["source_palette"] = dimensions["palette"]
        item["provenance"]["source_luminance"] = dimensions["lum"]
        if item["kind"] == "background":
            sources[family].add(source_id)
    return [{
        "id": f"type-{family}", "tags": [family],
        "allowed_kinds": ["layout", "background", "typography", "content", "separator", "decoration"],
        "exclusions": [],
        "rules": {"member_count": len(members), "typography_family": family,
                  "selection_basis": "typography-family", "color_independent": True},
    } for family, members in sorted(sources.items())]


def compile_compatibility_graph(items, source_hash):
    nodes = {item["id"]: {"id": item["id"], "kind": item["kind"]} for item in items}
    edges = []
    content_roles = defaultdict(set)
    for item in items:
        item_id = item["id"]
        if item["kind"] == "content":
            content_kind = item["compatibility"]["content_kind"]
            target = f"content-kind:{content_kind}"
            nodes[target] = {"id": target, "kind": "content-kind"}
            content_roles[content_kind].update(item["compatibility"].get("role_affinity", []))
            edges.append({"source": item_id, "relation": "realizes", "target": target,
                          "reason": "declared-content-kind"})
        for direction in ("requires", "provides"):
            for port in item["interface"].get(direction, {}).get("ports", []):
                target = f"port:{port}"
                nodes[target] = {"id": target, "kind": "port"}
                edges.append({"source": item_id, "relation": f"{direction}-port", "target": target,
                              "reason": "declared-material-interface"})
        if item["kind"] in STYLE_KINDS - {"typography"}:
            typography = f"typography.{item['provenance']['seed_id']}"
            if typography in nodes:
                edges.append({"source": typography, "relation": "style-companion", "target": item_id,
                              "reason": "same-source-style-bundle"})
    for item in items:
        if item["kind"] != "layout":
            continue
        roles = set(item["compatibility"].get("role_affinity", []))
        for content_kind, compatible_roles in sorted(content_roles.items()):
            exact = content_kind == item["compatibility"].get("content_kind")
            if exact or roles & compatible_roles:
                edges.append({"source": item["id"], "relation": "supports-content",
                              "target": f"content-kind:{content_kind}",
                              "reason": "source-content-kind" if exact else "shared-presentation-role"})
    return {"schema_version": "1.1.0", "builder_version": "runtime-library-v2", "policy": GRAPH_POLICY,
            "source_hash": source_hash, "created_at": datetime.now(timezone.utc).isoformat(),
            "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
            "edges": sorted(edges, key=lambda edge: (edge["source"], edge["relation"], edge["target"]))}


def build(output_dir=None, seeds_dir=None):
    from pattern_library.scene_primitives import DEFAULT_SEEDS, ScenePrimitiveLibrary

    style_path = META / "style_library.json"
    layout_path = META / "layout_library.json"
    style = json.loads(style_path.read_text())
    layouts = json.loads(layout_path.read_text())
    catalog_path = META / "pattern_catalog.json"
    catalog = {item["id"]: item for item in json.loads(catalog_path.read_text())}
    seeds_dir = Path(seeds_dir or DEFAULT_SEEDS)
    seed_paths = [seeds_dir / f"{seed_id}.html" for seed_id in sorted(catalog)]
    missing = [path for path in seed_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing {len(missing)} offline seed files under {seeds_dir}; "
            "supply the complete authorized seeds with --seeds-dir or REDECK_BAMS_SEEDS. "
            "Existing runtime artifacts were not changed."
        )
    components_path = META / "seed_components.json"
    source_hash = _hash([style_path, layout_path, catalog_path, components_path, Path(__file__), *seed_paths])
    items = []
    dialects = []

    dialect_members = {}
    for family in style["families"]:
        for member in family["members"]:
            seed_id = member["id"]
            dims = catalog[seed_id]["dims"]
            dialect_id = f"{dims['palette']}_{dims['lum']}"
            dialect_members.setdefault(dialect_id, []).append(member)
            recipes = member["recipes"]
            items.append(_base_item(
                f"background.{seed_id}", "background", {"css": _temper_background(recipes["background"])},
                [dialect_id], seed_id, bg_family=dims["bg"], typo_family=dims["typo"], motif_family=dims["deco"],
            ))
            tokens = member["tokens"]
            typo_css = (
                ".slide-title{font-family:%s;font-size:%s;font-weight:%s;line-height:%s;"
                "letter-spacing:%s;text-shadow:%s}"
                % (tokens["font_title"], tokens["title_size"], tokens["title_weight"],
                   tokens["title_line_height"], tokens["title_tracking"], tokens["title_shadow"])
            )
            items.append(_base_item(
                f"typography.{seed_id}", "typography", {"css": typo_css},
                [dialect_id], seed_id, roles=["title", "context", "method", "results", "comparison", "evaluation", "conclusion", "discussion"],
                bg_family=dims["bg"], typo_family=dims["typo"], motif_family=dims["deco"],
            ))
            if recipes.get("separator"):
                items.append(_base_item(
                    f"separator.{seed_id}", "separator", {"css": _resolve_style_tokens(recipes["separator"], tokens)},
                    [dialect_id], seed_id, bg_family=dims["bg"], typo_family=dims["typo"], motif_family=dims["deco"],
                ))
            if recipes.get("decoration"):
                code = recipes["decoration"]
                code = _resolve_style_tokens(code, tokens)
                key = "svg" if code.lstrip().startswith("<") else "css"
                items.append(_base_item(
                    f"decoration.{seed_id}", "decoration", {key: code},
                    [dialect_id], seed_id, density=["low", "medium"],
                    bg_family=dims["bg"], typo_family=dims["typo"], motif_family=dims["deco"],
                ))
            for index, content in enumerate(recipes.get("content", [])):
                kind = content["content"]
                items.append(_base_item(
                    f"content.{seed_id}.{index}", "content", _content_program(kind, _resolve_style_tokens(content["code"], tokens)),
                    [dialect_id], seed_id, roles=ROLE_BY_CONTENT.get(kind, []), content_kind=kind,
                    bg_family=dims["bg"], typo_family=dims["typo"], motif_family=dims["deco"],
                ))

    for dialect_id, members in sorted(dialect_members.items()):
        dims = [catalog[member["id"]]["dims"] for member in members]
        dialects.append({
            "id": dialect_id,
            "tags": sorted({value for item in dims for value in (item["typo"], item["deco"], item["bg"])}),
            "allowed_kinds": ["layout", "background", "typography", "content", "separator", "decoration"],
            "exclusions": [],
            "rules": {"member_count": len(members), "palette": dialect_id.rsplit("_", 1)[0], "luminance": dialect_id.rsplit("_", 1)[1]},
        })

    # Signature motifs are compiled offline from source SVG geometry. Runtime
    # sees only parameterized, text-free local motifs and never opens seed HTML.
    primitive_library = ScenePrimitiveLibrary(components_path, catalog_path, seeds_dir)
    for seed_id in sorted(catalog):
        dims = catalog[seed_id]["dims"]
        dialect_id = f"{dims['palette']}_{dims['lum']}"
        spec = primitive_library.compile(seed_id)
        for index, svg in enumerate(spec.get("motif_program", [])):
            items.append(_base_item(
                f"decoration.signature.{seed_id}.{index}",
                "decoration",
                {"svg": svg},
                [dialect_id],
                seed_id,
                density=["low", "medium", "high"],
                signature=True,
                bg_family=dims["bg"], typo_family=dims["typo"], motif_family=dims["deco"],
            ))
        motif_program = spec.get("motif_program", [])
        if len(motif_program) >= 2:
            fragments = "".join(
                f'<div class="motif-fragment motif-fragment-{index}">{svg}</div>'
                for index, svg in enumerate(motif_program[:3])
            )
            items.append(_base_item(
                f"decoration.signature-system.{seed_id}",
                "decoration",
                {
                    "css": ".motif-composition{position:absolute;inset:0;overflow:hidden}.motif-fragment{position:absolute;overflow:hidden}.motif-fragment>svg{display:block;width:100%;height:100%}.motif-fragment-0{right:-2%;top:-2%;width:67%;height:27%}.motif-fragment-1{left:-3%;bottom:-2%;width:82%;height:24%}.motif-fragment-2{right:-1%;bottom:-1%;width:40%;height:20%}",
                    "html": f'<div class="motif-composition">{fragments}</div>',
                },
                [dialect_id],
                seed_id,
                density=["low", "medium", "high"],
                signature=True,
                signature_system=True,
                bg_family=dims["bg"], typo_family=dims["typo"], motif_family=dims["deco"],
            ))

    for layout in layouts:
        content = layout["source_content"]
        items.append(_base_item(
            f"layout.{layout['id']}", "layout",
            {"macro": layout["macro"], "regions": _regions(layout)},
            ["*"], layout["id"], roles=ROLE_BY_CONTENT.get(content, []),
            density=[layout.get("density", "medium")], content_kind=content,
            bg_family=catalog[layout["id"]]["dims"]["bg"],
            typo_family=catalog[layout["id"]]["dims"]["typo"],
            motif_family=catalog[layout["id"]]["dims"]["deco"],
        ))

    material_groups = compile_material_groups(items, catalog)
    group_payload = _payload(material_groups, source_hash)
    group_payload["legacy_source_groups"] = dialects
    graph = compile_compatibility_graph(items, source_hash)
    output_dir = Path(output_dir or OUT)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "vocab_library.v1.json").write_text(json.dumps(_payload(items, source_hash), indent=2, ensure_ascii=False) + "\n")
    (output_dir / "dialect_library.v1.json").write_text(json.dumps(group_payload, indent=2, ensure_ascii=False) + "\n")
    (output_dir / "compatibility_graph.v1.json").write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n")
    return len(items), len(material_groups)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--seeds-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        item_count, dialect_count = build(args.out, args.seeds_dir)
    except FileNotFoundError as error:
        parser.error(str(error))
    print(f"built {item_count} vocab items and {dialect_count} dialects in {args.out}")


if __name__ == "__main__":
    main()
