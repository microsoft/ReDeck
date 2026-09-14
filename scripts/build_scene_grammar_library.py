#!/usr/bin/env python3
"""Extract relational scene grammars from rendered BAMS seed HTML.

Unlike the old component extractor, this keeps the spatial topology and visual
motifs while discarding source copy and literal colors. The result is not an
HTML template: runtime compilation turns each reference graph into ranges,
relations, and content-driven transformation operators.
"""

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEEDS = Path(os.environ.get("REDECK_BAMS_SEEDS", ROOT / "offline/style_seeds"))
DEFAULT_CATALOG = ROOT / "pattern_library" / "metadata" / "pattern_catalog.json"
DEFAULT_OUTPUT = ROOT / "pattern_library" / "metadata" / "scene_grammar_library.json"


EXTRACT_JS = r"""
() => {
  const root = document.querySelector('.slide,#slide') || document.body.firstElementChild || document.body;
  const rr = root.getBoundingClientRect();
  const roleOf = (el) => {
    const key = `${el.tagName} ${el.id || ''} ${el.className?.baseVal || el.className || ''}`.toLowerCase();
    const checks = [
      ['source', /(source|footer|footnote|citation)/],
      ['title', /(title|headline|heading|h1\b)/],
      ['subtitle', /(subtitle|tagline|kicker|eyebrow)/],
      ['metric', /(metric|kpi|stat|number|value|score)/],
      ['table', /(table|matrix|cell|thead|tbody)/],
      ['figure', /(figure|image|photo|visual)/],
      ['chart', /(chart|graph|bar|plot|donut|pie)/],
      ['step', /(step|stage|phase|timeline|milestone)/],
      ['label', /(label|tag|badge|caption|legend|nav)/],
      ['icon', /(icon|pictogram|glyph|logo)/],
      ['separator', /(divider|separator|rule|line|vsep|hsep)/],
      ['body', /(body|desc|copy|text|paragraph|intro|summary|list|bullet|item)/],
      ['panel', /(card|panel|box|column|col-|tile|band|strip|sidebar|rail)/],
      ['decoration', /(deco|ornament|shape|blob|wave|grain|dot|accent|corner|frame|glow)/],
    ];
    if (/^H[1-3]$/.test(el.tagName)) return 'title';
    if (el.tagName === 'TABLE' || ['TH','TD','TR'].includes(el.tagName)) return 'table';
    if (el.tagName === 'IMG') return 'figure';
    for (const [role, rx] of checks) if (rx.test(key)) return role;
    if (el.tagName === 'SVG') return 'visual';
    const direct = [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent.trim()).join(' ');
    if (direct) return 'body';
    return 'container';
  };
  const rgbaAlpha = (value) => {
    const m = value.match(/rgba?\([^)]*(?:,|\/)\s*([\d.]+)\s*\)$/);
    return m ? Number(m[1]) : (value === 'transparent' ? 0 : 1);
  };
  const all = [...root.querySelectorAll('*')];
  const raw = [];
  for (const [domIndex, el] of all.entries()) {
    if (['STYLE','SCRIPT','DEFS','STOP','TITLE','META','LINK'].includes(el.tagName)) continue;
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || Number(s.opacity) === 0) continue;
    const x = Math.max(0, r.left - rr.left), y = Math.max(0, r.top - rr.top);
    const w = Math.min(r.width, rr.width - x), h = Math.min(r.height, rr.height - y);
    if (w < 3 || h < 3 || x >= rr.width || y >= rr.height) continue;
    const directText = [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent.trim()).join(' ').trim();
    const role = roleOf(el);
    const border = Math.max(parseFloat(s.borderTopWidth)||0, parseFloat(s.borderRightWidth)||0, parseFloat(s.borderBottomWidth)||0, parseFloat(s.borderLeftWidth)||0);
    const visual = s.backgroundImage !== 'none' || rgbaAlpha(s.backgroundColor) > 0 || border > 0 || s.boxShadow !== 'none' || s.clipPath !== 'none' || s.transform !== 'none';
    const semantic = !['container','body'].includes(role);
    const structural = ['absolute','fixed'].includes(s.position) || ['grid','flex'].includes(s.display);
    if (!(directText || visual || semantic || structural || ['SVG','IMG','TABLE'].includes(el.tagName))) continue;
    let score = 0;
    if (directText) score += 6;
    if (semantic) score += 5;
    if (structural) score += 3;
    if (visual) score += 2;
    if (['SVG','IMG','TABLE'].includes(el.tagName)) score += 5;
    if (w*h > rr.width*rr.height*.025) score += 2;
    if (role === 'container' && w*h > rr.width*rr.height*.82) score -= 6;
    raw.push({
      domIndex, el, score, role, tag: el.tagName.toLowerCase(),
      classes: String(el.className?.baseVal || el.className || '').split(/\s+/).filter(Boolean).slice(0,4),
      x: x/rr.width*100, y: y/rr.height*100, w: w/rr.width*100, h: h/rr.height*100,
      directChars: directText.length,
      childCount: el.children.length,
      style: {
        position:s.position, display:s.display, fontSize:parseFloat(s.fontSize)||0,
        fontWeight:s.fontWeight, lineHeight:s.lineHeight, letterSpacing:s.letterSpacing,
        textAlign:s.textAlign, fill:s.backgroundImage !== 'none' ? (s.backgroundImage.includes('gradient')?'gradient':'image') : (rgbaAlpha(s.backgroundColor)>0?'solid':'none'),
        border:border>0, borderWidth:border, radius:parseFloat(s.borderRadius)||0,
        shadow:s.boxShadow!=='none' || s.textShadow!=='none',
        clip:s.clipPath!=='none', transform:s.transform!=='none', opacity:Number(s.opacity),
      }
    });
  }
  raw.sort((a,b) => b.score-a.score || b.w*b.h-a.w*a.h);
  const chosen = raw.slice(0,64).sort((a,b) => a.domIndex-b.domIndex);
  const map = new Map(chosen.map((n,i) => [n.el,i]));
  return {
    canvas:{width:rr.width,height:rr.height}, dom_count:all.length,
    nodes: chosen.map((n,i) => {
      let parent=n.el.parentElement, parentIndex=null;
      while (parent && parent!==root) { if (map.has(parent)) {parentIndex=map.get(parent);break;} parent=parent.parentElement; }
      const out={...n,id:`n${String(i+1).padStart(2,'0')}`,parentIndex}; delete out.el; delete out.score; delete out.domIndex;
      return out;
    })
  };
}
"""


def _round_node(node):
    for key in ("x", "y", "w", "h"):
        node[key] = round(node[key], 1)
    style = node["style"]
    style["fontSize"] = round(style["fontSize"], 1)
    style["borderWidth"] = round(style["borderWidth"], 1)
    style["radius"] = round(style["radius"], 1)
    style["opacity"] = round(style["opacity"], 2)
    parent_index = node.pop("parentIndex", None)
    if parent_index is not None:
        node["parent"] = f"n{parent_index + 1:02d}"
    return node


def _similar(a, b, tolerance=3.5):
    return abs(a - b) <= tolerance


def derive_repetitions(nodes):
    groups = defaultdict(list)
    for node in nodes:
        if node["role"] in {"title", "subtitle", "source", "container", "decoration"}:
            continue
        key = (node["role"], round(node["w"] / 5), round(node["h"] / 5), node["tag"])
        groups[key].append(node)
    output = []
    for (role, _, _, tag), items in groups.items():
        if len(items) < 2:
            continue
        xs, ys = [item["x"] for item in items], [item["y"] for item in items]
        if max(xs) - min(xs) > max(ys) - min(ys) * 1.4:
            axis = "horizontal"
        elif max(ys) - min(ys) > max(xs) - min(xs) * 1.4:
            axis = "vertical"
        else:
            axis = "grid"
        output.append({
            "role": role,
            "tag": tag,
            "count": len(items),
            "axis": axis,
            "members": [item["id"] for item in items[:8]],
        })
    return sorted(output, key=lambda item: (-item["count"], item["role"]))[:8]


def derive_relations(nodes):
    important = [
        node for node in nodes
        if node["role"] not in {"container", "decoration", "separator"}
        and node["w"] * node["h"] >= 5
    ][:24]
    relations = []
    seen = set()
    for index, left in enumerate(important):
        for right in important[index + 1:]:
            candidates = []
            if _similar(left["x"], right["x"], 1.2):
                candidates.append("align-left")
            if _similar(left["x"] + left["w"], right["x"] + right["w"], 1.2):
                candidates.append("align-right")
            if _similar(left["y"], right["y"], 1.2):
                candidates.append("align-top")
            if left["x"] + left["w"] <= right["x"] + 1.5:
                candidates.append("left-of")
            elif right["x"] + right["w"] <= left["x"] + 1.5:
                candidates.append("right-of")
            if left["y"] + left["h"] <= right["y"] + 1.5:
                candidates.append("above")
            elif right["y"] + right["h"] <= left["y"] + 1.5:
                candidates.append("below")
            for relation in candidates[:1]:
                key = (left["id"], relation, right["id"])
                if key not in seen:
                    seen.add(key)
                    relations.append(list(key))
    return relations[:28]


def derive_motifs(nodes):
    styles = [node["style"] for node in nodes]
    counts = Counter()
    counts["gradient-surface"] = sum(style["fill"] == "gradient" for style in styles)
    counts["solid-surface"] = sum(style["fill"] == "solid" for style in styles)
    counts["outlined-element"] = sum(style["border"] for style in styles)
    counts["rounded-element"] = sum(style["radius"] >= 6 for style in styles)
    counts["shadow-layer"] = sum(style["shadow"] for style in styles)
    counts["clipped-shape"] = sum(style["clip"] for style in styles)
    counts["transformed-element"] = sum(style["transform"] for style in styles)
    counts["svg-visual"] = sum(node["tag"] == "svg" for node in nodes)
    return [{"kind": key, "count": value} for key, value in counts.items() if value]


def derive_typography(nodes, canvas_height):
    values = []
    for node in nodes:
        if node["directChars"] and node["style"]["fontSize"]:
            values.append(node["style"]["fontSize"] / canvas_height * 100)
    values = sorted({round(value, 1) for value in values}, reverse=True)
    return values[:7]


def enrich(seed_id, graph, catalog):
    nodes = [_round_node(node) for node in graph["nodes"]]
    entry = catalog[seed_id]
    role_counts = Counter(node["role"] for node in nodes)
    return {
        "id": seed_id,
        "macro": entry.get("dims", {}).get("layout", "unknown"),
        "source_content": entry.get("dims", {}).get("content", "unknown"),
        "canvas": {key: round(value, 1) for key, value in graph["canvas"].items()},
        "dom_count": graph["dom_count"],
        "nodes": nodes,
        "role_counts": dict(role_counts),
        "relations": derive_relations(nodes),
        "repetitions": derive_repetitions(nodes),
        "motifs": derive_motifs(nodes),
        "type_scale_pct": derive_typography(nodes, graph["canvas"]["height"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=Path, default=DEFAULT_SEEDS)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    catalog = {item["id"]: item for item in json.loads(args.catalog.read_text())}
    seed_paths = sorted(args.seeds.glob("seed_*.html"))
    if args.limit:
        seed_paths = seed_paths[:args.limit]
    output = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1536, "height": 864})
        for index, path in enumerate(seed_paths, 1):
            if path.stem not in catalog:
                continue
            page.goto(path.resolve().as_uri())
            page.wait_for_timeout(30)
            output[path.stem] = enrich(path.stem, page.evaluate(EXTRACT_JS), catalog)
            if index % 50 == 0:
                print(f"  extracted {index}/{len(seed_paths)}", flush=True)
        browser.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
    avg_nodes = sum(len(item["nodes"]) for item in output.values()) / max(len(output), 1)
    print(f"Wrote {len(output)} scene grammars; avg {avg_nodes:.1f} nodes -> {args.out}")


if __name__ == "__main__":
    main()
