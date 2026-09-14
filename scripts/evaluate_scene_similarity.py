#!/usr/bin/env python3
"""Measure whether generated slides occupy a BAMS structural neighborhood.

The score intentionally has two failure modes:
  * below the lower bound: generic drift / insufficient BAMS resemblance;
  * above the upper bound: suspiciously literal geometry/template copying.
"""

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_scene_grammar_library import EXTRACT_JS
from redeck_style.domain.constraints import MIN_TEXT_CONTRAST, FRAGMENT_SHORT_EDGE, FRAGMENT_LONG_EDGE, FRAGMENT_ASPECT_RATIO


SCENES = ROOT / "pattern_library" / "metadata" / "scene_grammar_library.json"


def _ratio(a, b):
    if not a or not b:
        return 0.0
    return min(a, b) / max(a, b)


def _cosine(left, right):
    keys = set(left) | set(right)
    dot = sum(left.get(key, 0) * right.get(key, 0) for key in keys)
    norm_l = math.sqrt(sum(left.get(key, 0) ** 2 for key in keys))
    norm_r = math.sqrt(sum(right.get(key, 0) ** 2 for key in keys))
    return dot / (norm_l * norm_r) if norm_l and norm_r else 0.0


def _occupancy(nodes, grid=4):
    bins = Counter()
    for node in nodes:
        if node["role"] in {"container", "decoration", "separator"}:
            continue
        cx = max(0, min(grid - 1, int((node["x"] + node["w"] / 2) / 100 * grid)))
        cy = max(0, min(grid - 1, int((node["y"] + node["h"] / 2) / 100 * grid)))
        bins[f"{cx}:{cy}"] += min(node["w"] * node["h"], 800) / 800
    return bins


def _geometry_copy(reference, output):
    ref = [node for node in reference if node["role"] not in {"container", "decoration", "separator"}]
    out = [node for node in output if node["role"] not in {"container", "decoration", "separator"}]
    if not ref or not out:
        return 0.0
    matches = []
    for node in out:
        best = 0.0
        for candidate in ref:
            if candidate["role"] != node["role"]:
                continue
            distance = sum(abs(node[key] - candidate[key]) for key in ("x", "y", "w", "h")) / 4
            best = max(best, max(0.0, 1.0 - distance / 7.5))
        matches.append(best)
    return sum(matches) / len(matches)


def _role_counts(nodes):
    return Counter(
        node["role"] for node in nodes
        if node["role"] not in {"container", "decoration", "separator"}
    )


def compare(reference, output):
    ref_nodes, out_nodes = reference["nodes"], output["nodes"]
    dom = _ratio(reference["dom_count"], output["dom_count"])
    node_density = _ratio(len(ref_nodes), len(out_nodes))
    roles = _cosine(_role_counts(ref_nodes), _role_counts(out_nodes))
    occupancy = _cosine(_occupancy(ref_nodes), _occupancy(out_nodes))
    ref_repeat = sum(item["count"] for item in reference.get("repetitions", []))
    out_repeat = sum(item["count"] for item in output.get("repetitions", []))
    rhythm = _ratio(ref_repeat, out_repeat) if ref_repeat and out_repeat else 0.35
    ref_motifs = Counter({item["kind"]: min(item["count"], 8) for item in reference.get("motifs", [])})
    out_motifs = Counter({item["kind"]: min(item["count"], 8) for item in output.get("motifs", [])})
    motifs = _cosine(ref_motifs, out_motifs)
    similarity = (
        dom * 0.12
        + node_density * 0.13
        + roles * 0.20
        + occupancy * 0.25
        + rhythm * 0.15
        + motifs * 0.15
    )
    copy_score = _geometry_copy(ref_nodes, out_nodes)
    return {
        "similarity": round(similarity, 3),
        "copy_score": round(copy_score, 3),
        "components": {
            "dom": round(dom, 3),
            "node_density": round(node_density, 3),
            "semantic_roles": round(roles, 3),
            "spatial_occupancy": round(occupancy, 3),
            "repeat_rhythm": round(rhythm, 3),
            "motifs": round(motifs, 3),
        },
    }


def _enrich_output(graph):
    # Reuse deterministic structural derivation without source metadata.
    from scripts.build_scene_grammar_library import (
        _round_node,
        derive_motifs,
        derive_repetitions,
    )

    nodes = [_round_node(node) for node in graph["nodes"]]
    return {
        "dom_count": graph["dom_count"],
        "nodes": nodes,
        "repetitions": derive_repetitions(nodes),
        "motifs": derive_motifs(nodes),
    }


def _layout_validity(page):
    """Hard rendering gate kept separate from the two BAMS similarity scores."""
    return page.evaluate("""
({minimumContrast, fragmentShortEdge, fragmentLongEdge, fragmentAspectRatio}) => {
  const viewport = {w: 1280, h: 720};
  const visible = el => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0 && r.width > 1 && r.height > 1;
  };
  const informative = el => !el.closest('.deco,[aria-hidden="true"]');
  const label = el => el.getAttribute('data-scene-role') || el.tagName.toLowerCase();
  const selector = el => {
    const parts = [];
    for (let node = el; node; node = node.parentElement) {
      let own = node.id ? '#' + CSS.escape(node.id) : node.tagName.toLowerCase() +
        Array.from(node.classList || []).slice(0,3).map(name => '.' + CSS.escape(name)).join('');
      const siblings = node.parentElement ? Array.from(node.parentElement.children)
        .filter(sibling => sibling.tagName === node.tagName) : [];
      if (!node.id && siblings.length > 1) own += `:nth-of-type(${siblings.indexOf(node)+1})`;
      parts.unshift(own);
      const value = parts.join(' > ');
      if (document.querySelectorAll(value).length === 1) return value;
    }
    return parts.join(' > ');
  };
  const rectData = rect => ({
    x:Math.round(rect.x), y:Math.round(rect.y),
    w:Math.round(rect.width), h:Math.round(rect.height)
  });
  const excerpt = el => (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
  const sourceAssetIssues = Array.from(document.images).flatMap(image => {
    if (!informative(image)) return [];
    const width = image.naturalWidth;
    const height = image.naturalHeight;
    const shortEdge = Math.min(width, height);
    const longEdge = Math.max(width, height);
    let reason = '';
    if (!image.complete || !width || !height) reason = 'unavailable-image';
    else if (shortEdge <= fragmentShortEdge && longEdge >= fragmentLongEdge && longEdge / shortEdge >= fragmentAspectRatio)
      reason = 'suspected-extraction-fragment';
    if (!reason) return [];
    return [{selector:selector(image), source:image.currentSrc || image.src,
      alt:image.alt, intrinsic_width:width, intrinsic_height:height,
      rect:rectData(image.getBoundingClientRect()), reason}];
  });
  const overflow = [];
  const clippedText = [];
  const textCollisions = [];
  const lowContrast = [];
  const lowContrastDetails = [];
  const rgba = value => {
    if (!value || value === 'transparent') return {r:0,g:0,b:0,a:0};
    const hex = value.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (hex) {
      let raw = hex[1];
      if (raw.length === 3) raw = raw.split('').map(c => c + c).join('');
      return {r:parseInt(raw.slice(0,2),16),g:parseInt(raw.slice(2,4),16),b:parseInt(raw.slice(4,6),16),a:1};
    }
    const m = value.match(/rgba?\\(([^)]+)\\)/);
    if (m) {
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return {r:p[0],g:p[1],b:p[2],a:p.length > 3 ? p[3] : 1};
    }
    const srgb = value.match(/color\\(srgb\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)(?:\\s*\\/\\s*([\\d.]+))?\\)/);
    if (srgb) return {
      r:Number(srgb[1])*255,g:Number(srgb[2])*255,b:Number(srgb[3])*255,a:Number(srgb[4] || 1)
    };
    return null;
  };
  const luminance = c => {
    const f = v => {v/=255; return v<=.04045 ? v/12.92 : Math.pow((v+.055)/1.055,2.4)};
    return .2126*f(c.r)+.7152*f(c.g)+.0722*f(c.b);
  };
  const contrast = (a,b) => {const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
  const backgroundSample = el => {
    const s = getComputedStyle(el);
    const solid = rgba(s.backgroundColor);
    if (solid && solid.a >= .85) return solid;
    // Full-canvas gradients cannot be approximated from their first color:
    // the relevant stop depends on element position.  Fall back to the
    // semantic canvas token; local panel/sidebar gradients are homogeneous
    // enough for a representative stop to be meaningful.
    if (el.classList && el.classList.contains('slide')) return null;
    const colors = s.backgroundImage.match(/rgba?\\([^)]*\\)/g) || [];
    const opaque = colors.map(rgba).filter(c => c && c.a >= .85);
    if (opaque.length) return opaque[0];
    const srgb = s.backgroundImage.match(/color\\(srgb\\s+([\\d.]+)\\s+([\\d.]+)\\s+([\\d.]+)(?:\\s*\\/\\s*([\\d.]+))?\\)/);
    if (srgb && Number(srgb[4] || 1) >= .85) {
      return {r:Number(srgb[1])*255,g:Number(srgb[2])*255,b:Number(srgb[3])*255,a:Number(srgb[4] || 1)};
    }
    return null;
  };
  const canvasColor=rgba(getComputedStyle(document.documentElement).getPropertyValue('--surface-canvas').trim());
  const canvas=canvasColor && canvasColor.a>=.85 ? canvasColor : {r:255,g:255,b:255,a:1};
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el) || !informative(el)) continue;
    if (el instanceof SVGElement || el.closest('svg')) continue;
    const r = el.getBoundingClientRect();
    if (r.left < -1 || r.top < -1 || r.right > viewport.w + 1 || r.bottom > viewport.h + 1) {
      overflow.push(label(el));
    }
    const textNodes = Array.from(el.childNodes).filter(
      node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()
    );
    const overflowStyle = getComputedStyle(el);
    const clips = ['hidden', 'clip', 'auto', 'scroll'].includes(overflowStyle.overflowX) ||
                  ['hidden', 'clip', 'auto', 'scroll'].includes(overflowStyle.overflowY);
    if (textNodes.length && clips && el instanceof HTMLElement) {
      const contentRight = r.right - parseFloat(overflowStyle.paddingRight || 0);
      const contentBottom = r.bottom - parseFloat(overflowStyle.paddingBottom || 0);
      for (const node of textNodes) {
        const range = document.createRange();
        range.selectNodeContents(node);
        const tr = range.getBoundingClientRect();
        if (tr.right > contentRight + 2 || tr.bottom > contentBottom + 2 || tr.left < r.left - 2 || tr.top < r.top - 2) {
          clippedText.push(label(el));
          break;
        }
      }
    }
    if (textNodes.length) {
      const fg = rgba(getComputedStyle(el).color);
      let bg = null;
      for (let node = el; node && !bg; node = node.parentElement) {
        bg = backgroundSample(node);
      }
      bg = bg || canvas;
      const painted = fg && {r:fg.r*fg.a+bg.r*(1-fg.a),g:fg.g*fg.a+bg.g*(1-fg.a),b:fg.b*fg.a+bg.b*(1-fg.a)};
      if (painted && contrast(painted, bg) < minimumContrast) {
        lowContrast.push(label(el));
        lowContrastDetails.push({selector:selector(el),text:excerpt(el),rect:rectData(r),
          color:getComputedStyle(el).color,contrast_ratio:Math.round(contrast(painted,bg)*100)/100,minimum:minimumContrast});
      }
    }
  }
  // Compare rendered text fragments rather than element boxes. This catches
  // a subtitle laid over a wrapped heading without flagging normal nested
  // containers or adjacent table cells.
  const textRects = [];
  const textInkRects = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el) || !informative(el)) continue;
    const style = getComputedStyle(el);
    for (const node of el.childNodes) {
      if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (rect.width > 2 && rect.height > 2) {
          textRects.push({el, rect, label:label(el), position:style.position});
        }
      }
      // Graphic/text collisions use word boxes rather than a whole line box.
      // This prevents a connector passing through inter-word whitespace from
      // being reported as if it crossed visible glyphs.
      for (const match of node.textContent.matchAll(/\\S+/g)) {
        const word = document.createRange();
        word.setStart(node, match.index);
        word.setEnd(node, match.index + match[0].length);
        for (const rect of word.getClientRects()) {
          if (rect.width > 2 && rect.height > 2) textInkRects.push({el, rect, text:match[0]});
        }
      }
    }
  }
  const seenCollisions = new Set();
  const textCollisionDetails=[];
  const textClearances = [];
  const seenTextClearance = new Set();
  for (let i = 0; i < textRects.length; i++) {
    for (let j = i + 1; j < textRects.length; j++) {
      const a = textRects[i], b = textRects[j];
      if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      if (a.el.parentElement === b.el.parentElement && a.position === 'static' && b.position === 'static') continue;
      const overlapW = Math.min(a.rect.right,b.rect.right)-Math.max(a.rect.left,b.rect.left);
      const overlapH = Math.min(a.rect.bottom,b.rect.bottom)-Math.max(a.rect.top,b.rect.top);
      if (overlapW > 5 && overlapH > 3) {
        const key = [selector(a.el),selector(b.el)].sort().join(' ↔ ');
        if (!seenCollisions.has(key)) {
          seenCollisions.add(key);
          textCollisions.push(key);
          textCollisionDetails.push({first:{selector:selector(a.el),text:excerpt(a.el),rect:rectData(a.rect)},
            second:{selector:selector(b.el),text:excerpt(b.el),rect:rectData(b.rect)}});
        }
      }
      // A small absolutely positioned relation label wedged into a body
      // sentence is not fixed merely because their boxes stop intersecting.
      // Normal inline text and closely set chart/table rows are excluded.
      const small = [a,b].find(item => ['absolute','fixed'].includes(item.position) &&
        parseFloat(getComputedStyle(item.el).fontSize) <= 14 && !(item.el instanceof SVGElement));
      const body = small === a ? b : a;
      if (small && parseFloat(getComputedStyle(body.el).fontSize) >= 15 &&
          overlapH >= Math.min(a.rect.height,b.rect.height)*.5 && overlapW <= 5) {
        const gap = Math.max(0,-overlapW);
        const key = [selector(a.el),selector(b.el)].sort().join('|');
        if (gap < 8 && !seenTextClearance.has(key)) {
          seenTextClearance.add(key);
          textClearances.push({label:{selector:selector(small.el),text:excerpt(small.el),rect:rectData(small.rect)},
            body:{selector:selector(body.el),text:excerpt(body.el),rect:rectData(body.rect)},gap_px:Math.round(gap*100)/100,minimum_px:8});
        }
      }
    }
  }
  // Detect a floating label squeezed between two separate prose groups even
  // if both gaps narrowly exceed the single-neighbor threshold. This is a
  // relationship ambiguity, not a rule for ordinary inline labels or tables.
  const textAssociations = [];
  const seenAssociations = new Set();
  for (const small of textRects) {
    if (!['absolute','fixed'].includes(small.position) || small.el instanceof SVGElement ||
        parseFloat(getComputedStyle(small.el).fontSize) > 14) continue;
    const neighbors = textRects.filter(body => body.el !== small.el && !body.el.contains(small.el) &&
      !small.el.contains(body.el) && !(body.el instanceof SVGElement) && parseFloat(getComputedStyle(body.el).fontSize) >= 15 &&
      Math.min(body.rect.bottom,small.rect.bottom)-Math.max(body.rect.top,small.rect.top) >= Math.min(body.rect.height,small.rect.height)*.5);
    const left = neighbors.find(body => small.rect.left-body.rect.right >= 0 && small.rect.left-body.rect.right < 24);
    const right = neighbors.find(body => body.rect.left-small.rect.right >= 0 && body.rect.left-small.rect.right < 24);
    const key = selector(small.el);
    if (left && right && left.el !== right.el && !seenAssociations.has(key)) {
      seenAssociations.add(key);
      textAssociations.push({selector:key,text:excerpt(small.el),rect:rectData(small.rect),
        left:selector(left.el),right:selector(right.el),reason:'floating label wedged between two prose groups; relocate into its own connector lane'});
    }
  }
  // Lines and arrows are first-class layout objects. The previous detector
  // ignored them, so an SVG connector or CSS rule could visibly strike text
  // while the page still reported zero issues.
  const graphicSegments = [];
  const graphicBoxes = [];
  const arrowPaths = new Map();
  const addSegment = (owner, kind, x1, y1, x2, y2, width=1) => {
    if ([x1,y1,x2,y2,width].every(Number.isFinite)) {
      graphicSegments.push({owner,kind,x1,y1,x2,y2,width});
    }
  };
  const addBox = (owner, kind, left, top, right, bottom) => {
    if ([left,top,right,bottom].every(Number.isFinite) && right-left > .5 && bottom-top > .5) {
      graphicBoxes.push({owner,kind,left,top,right,bottom});
    }
  };
  const opaque = value => {
    const parsed = rgba(value || '');
    return parsed && parsed.a > .08;
  };
  const borderSegments = (el, style, rect, kind='css-border') => {
    const sides = [
      ['Top',rect.left,rect.top,rect.right,rect.top],
      ['Right',rect.right,rect.top,rect.right,rect.bottom],
      ['Bottom',rect.left,rect.bottom,rect.right,rect.bottom],
      ['Left',rect.left,rect.top,rect.left,rect.bottom],
    ];
    for (const [side,x1,y1,x2,y2] of sides) {
      const width = parseFloat(style['border'+side+'Width']) || 0;
      if (width >= 1 && style['border'+side+'Style'] !== 'none' && opaque(style['border'+side+'Color'])) {
        // CSS paints borders inside the border box, not centered on its edge.
        const dx = side === 'Left' ? width/2 : side === 'Right' ? -width/2 : 0;
        const dy = side === 'Top' ? width/2 : side === 'Bottom' ? -width/2 : 0;
        addSegment(el,kind,x1+dx,y1+dy,x2+dx,y2+dy,width);
      }
    }
  };
  for (const el of document.body.querySelectorAll('*:not(svg):not(svg *)')) {
    if (!visible(el)) continue;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    borderSegments(el,style,rect);
    // A standalone thin filled element is a rule even when implemented as a
    // background instead of a border. Text-bearing badges are excluded.
    if (!(el.textContent || '').trim() && opaque(style.backgroundColor)) {
      if (rect.width >= 20 && rect.height <= 12) addBox(el,'css-rule',rect.left,rect.top,rect.right,rect.bottom);
      if (rect.height >= 20 && rect.width <= 12) addBox(el,'css-rule',rect.left,rect.top,rect.right,rect.bottom);
    }
    // Absolutely/fixed positioned pseudo-elements have recoverable geometry.
    // This covers the common CSS rule and arrowhead implementations.
    for (const pseudo of ['::before','::after']) {
      const ps = getComputedStyle(el,pseudo);
      let content = ps.content || '';
      if (content === 'none' || ps.display === 'none' || ps.visibility === 'hidden' || Number(ps.opacity) === 0) continue;
      if (!['absolute','fixed'].includes(ps.position)) continue;
      content = content.replace(/^['"]|['"]$/g,'');
      const bl=parseFloat(ps.borderLeftWidth)||0, br=parseFloat(ps.borderRightWidth)||0;
      const bt=parseFloat(ps.borderTopWidth)||0, bb=parseFloat(ps.borderBottomWidth)||0;
      let width=parseFloat(ps.width), height=parseFloat(ps.height);
      if (!Number.isFinite(width)) width = content ? Math.max(parseFloat(ps.fontSize)||12, content.length*(parseFloat(ps.fontSize)||12)*.65) : 0;
      if (!Number.isFinite(height)) height = content ? (parseFloat(ps.lineHeight)||parseFloat(ps.fontSize)||0) : 0;
      width += bl+br; height += bt+bb;
      let left=parseFloat(ps.left), right=parseFloat(ps.right), top=parseFloat(ps.top), bottom=parseFloat(ps.bottom);
      const base = ps.position === 'fixed' ? {left:0,top:0,right:viewport.w,bottom:viewport.h} : rect;
      let x = Number.isFinite(left) ? base.left+left : (Number.isFinite(right) ? base.right-right-width : NaN);
      let y = Number.isFinite(top) ? base.top+top : (Number.isFinite(bottom) ? base.bottom-bottom-height : NaN);
      if (!Number.isFinite(x) || !Number.isFinite(y) || width <= 0 || height <= 0) continue;
      borderSegments(el,ps,{left:x,top:y,right:x+width,bottom:y+height},'pseudo-border');
      const arrowText = /[→←↑↓↔↕➜➝➞➟➠➤▶◀]/.test(content);
      const triangle = (bl+br+bt+bb) >= 6 && (parseFloat(ps.width)||0) <= 4 && (parseFloat(ps.height)||0) <= 4;
      const slender = (width >= 15 && height <= 12) || (height >= 15 && width <= 12);
      if (arrowText || triangle || (slender && opaque(ps.backgroundColor))) addBox(el,'pseudo-'+pseudo.slice(2),x,y,x+width,y+height);
    }
  }
  for (const shape of document.querySelectorAll('svg path,svg line,svg polyline,svg polygon,svg rect')) {
    if (shape.closest('defs,marker,clipPath,mask,symbol')) continue;
    const style = getComputedStyle(shape);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
    const paintedStroke = style.stroke !== 'none' && opaque(style.stroke) && Number(style.strokeOpacity) > .08;
    const paintedFill = style.fill !== 'none' && opaque(style.fill);
    if (!paintedStroke && !paintedFill) continue;
    // Filled arrowheads and compact symbols may not have a stroke. Capture
    // their actual painted footprint separately from connector centerlines.
    if (paintedFill && ['path','polygon','rect'].includes(shape.tagName.toLowerCase())) {
      const bounds=shape.getBoundingClientRect();
      if (bounds.width>1 && bounds.height>1 && bounds.width<=64 && bounds.height<=64) {
        addBox(shape,'svg-filled-mark',bounds.left,bounds.top,bounds.right,bounds.bottom);
      }
    }
    if (!paintedStroke) continue;
    const width = Math.max(.5,parseFloat(style.strokeWidth)||1);
    if (typeof shape.getTotalLength !== 'function' || typeof shape.getPointAtLength !== 'function') continue;
    let length;
    try { length=shape.getTotalLength(); } catch (_) { continue; }
    const matrix=shape.getScreenCTM();
    if (!matrix || !Number.isFinite(length) || length <= 0) continue;
    const viewportBox=shape.ownerSVGElement?.viewBox?.baseVal;
    const svgBounds=shape.ownerSVGElement?.getBoundingClientRect();
    const diagonal=Math.hypot(viewportBox?.width || svgBounds?.width || 0,viewportBox?.height || svgBounds?.height || 0)/Math.SQRT2;
    const pathScale=shape.hasAttribute('pathLength') && Number(shape.getAttribute('pathLength'))>0
      ? length/Number(shape.getAttribute('pathLength')) : 1;
    const dashLength=value => parseFloat(value)*(value.includes('%') ? diagonal/100 : pathScale);
    let dashes=style.strokeDasharray === 'none' ? [] : style.strokeDasharray.split(/[ ,]+/).filter(Boolean).map(dashLength);
    if ((shape.tagName.toLowerCase()==='path' && ((shape.getAttribute('d')||'').match(/[mM]/g)||[]).length>1) ||
        (style.strokeLinecap!=='butt' && dashes.includes(0))) dashes=[];
    if (dashes.length%2) dashes=dashes.concat(dashes);
    const cycle=dashes.reduce((total,value)=>total+value,0);
    const intervals=[];
    if (cycle>0 && dashes.every(value=>Number.isFinite(value) && value>=0)) {
      const offset=dashLength(style.strokeDashoffset || '0');
      let cursor=-((offset%cycle+cycle)%cycle), index=0;
      while (cursor<length && index<10000) {
        const end=cursor+dashes[index%dashes.length];
        if (index%2===0 && end>0 && end>cursor) intervals.push([Math.max(0,cursor),Math.min(length,end)]);
        cursor=end;
        index++;
      }
      if (cursor<length) intervals.push([Math.max(0,cursor),length]);
    } else intervals.push([0,length]);
    const screenPoint=distance => {
      const local=shape.getPointAtLength(distance);
      return new DOMPoint(local.x,local.y).matrixTransform(matrix);
    };
    const first=screenPoint(0), last=screenPoint(length);
    for (const [start,end] of intervals) {
      const steps=Math.max(1,Math.min(400,Math.ceil((end-start)/4)));
      let previous=null, previousLocal=null;
      for (let index=0;index<=steps;index++) {
        const local=shape.getPointAtLength(start+(end-start)*index/steps);
        const point=new DOMPoint(local.x,local.y).matrixTransform(matrix);
        const continuous=previousLocal && Math.hypot(local.x-previousLocal.x,local.y-previousLocal.y)<=(end-start)/steps+.05;
        if (previous && continuous) addSegment(shape,'svg-connector',previous.x,previous.y,point.x,point.y,width);
        previous=point;
        previousLocal=local;
      }
    }
    // Marker geometry is rendered outside the path centerline. Browsers do
    // not expose its painted bounds, so conservatively reserve the endpoint
    // footprint using stroke-scaled dimensions.
    const markerRadius=Math.max(5,width*3);
    if (style.markerStart && style.markerStart !== 'none' && first) {
      addBox(shape,'svg-marker-start',first.x-markerRadius,first.y-markerRadius,first.x+markerRadius,first.y+markerRadius);
    }
    if (style.markerEnd && style.markerEnd !== 'none' && last) {
      addBox(shape,'svg-marker-end',last.x-markerRadius,last.y-markerRadius,last.x+markerRadius,last.y+markerRadius);
    }
    if ((style.markerStart && style.markerStart !== 'none') ||
        (style.markerEnd && style.markerEnd !== 'none')) {
      arrowPaths.set(shape,{first,last,radius:markerRadius,
        start:style.markerStart && style.markerStart !== 'none',end:style.markerEnd && style.markerEnd !== 'none'});
    }
  }
  // Only independent separators are obstacles here, not enclosed node
  // boundaries or chart grids. Docking on nodes is intentional; docking on
  // an independent decorative separator is not a semantic attachment.
  const ruleSegments = graphicSegments.filter(segment => {
    if (segment.kind === 'pseudo-border') return true;
    if (segment.kind !== 'css-border') return false;
    const style = getComputedStyle(segment.owner);
    const sides = ['Top','Right','Bottom','Left'].filter(side =>
      parseFloat(style['border'+side+'Width']) >= 1 &&
      style['border'+side+'Style'] !== 'none' && opaque(style['border'+side+'Color']));
    return sides.length === 1;
  });
  for (const box of graphicBoxes) {
    if (box.kind !== 'css-rule' && !box.kind.startsWith('pseudo-')) continue;
    const w=box.right-box.left,h=box.bottom-box.top;
    if (w >= 40 && h <= 8) ruleSegments.push({owner:box.owner,kind:box.kind,
      x1:box.left,y1:(box.top+box.bottom)/2,x2:box.right,y2:(box.top+box.bottom)/2,width:h});
    else if (h >= 40 && w <= 8) ruleSegments.push({owner:box.owner,kind:box.kind,
      x1:(box.left+box.right)/2,y1:box.top,x2:(box.left+box.right)/2,y2:box.bottom,width:w});
  }
  const connectorRuleCollisions=[];
  const seenConnectorRule=new Set();
  const intersect = (a,b) => {
    const ax=a.x2-a.x1,ay=a.y2-a.y1,bx=b.x2-b.x1,by=b.y2-b.y1;
    const cross=ax*by-ay*bx;
    if (Math.abs(cross)<1e-6) return null;
    const dx=b.x1-a.x1,dy=b.y1-a.y1;
    const t=(dx*by-dy*bx)/cross,u=(dx*ay-dy*ax)/cross;
    return t>=0 && t<=1 && u>0 && u<1 ? {x:a.x1+t*ax,y:a.y1+t*ay} : null;
  };
  for (const segment of graphicSegments) {
    const arrow=arrowPaths.get(segment.owner);
    if (!arrow) continue;
    for (const rule of ruleSegments) {
      if (rule.owner === segment.owner) continue;
      const point=intersect(segment,rule);
      if (!point) continue;
      const key=selector(segment.owner)+'|'+selector(rule.owner);
      if (seenConnectorRule.has(key)) continue;
      seenConnectorRule.add(key);
      connectorRuleCollisions.push({
        connector:{selector:selector(segment.owner),kind:'arrow-path'},
        rule:{selector:selector(rule.owner),kind:rule.kind},
        selector:selector(segment.owner),
        rect:{x:Math.round(point.x-12),y:Math.round(point.y-12),w:24,h:24},
        reason:'arrow traverses an independent separator; reroute the connector or shorten the decorative rule, preserving endpoints and text'
      });
    }
  }
  const pointSegmentDistance=(point,segment) => {
    const dx=segment.x2-segment.x1,dy=segment.y2-segment.y1;
    const t=Math.max(0,Math.min(1,((point.x-segment.x1)*dx+(point.y-segment.y1)*dy)/(dx*dx+dy*dy || 1)));
    return Math.hypot(point.x-segment.x1-t*dx,point.y-segment.y1-t*dy);
  };
  for (const [shape,arrow] of arrowPaths) {
    for (const [enabled,end] of [[arrow.start,arrow.first],[arrow.end,arrow.last]]) {
      if (!enabled) continue;
      for (const rule of ruleSegments) {
        const key=selector(shape)+'|'+selector(rule.owner);
        if (seenConnectorRule.has(key) || pointSegmentDistance(end,rule)>=arrow.radius+8+rule.width/2) continue;
        seenConnectorRule.add(key);
        connectorRuleCollisions.push({selector:selector(shape),
          connector:{selector:selector(shape),kind:'arrowhead'},rule:{selector:selector(rule.owner),kind:rule.kind},
          rect:{x:Math.round(end.x-12),y:Math.round(end.y-12),w:24,h:24},
          reason:'arrowhead touches or crowds an independent decorative separator; leave a clear gap, not a false attachment to the rule'});
      }
    }
  }
  // An endpoint far inside a later-painted opaque panel loses its arrowhead.
  // Use the browser paint hit stack, not box overlap: a connector above a
  // panel or docking on its boundary is valid. Pointer-events:none shapes
  // are left to visual review when the stack cannot identify their layer.
  const connectorOcclusions=[];
  for (const [shape,arrow] of arrowPaths) {
    for (const [enabled,end] of [[arrow.start,arrow.first],[arrow.end,arrow.last]]) {
      if (!enabled) continue;
      const stack=document.elementsFromPoint(end.x,end.y);
      const layer=stack.indexOf(shape);
      if (layer<0) continue;
      const cover=stack.slice(0,layer).find(el => {
        if (el instanceof SVGElement || el.contains(shape)) return false;
        const s=getComputedStyle(el),r=el.getBoundingClientRect(),color=rgba(s.backgroundColor);
        return color && color.a>=.85 && Number(s.opacity)>=.85 &&
          Math.min(end.x-r.left,r.right-end.x,end.y-r.top,r.bottom-end.y)>arrow.radius;
      });
      if (!cover) continue;
      connectorOcclusions.push({selector:selector(shape),connector:{selector:selector(shape),kind:'arrowhead'},
        cover:{selector:selector(cover)},rect:{x:Math.round(end.x-12),y:Math.round(end.y-12),w:24,h:24},
        reason:'arrow endpoint is hidden well inside a later-painted opaque panel; dock visibly outside its edge rather than drawing through the panel or its text'});
    }
  }
  const graphicGeometry = new Map();
  for (const item of [...graphicSegments,...graphicBoxes]) {
    const key=selector(item.owner);
    const left=item.left ?? Math.min(item.x1,item.x2)-item.width/2;
    const right=item.right ?? Math.max(item.x1,item.x2)+item.width/2;
    const top=item.top ?? Math.min(item.y1,item.y2)-item.width/2;
    const bottom=item.bottom ?? Math.max(item.y1,item.y2)+item.width/2;
    const previous=graphicGeometry.get(key);
    graphicGeometry.set(key,{selector:key,kind:item.kind,
      left:Math.min(left,previous?.left ?? left),right:Math.max(right,previous?.right ?? right),
      top:Math.min(top,previous?.top ?? top),bottom:Math.max(bottom,previous?.bottom ?? bottom)});
  }
  const inkRect = rect => {
    const verticalInset=Math.min(3,Math.max(1,rect.height*.12));
    return {left:rect.left+.5,right:rect.right-.5,top:rect.top+verticalInset,bottom:rect.bottom-verticalInset};
  };
  const segmentHitsRect = (segment, rect) => {
    const r=inkRect(rect), pad=segment.width/2;
    const left=r.left-pad,right=r.right+pad,top=r.top-pad,bottom=r.bottom+pad;
    let t0=0,t1=1;
    const dx=segment.x2-segment.x1,dy=segment.y2-segment.y1;
    for (const [p,q] of [[-dx,segment.x1-left],[dx,right-segment.x1],[-dy,segment.y1-top],[dy,bottom-segment.y1]]) {
      if (p===0 && q<0) return false;
      if (p!==0) { const t=q/p; if (p<0) { if (t>t1) return false; t0=Math.max(t0,t); } else { if (t<t0) return false; t1=Math.min(t1,t); } }
    }
    return true;
  };
  const boxHitsRect = (box, rect) => {
    const r=inkRect(rect);
    return Math.min(box.right,r.right)-Math.max(box.left,r.left)>1 && Math.min(box.bottom,r.bottom)-Math.max(box.top,r.top)>1;
  };
  const graphicTextCollisions=[];
  const graphicTextClearances=[];
  const backgroundLabelOverlaps=[];
  const seenGraphicText=new Set();
  const seenBackgroundLabels=new Set();
  const seenClearance=new Set();
  const recordGraphicHit=(graphic,text) => {
    // Include parent borders: overflowing descendant glyphs can cross them.
    const key=graphic.kind+'|'+selector(graphic.owner)+'|'+selector(text.el);
    if (seenGraphicText.has(key)) return;
    if (graphic.kind==='css-rule') {
      const track=graphic.owner.getBoundingClientRect();
      const background=rgba(getComputedStyle(graphic.owner).backgroundColor);
      const foreground=rgba(getComputedStyle(text.el).color);
      let backing=canvas;
      for (let parent=graphic.owner.parentElement;parent;parent=parent.parentElement) {
        const sample=backgroundSample(parent);
        if (sample) { backing=sample; break; }
      }
      const blended=background && {r:background.r*background.a+backing.r*(1-background.a),
        g:background.g*background.a+backing.g*(1-background.a),b:background.b*background.a+backing.b*(1-background.a)};
      const fills=Array.from(graphic.owner.children).filter(child=>{
        const bounds=child.getBoundingClientRect();
        const color=rgba(getComputedStyle(child).backgroundColor);
        return visible(child) && !(child.textContent||'').trim() && color && color.a>=.85 &&
          bounds.width>10 && bounds.width<=track.width && bounds.height>=track.height*.8 &&
          bounds.left>=track.left-.5 && bounds.right<=track.right+.5 &&
          bounds.top>=track.top-.5 && bounds.bottom<=track.bottom+.5;
      });
      if (track.width>=track.height*5 && blended && foreground && foreground.a>=.85 && fills.length===1 &&
          contrast(blended,backing)<1.5 && contrast(foreground,blended)>=minimumContrast &&
          !boxHitsRect(fills[0].getBoundingClientRect(),text.rect)) {
        if (!seenBackgroundLabels.has(key)) {
          seenBackgroundLabels.add(key);
          backgroundLabelOverlaps.push({graphic:{kind:graphic.kind,selector:selector(graphic.owner)},
            text:{selector:selector(text.el),text:text.text,rect:rectData(text.rect)},reason:'readable-label-on-low-contrast-track'});
        }
        return;
      }
    }
    seenGraphicText.add(key);
    graphicTextCollisions.push({
      graphic:{kind:graphic.kind,selector:selector(graphic.owner)},
      text:{selector:selector(text.el),text:text.text,rect:rectData(text.rect)}
    });
  };
  for (const text of textInkRects) {
    for (const segment of graphicSegments) if (segmentHitsRect(segment,text.rect)) recordGraphicHit(segment,text);
    for (const box of graphicBoxes) if (boxHitsRect(box,text.rect)) recordGraphicHit(box,text);
  }
  for (const text of textInkRects) {
    const style=getComputedStyle(text.el);
    const displayType=parseFloat(style.fontSize)>=48;
    const compactLabel=parseFloat(style.fontSize)<=18 && style.textAlign==='center' &&
      style.textTransform==='uppercase' && text.text.length<=80;
    if (!displayType && !compactLabel) continue;
    const minimumGap=displayType ? 12 : 4;
    for (const segment of graphicSegments) {
      if (segment.kind !== 'css-border' || Math.abs(segment.x1-segment.x2) > .1 || Math.abs(segment.y2-segment.y1) < 40) continue;
      const key=segment.kind+'|'+selector(segment.owner)+'|'+selector(text.el);
      if (seenGraphicText.has(key) || seenClearance.has(key)) continue;
      if (Math.min(Math.max(segment.y1,segment.y2),text.rect.bottom-3) <= Math.max(Math.min(segment.y1,segment.y2),text.rect.top+3)) continue;
      const gap=Math.max(0, segment.x1 >= text.rect.right ? segment.x1-segment.width/2-text.rect.right : text.rect.left-segment.x1-segment.width/2);
      if (gap >= minimumGap) continue;
      seenClearance.add(key);
      graphicTextClearances.push({graphic:{kind:segment.kind,selector:selector(segment.owner)},
        text:{selector:selector(text.el),text:text.text,rect:rectData(text.rect)},gap_px:Math.round(gap*100)/100,minimum_px:minimumGap});
    }
  }
  const textScaleCache=new Map();
  const textScale=element => {
    if (textScaleCache.has(element)) return textScaleCache.get(element);
    let matrix=typeof element.getScreenCTM==='function' ? element.getScreenCTM() : null;
    if (!matrix) {
      matrix=new DOMMatrix();
      for (let ancestor=element;ancestor;ancestor=ancestor.parentElement) {
        const style=getComputedStyle(ancestor);
        const scalar=value => parseFloat(value)/(value.endsWith('%') ? 100 : 1);
        const scales=style.scale && style.scale!=='none' ? style.scale.split(/ +/).map(scalar) : [1];
        const zoom=style.zoom && style.zoom!=='normal' ? scalar(style.zoom) : 1;
        let individual=new DOMMatrix();
        if (style.rotate && style.rotate!=='none') {
          const parts=style.rotate.split(/ +/);
          const angleText=parts.pop();
          const degrees=parseFloat(angleText)*(angleText.endsWith('turn') ? 360 :
            angleText.endsWith('grad') ? .9 : angleText.endsWith('rad') ? 180/Math.PI : 1);
          const axes={x:[1,0,0],y:[0,1,0],z:[0,0,1]};
          const axis=parts.length===0 ? axes.z : parts.length===1 ? axes[parts[0]] : parts.map(Number);
          individual=individual.rotateAxisAngle(...axis,degrees);
        }
        const transform=style.transform==='none' ? new DOMMatrix() : new DOMMatrix(style.transform);
        individual=individual.scale(scales[0]*zoom,(scales[1] ?? scales[0])*zoom,scales[2] ?? 1);
        matrix=individual.multiply(transform).multiply(matrix);
      }
    }
    const result={x:Math.hypot(matrix.a,matrix.b),y:Math.hypot(matrix.c,matrix.d)};
    textScaleCache.set(element,result);
    return result;
  };
  const typographyCache=new Map();
  const boundedPanel=element => {
    for (let ancestor=element.parentElement; ancestor && ancestor!==document.body; ancestor=ancestor.parentElement) {
      const style=getComputedStyle(ancestor), rect=ancestor.getBoundingClientRect();
      const framed=parseFloat(style.borderTopWidth)>0 || parseFloat(style.borderLeftWidth)>0;
      if (framed && rect.width>=100 && rect.width<=660 && rect.height>=40 && rect.height<=720) return ancestor;
    }
    return null;
  };
  const typography=element => {
    if (typographyCache.has(element)) return typographyCache.get(element);
    const style=getComputedStyle(element);
    const text=(element.innerText || element.textContent || '').trim();
    const semantic=element.closest('h1,h2,h3,h4,h5,h6,p,li,td,th,small,[data-level],[role="heading"]') || element;
    const level=semantic.getAttribute('data-level');
    const tag=semantic.tagName.toLowerCase();
    const font=parseFloat(style.fontSize);
    const short=text.length<=90 && text.split(/\\s+/).length<=12;
    let role='unknown';
    if (tag==='h1') role='title';
    else if (/^h[2-6]$/.test(tag) || semantic.getAttribute('role')==='heading') role='heading';
    else if (level==='section') role='label';
    else if (level==='note' || tag==='small' || element.closest('.note,[data-ink="annotation"]')) role='note';
    else if (level==='body' || ['p','li','td'].includes(tag)) role='body';
    else if (short && font>=24 && parseFloat(style.fontWeight)>=600 && element.closest('aside,[data-style-role="edge-band"]')) role='sidebar_heading';
    else if (level==='display' || (short && font>=24 && parseFloat(style.fontWeight)>=600 && element.closest('article'))) role='heading';
    else if (tag==='th' || element.closest('figcaption')) role='label';
    if (tag==='td') role='table_cell';
    else if (role==='body' && ['p','li'].includes(tag) && font<=16 && boundedPanel(element)) role='supporting_copy';
    else if (/^h[2-6]$/.test(tag) && font<=24 && boundedPanel(element)) role='panel_heading';
    if (element.closest('svg text')) role='svg_label';
    if (/^sources?\\s*:/i.test(text) && element.closest('footer,.source,.footer')) role='citation';
    let container=element;
    while (container.parentElement && (getComputedStyle(container).display==='inline' || !container.clientWidth)) container=container.parentElement;
    const contentWidth=target => {
      const css=getComputedStyle(target);
      return Math.max(0,target.clientWidth-parseFloat(css.paddingLeft || 0)-parseFloat(css.paddingRight || 0));
    };
    let available=contentWidth(container);
    if (container.parentElement) available=Math.min(available,contentWidth(container.parentElement));
    const context=document.createElement('canvas').getContext('2d');
    context.font=style.fontWeight+' '+style.fontSize+' '+style.fontFamily;
    const tracking=parseFloat(style.letterSpacing) || 0;
    context.letterSpacing=tracking+'px';
    const words=text.split(/\\s+/).filter(Boolean);
    const wordWidth=Math.max(0,...words.map(word=>context.measureText(word).width));
    const result={role,role_basis:{tag,level,contextual:!['h1','h2','h3','h4','h5','h6','p','li','td','th','small'].includes(tag)},
      tracking_px:tracking,line_height_px:parseFloat(style.lineHeight) || null,
      available_width_px:Math.round(available*100)/100,max_word_width_px:Math.round(wordWidth*100)/100};
    typographyCache.set(element,result);
    return result;
  };
  const tableCellOverflows=[];
  for (const cell of document.querySelectorAll('td,th')) {
    const cellRect=cell.getBoundingClientRect(), style=getComputedStyle(cell);
    if (cellRect.width<=0 || cellRect.height<=0 || style.visibility==='hidden' || style.display==='none') continue;
    const left=cellRect.left+parseFloat(style.borderLeftWidth)+parseFloat(style.paddingLeft);
    const right=cellRect.right-parseFloat(style.borderRightWidth)-parseFloat(style.paddingRight);
    const walker=document.createTreeWalker(cell,NodeFilter.SHOW_TEXT), overflow=[];
    let node;
    while (node=walker.nextNode()) {
      if (node.parentElement.closest('td,th')!==cell) continue;
      const textStyle=getComputedStyle(node.parentElement);
      if (textStyle.visibility==='hidden' || textStyle.display==='none' || Number(textStyle.opacity)===0) continue;
      for (const match of node.textContent.matchAll(/\\S+/g)) {
        const range=document.createRange();
        range.setStart(node,match.index);
        range.setEnd(node,match.index+match[0].length);
        for (const rect of range.getClientRects()) {
          if (rect.width>0 && rect.height>0 && (rect.left<left-1 || rect.right>right+1)) {
            overflow.push({text:match[0],rect:rectData(rect)});
          }
        }
      }
    }
    if (overflow.length) tableCellOverflows.push({selector:selector(cell),text:excerpt(cell),rect:rectData(cellRect),
      content_left:left,content_right:right,word_count:overflow.length,words:overflow.slice(0,4)});
  }
  return {
    source_asset_issue_count: sourceAssetIssues.length,
    source_asset_issue_details: sourceAssetIssues,
    table_cell_overflow_count: tableCellOverflows.length,
    table_cell_overflow_details: tableCellOverflows,
    overflow_count: overflow.length,
    text_clip_count: clippedText.length,
    text_collision_count: textCollisions.length,
    overflow_roles: overflow.slice(0, 8),
    clipped_roles: clippedText.slice(0, 8),
    text_collision_roles: textCollisions.slice(0, 8),
    text_collision_details: textCollisionDetails,
    graphic_text_collision_count: graphicTextCollisions.length,
    connector_rule_collision_count: connectorRuleCollisions.length,
    connector_occlusion_count: connectorOcclusions.length,
    connector_occlusion_details: connectorOcclusions.slice(0,8),
    connector_rule_collision_details: connectorRuleCollisions.slice(0,8),
    graphic_geometry: Array.from(graphicGeometry.values()).slice(0,160).map(item => ({
      selector:item.selector,kind:item.kind,rect:rectData({x:item.left,y:item.top,width:item.right-item.left,height:item.bottom-item.top})
    })),
    graphic_text_collision_roles: graphicTextCollisions.slice(0,8).map(item =>
      item.graphic.kind+' '+item.graphic.selector+' ↔ '+item.text.selector
    ),
    graphic_text_collision_details: graphicTextCollisions,
    background_label_overlaps: backgroundLabelOverlaps,
    graphic_text_clearance_count: graphicTextClearances.length,
    graphic_text_clearance_details: graphicTextClearances.slice(0,8),
    text_clearance_count: textClearances.length,
    text_clearance_details: textClearances.slice(0,8),
    text_association_count: textAssociations.length,
    text_association_details: textAssociations.slice(0,8),
    low_contrast_count: lowContrast.length,
    low_contrast_roles: lowContrast.slice(0, 8),
    low_contrast_details: lowContrastDetails.slice(0,64),
    table_capacity: Array.from(document.querySelectorAll('table')).map(table => {
      const rows=Array.from(table.rows), cells=rows.flatMap(row=>Array.from(row.cells));
      const spans=cells.some(cell=>cell.colSpan!==1 || cell.rowSpan!==1);
      const count=Math.max(0,...rows.map(row=>row.cells.length));
      return {selector:selector(table),width_px:table.getBoundingClientRect().width,
        requires_span_mapping:spans,columns:spans ? [] : Array.from({length:count},(_,index)=>{
          const targets=rows.map(row=>row.cells[index]).filter(Boolean);
          const observations=targets.map(cell=>{
            const metrics=typography(cell), style=getComputedStyle(cell);
            const padding=parseFloat(style.paddingLeft)+parseFloat(style.paddingRight);
            return {selector:selector(cell),text:excerpt(cell),font_px:parseFloat(style.fontSize),
              required_width_px:Math.ceil(metrics.max_word_width_px+padding+2),
              actual_width_px:Math.round(cell.getBoundingClientRect().width*100)/100};
          });
          const critical=observations.reduce((left,right)=>left.required_width_px>right.required_width_px ? left:right);
          return {index,header:excerpt(targets[0]),actual_width_px:critical.actual_width_px,
            required_width_px:critical.required_width_px,critical_selector:critical.selector,
            critical_text:critical.text,critical_font_px:critical.font_px,
            deficit_px:Math.max(0,Math.round((critical.required_width_px-critical.actual_width_px)*100)/100)};
        })};
    }).slice(0,12),
    region_geometry: Array.from(document.body.querySelectorAll('*')).filter(element => {
      const style=getComputedStyle(element), rect=element.getBoundingClientRect();
      return rect.width>=120 && rect.height>=45 && !element.closest('svg') &&
        (['grid','flex','table'].includes(style.display) || parseFloat(style.borderTopWidth)>0 || style.overflowY==='hidden');
    }).slice(0,48).map(element => {
      const style=getComputedStyle(element), rect=element.getBoundingClientRect();
      return {selector:selector(element),parent_selector:selector(element.parentElement),rect:rectData(rect),
        display:style.display,columns:style.gridTemplateColumns,rows:style.gridTemplateRows,
        gap:style.gap,padding:style.padding,overflow:style.overflow,
        content_height_px:element.scrollHeight,available_canvas_height_px:Math.max(0,720-rect.top),
        overflow_y_px:Math.max(0,element.scrollHeight-element.clientHeight),
        child_selectors:Array.from(element.children).slice(0,12).map(selector)};
    }),
    // Stable targets for screenshot review; no reference image or template.
    text_geometry: Array.from(new Map(textRects.map(item=>[item.el,item])).values()).map(item => ({selector:selector(item.el),text:excerpt(item.el),
      font_px:parseFloat(getComputedStyle(item.el).fontSize),font_scale:textScale(item.el),
      viewport_only_scaling:!!item.el.closest('svg') && (()=>{
        for (let element=item.el; element; element=element.parentElement) {
          const style=getComputedStyle(element);
          if (style.transform!=='none' || !['none','1','1 1'].includes(style.scale || 'none') ||
              !['normal','1'].includes(style.zoom || '1') || element.hasAttribute('transform')) return false;
        }
        return true;
      })(),
      layout_parent_selector:item.el.tagName.toLowerCase()==='tspan' && item.el.closest('text') ? selector(item.el.closest('text')) : null,
      typography:typography(item.el),rect:rectData(item.rect)})),
  };
}
""", {"minimumContrast": MIN_TEXT_CONTRAST, "fragmentShortEdge": FRAGMENT_SHORT_EDGE,
      "fragmentLongEdge": FRAGMENT_LONG_EDGE, "fragmentAspectRatio": FRAGMENT_ASPECT_RATIO})


def _surface_validity(page):
    """Reject decorative gradients while allowing explicitly semantic data ink."""
    return page.evaluate("""
() => {
  const violations = [];
  const visible = el => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0 && r.width > 1 && r.height > 1;
  };
  const label = el => el.getAttribute('data-scene-role') || el.className || el.tagName.toLowerCase();
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el)) continue;
    const image = getComputedStyle(el).backgroundImage || '';
    if (!image.includes('gradient')) continue;
    if (el.getAttribute('data-ink') === 'signal') continue;
    const r = el.getBoundingClientRect();
    const isCanvas = el === document.body || el.classList.contains('slide') || r.width * r.height > 1280 * 720 * .18;
    const isDecorative = el.classList.contains('deco') || el.getAttribute('aria-hidden') === 'true';
    if (isCanvas || isDecorative) violations.push(String(label(el)));
  }
  return {
    gradient_violation_count: violations.length,
    gradient_roles: violations.slice(0, 8),
  };
}
""")


def evaluate_run(run_path):
    from playwright.sync_api import sync_playwright

    run_path = Path(run_path)
    references = json.loads(SCENES.read_text())
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        for slide_path in sorted((run_path / "slide_code").glob("slide_*.html")):
            match = re.search(r"(\d+)$", slide_path.stem)
            slide_id = int(match.group(1))
            program = json.loads(
                (run_path / "slide_programs" / f"slide_{slide_id:02d}.json").read_text()
            )
            composition = program.get("composition", {})
            layout_vocab_id = program.get("layout_vocab_id") or composition.get("layout_inspiration_id")
            if not layout_vocab_id:
                raise ValueError(f"slide {slide_id} program has no layout inspiration")
            source_id = layout_vocab_id.split("layout.", 1)[-1]
            anchor_id = program.get("content_profile", {}).get("design_anchor_id")
            reference_ids = [anchor_id] if anchor_id in references else [source_id]
            page.goto(slide_path.resolve().as_uri())
            page.wait_for_timeout(40)
            output = _enrich_output(page.evaluate(EXTRACT_JS))
            validity = _layout_validity(page)
            validity.update(_surface_validity(page))
            neighborhood_scores = [
                (reference_id, compare(references[reference_id], output))
                for reference_id in reference_ids if reference_id in references
            ]
            best_reference, score = max(
                neighborhood_scores, key=lambda item: item[1]["similarity"]
            )
            # Resemblance may land near any member of the allowed neighborhood,
            # but literal copying of any member is rejected.
            score["copy_score"] = max(
                item[1]["copy_score"] for item in neighborhood_scores
            )
            budgets = program.get("budgets", {})
            lower = budgets.get("distribution_similarity_min", 0.35)
            copy_max = budgets.get("geometry_copy_max", 0.74)
            if (validity["overflow_count"] or validity["text_clip_count"]
                    or validity["text_collision_count"]
                    or validity["graphic_text_collision_count"]
                    or validity["connector_rule_collision_count"]
                    or validity["connector_occlusion_count"]
                    or validity["graphic_text_clearance_count"]
                    or validity["text_clearance_count"]
                    or validity["text_association_count"]
                    or validity["low_contrast_count"] or validity["gradient_violation_count"]):
                status = "layout-invalid"
            elif validity["source_asset_issue_count"]:
                status = "source-review-required"
            elif score["copy_score"] >= copy_max:
                status = "too-literal"
            elif score["similarity"] < lower:
                status = "generic-drift"
            else:
                status = "in-band"
            results.append({
                "slide_id": slide_id,
                "reference_id": source_id,
                "reference_ids": reference_ids,
                "nearest_reference_id": best_reference,
                "macro": program.get("layout_macro") or composition.get("strategy", "unknown"),
                "status": status,
                "layout_validity": validity,
                **score,
            })
        browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = {}
    for run in args.runs:
        results = evaluate_run(run)
        report[str(run)] = results
        if not args.json:
            print(f"\n{run}")
            print("slide  ref       macro                  similarity  copy   validity  status")
            for item in results:
                print(
                    f"{item['slide_id']:>5}  {item['reference_id']:<8}  {item['macro']:<21}  "
                    f"{item['similarity']:.3f}       {item['copy_score']:.3f}  "
                    f"{item['layout_validity']['overflow_count']}/{item['layout_validity']['text_clip_count']}       "
                    f"{item['status']}"
                )
    if args.json:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
