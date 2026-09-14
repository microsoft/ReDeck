"""Render one bounded creative brief into a compact model payload."""

import json
import re

from redeck_style.style_grammar import compile_relational_style_grammar
from redeck_style.domain.constraints import title_size_ceiling
from redeck_style.domain.density import density_policy
from redeck_style.domain.editorial import ART_DIRECTION, EDITORIAL_COPY_POLICY


_TABLE_STOPWORDS = {
    "and", "based", "best", "conventional", "graph", "learner", "method",
    "methods", "plus", "reaches", "result", "transformer", "with",
}

_RETRIEVAL_STOPWORDS = _TABLE_STOPWORDS | {
    "a", "an", "are", "as", "at", "be", "both", "by", "can", "each",
    "for", "from", "in", "into", "is", "it", "of", "on", "or", "our",
    "that", "the", "their", "then", "this", "to", "using", "we",
}


def _tokens(value):
    return set(re.findall(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", str(value).lower()))


def _table_display_plan(figure, evidence, max_rows, include_context_rows=False):
    """Select claim-bearing source rows without asking the model to compress a whole table.

    The selection is conservative: it copies source cells verbatim and uses overlap with
    must-cover evidence only.  Group labels are retained as metadata, not invented rows.
    """
    rows = figure.get("rows", [])
    evidence_tokens = _tokens(" ".join(map(str, evidence))) - _TABLE_STOPWORDS
    numeric_tokens = {
        token for token in evidence_tokens if any(character.isdigit() for character in token)
    }
    current_group = ""
    records = []
    for index, row in enumerate(rows):
        values = list(row or [])
        nonempty = [str(value) for value in values if value not in (None, "")]
        if not nonempty:
            continue
        if len(nonempty) == 1 and len(values) > 1:
            current_group = nonempty[0]
            continue
        row_tokens = _tokens(" ".join(nonempty))
        number_hits = row_tokens & numeric_tokens
        word_hits = (row_tokens & evidence_tokens) - numeric_tokens
        score = 12 * len(number_hits) + len(word_hits)
        records.append({
            "source_row_index": index,
            "source_group": current_group,
            "cells": values,
            "match_score": score,
        })
    candidates = [record for record in records if record["match_score"]] or records
    selected = sorted(candidates, key=lambda item: (-item["match_score"], item["source_row_index"]))[:max_rows]
    if include_context_rows:
        groups = {}
        for record in records:
            groups.setdefault(record["source_group"], []).append(record)
        boundaries = [record for group in groups.values() for record in (group[0], group[-1])]
        for record in [*boundaries, *records]:
            if len(selected) >= max_rows:
                break
            if record not in selected:
                selected.append(record)
    selected.sort(key=lambda item: item["source_row_index"])
    return {
        "mode": "claim-and-context-excerpt" if include_context_rows else "claim-aligned-excerpt",
        "source_raw_row_count": int(figure.get("row_count") or len(rows)),
        "source_row_count": len(records),
        "count_scope": "extracted data rows; excludes group headings and empty rows, not an assertion of complete extraction",
        "display_row_count": len(selected),
        "omitted_row_count": len(records) - len(selected),
        "selection_policy": "claim overlap, then source-group boundary rows, then source order; not a best/worst ranking" if include_context_rows else "claim overlap",
        "rows": selected,
    }


def _theme_css(theme):
    return ":root{" + ";".join(
        f"--{name.replace('_', '-')}:{value}" for name, value in theme.tokens.items()
    ) + "}"


def _supporting_evidence(source_text, slide, limit=9, char_budget=2800):
    """Retrieve verbatim source sentences relevant to one slide's claims."""
    if not source_text:
        return []
    normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", source_text)
    normalized = re.sub(r"\s+", " ", normalized)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)
    query = " ".join([
        slide.get("primary_proposition", ""),
        *map(str, slide.get("must_cover_subset", [])),
    ])
    query_tokens = _tokens(query) - _RETRIEVAL_STOPWORDS
    numeric_tokens = {
        token for token in query_tokens if any(character.isdigit() for character in token)
    }
    ranked = []
    for index, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not 55 <= len(sentence) <= 420:
            continue
        if "figure " in sentence.lower() and len(sentence) > 220:
            continue
        tokens = _tokens(sentence)
        overlap = tokens & query_tokens
        if len(overlap) < 2:
            continue
        score = len(overlap) + 6 * len(tokens & numeric_tokens)
        ranked.append((score, index, sentence))
    chosen = []
    used = 0
    for _, index, sentence in sorted(ranked, key=lambda item: (-item[0], item[1])):
        if any(
            len(_tokens(sentence) & _tokens(existing)) /
            max(1, min(len(_tokens(sentence)), len(_tokens(existing)))) > 0.72
            for _, existing in chosen
        ):
            continue
        if used + len(sentence) > char_budget:
            continue
        chosen.append((index, sentence))
        used += len(sentence)
        if len(chosen) == limit:
            break
    return [sentence for _, sentence in sorted(chosen)]


_SEMANTIC_FAMILIES = {
    "title": "identity-and-thesis",
    "context": "claim-context-evidence",
    "method": "mechanism-and-evidence",
    "evaluation": "fixed-context-changing-variable-measures",
    "results": "claim-baseline-proof-qualification",
    "comparison": "shared-criteria-contrasts-conclusion",
    "discussion": "claim-tensions-implication",
    "conclusion": "synthesis-implications-next-questions",
}


def _semantic_architecture(program, slide, supporting):
    """Compile evidence relationships without prescribing page geometry.

    This is deliberately neither a list of UI components nor a prose style
    prompt.  It gives the realizer a typed argument graph; the model remains
    responsible for deciding whether a relation becomes proximity, a scale,
    a sequence, a chart, a table, or another coherent visual treatment.
    """
    claims = [
        {"id": evidence_id, "kind": "required-evidence", "text": str(text)}
        for evidence_id, text in zip(
            program.content_profile.evidence_ids,
            slide.get("must_cover_subset", []),
        )
    ]
    claim_tokens = {item["id"]: _tokens(item["text"]) - _RETRIEVAL_STOPWORDS for item in claims}
    support_limit = density_policy(program.information_density, program.content_profile.role)["support_candidates"]
    support_nodes = []
    for index, sentence in enumerate(supporting[:support_limit]):
        sentence_tokens = _tokens(sentence) - _RETRIEVAL_STOPWORDS
        ranked = sorted(
            (
                (len(sentence_tokens & tokens), claim_id)
                for claim_id, tokens in claim_tokens.items()
            ),
            reverse=True,
        )
        parent = ranked[0][1] if ranked and ranked[0][0] else "thesis"
        support_nodes.append({
            "id": f"support-{index}",
            "kind": "source-detail",
            "supports": parent,
            "text": sentence,
        })

    role = program.content_profile.role
    claim_ids = [item["id"] for item in claims]
    relations = [{"from": "thesis", "relation": "supported-by", "to": claim_id} for claim_id in claim_ids]
    relations.extend({"from": edge.source, "relation": edge.kind, "to": edge.target,
                      "evidence_quote": edge.evidence_quote}
                     for edge in program.content_profile.evidence_relations)
    for node in support_nodes:
        relations.append({"from": node["id"], "relation": "grounds", "to": node["supports"]})

    architecture = {
        "family": _SEMANTIC_FAMILIES.get(role, "claim-evidence-implication"),
        "lead": {"id": "thesis", "kind": "primary-proposition", "text": slide.get("primary_proposition", "")},
        "required_evidence": claims,
        "optional_source_detail_reservoir": support_nodes,
        "relations": relations,
        "connector_policy": {
            "default": "none",
            "eligible_relations": [edge for edge in relations if "evidence_quote" in edge],
            "additional_relations": "only if explicit in supplied source; encode data-relation-from, data-relation-to and data-evidence-quote on each connector",
            "forbidden_inference": ["item order implies causality", "method role implies temporal stages", "support edge implies arrow"],
            "preferred_for_unordered_evidence": ["proximity", "shared alignment", "typographic hierarchy", "direct annotation"],
            "staircase": "only for a grounded ordered progression, never to decorate an ordinary evidence list",
        },
        "realization_rule": (
            "Preserve these relationships and factual layers. Choose geometry and visual forms "
            "holistically; node count is not a request for boxes, cards, or a node-link diagram."
        ),
    }
    architecture["content_budget"] = _content_budget(program, architecture)
    return architecture


def _split_table_row(row):
    """Expand extractor-merged multiline cells without inventing values."""
    cells = ["" if value is None else str(value) for value in (row or [])]
    parts = [cell.splitlines() for cell in cells]
    count = max((len(values) for values in parts), default=0)
    if count <= 1 or not all(len(values) in {1, count} for values in parts):
        return [cells]
    return [
        [values[index] if len(values) == count else values[0] for values in parts]
        for index in range(count)
    ]


def _number(value):
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(value))
    return float(match.group().replace(",", "")) if match else None


def _table_chart_data(figure, display_plan):
    """Return exact labels/values plus deterministic plotting coordinates."""
    caption = str(figure.get("caption", "")).lower()
    col_count = int(figure.get("col_count") or 0)
    if "seizure detection" in caption and col_count == 4:
        series = ["F1", "Accuracy", "Recall"]
    elif "graph-level" in caption and col_count == 3:
        series = ["Graph sparsity", "JSD"]
    else:
        series = [f"Measure {index}" for index in range(1, max(1, col_count))]
    expanded = []
    for item in display_plan.get("rows", []):
        cells = item.get("cells", item) if isinstance(item, dict) else item
        for row in _split_table_row(cells):
            if len(row) < 2 or not row[0].strip():
                continue
            values = []
            valid = True
            for index, name in enumerate(series, 1):
                if index >= len(row) or _number(row[index]) is None:
                    valid = False
                    break
                numeric = _number(row[index])
                values.append({
                    "series": name,
                    "label": row[index],
                    "value": numeric,
                    "plot_percent_of_one": round(numeric * 100, 2) if 0 <= numeric <= 1 else None,
                })
            if valid:
                expanded.append({"label": row[0], "values": values})
    return {"series": series, "rows": expanded}


def _evidence_numbers(architecture):
    groups = []
    for node in architecture.get("required_evidence", []):
        values = []
        for raw in re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?%?", node["text"]):
            numeric = _number(raw)
            if numeric is not None:
                values.append({"label": raw, "value": numeric})
        if values:
            groups.append({"evidence_id": node["id"], "text": node["text"], "values": values})
    return groups


def _visual_encoding_plan(program, architecture, figure=None, table_plan=None):
    """Compile data/relations into executable marks, never page geometry.

    This restores a signal previously lost between ContentProfile and the
    prompt: representation_needs described possible charts, but the renderer
    hid them.  The plan specifies truthful marks and exact data while leaving
    scale, placement, and composition to the realizer.
    """
    role = program.content_profile.role
    relations = [
        edge for edge in architecture["relations"]
        if edge["relation"] not in {"supported-by", "grounds"}
    ]
    base = {
        "required": bool(
            figure
            or (
                role in {"results", "comparison", "evaluation"}
                and program.content_profile.numeric_count >= 3
            )
        ),
        "rendering": "native HTML/CSS/SVG; no raster chart generation",
        "composition_freedom": (
            "Choose scale, orientation, placement, and grouping from the page argument; "
            "these marks are not a layout template."
        ),
        "color_encoding": {
            "default": "one primary accent; neutral text, rules, connectors, and baseline data",
            "series_identity": "one named series uses the same --series-color for bars, dots, lines and labels across the deck",
            "additional_hues": "secondary/tertiary only distinguish named comparable series; position, unit and direct label must still explain the comparison",
            "signal": "reserve accent-signal for a genuinely exceptional datum, never a generic connector or badge",
            "source_figure": "retain original colors and legend; keep surrounding annotation neutral unless explicitly referring to an existing series",
        },
        "element_binding": {
            "connectors": "governed by semantic_architecture.connector_policy; reserve a clear lane for each grounded connection and its horizontal label",
            "ticks": "positions and labels derive from a quantitative scale; no decorative ruler",
            "markers": "use shape to encode a real distinction; do not add diamonds to every fact or list item",
        },
        "substitution_rule": (
            "A realized chart or diagram replaces redundant prose that states the same "
            "relationship. Keep one concise interpretation; do not show the full claim, "
            "the same values in a table, and the same values in a chart unless each adds "
            "a distinct reading task."
        ),
    }
    asset_mode = program.content_profile.asset_mode
    if figure and (figure.get("kind") != "table" or asset_mode == "preserve"):
        return {
            **base,
            "primary_mark": "source-figure",
            "rendering": "embed the supplied source image unchanged; do not redraw it",
            "supporting_marks": ["direct-annotation", "metric-callout"],
            "source_policy": "Preserve the supplied figure; do not redraw or crop its data.",
            "relations": relations,
        }
    if figure and figure.get("kind") == "table" and table_plan:
        if asset_mode == "table":
            return {
                **base,
                "primary_mark": "data-table",
                "data": table_plan,
                "table_policy": "Render the selected source rows as a native HTML table, not a chart or screenshot. Preserve cell labels, values, units and row order.",
            }
        chart_data = _table_chart_data(figure, table_plan)
        if not chart_data["series"] or not chart_data["rows"]:
            if asset_mode == "chart":
                raise ValueError(f"Slide {program.slide_id}: chart mode requires plottable extracted rows in the selected table data")
            return {
                **base,
                "required": False,
                "primary_mark": "direct-labeled-metrics",
                "numeric_groups": _evidence_numbers(architecture),
                "reason": "The source table has no extracted plottable series. Do not request a chart from empty data.",
                "scale_rule": (
                    "Preserve grounded values and units as direct labels. Do not draw bars, "
                    "progress tracks or axes without an explicit comparable series and domain; "
                    "unlike units cannot share a length scale."
                ),
            }
        primary = "aligned-dot-plot" if role == "comparison" else "grouped-bar-chart"
        alternatives = (
            ["slopegraph", "paired-lanes"] if role == "comparison"
            else ["small-multiple-bars", "dot-and-rule-comparison"]
        )
        return {
            **base,
            "primary_mark": primary,
            "allowed_alternatives": alternatives,
            "data": chart_data,
            "encoding": {
                "category": "row label",
                "magnitude": "position or length on a labeled common scale within each series",
                "series": "color plus direct label",
                "exact_values": "show supplied labels verbatim; never infer missing values",
            },
            "table_policy": (
                "Render the selected source values as a chart with exact-value labels, not a table or screenshot."
                if asset_mode == "chart" else
                "Default to the chart with direct exact-value labels. Add a compact table only when "
                "it supports a distinct lookup task or contains values the chart does not already show; "
                "never repeat the same rows and measures in both forms."
            ),
        }
    if role in {"context", "method", "conclusion"}:
        return {
            **base,
            "primary_mark": "grounded-relation-diagram" if relations else "annotated-evidence-field",
            "nodes": [architecture["lead"], *architecture["required_evidence"]],
            "edges": relations,
            "allowed_alternatives": ["open-evidence-groups", "shared-axis-comparison", "annotated-system-view"],
        }
    if role == "evaluation":
        return {
            **base,
            "primary_mark": "controlled-variable-diagram",
            "numeric_groups": _evidence_numbers(architecture),
            "allowed_alternatives": ["metric-small-multiples", "protocol-summary", "comparison-scale"],
            "scale_rule": "Do not place unlike units on one quantitative axis.",
        }
    return {
        **base,
        "primary_mark": "evidence-comparison",
        "numeric_groups": _evidence_numbers(architecture),
        "relations": relations,
        "allowed_alternatives": ["dot-plot", "bar-chart", "metric-sequence"],
    }


def _content_budget(program, architecture):
    """Bound what a slide must show so evidence does not become page fill."""
    role = program.content_profile.role
    policy = density_policy(program.information_density, role)
    available_details = len(architecture["optional_source_detail_reservoir"])
    numeric_target = {
        "evaluation": 4,
        "results": 4,
        "comparison": 4,
        "method": 2,
        "context": 2,
    }.get(role, 1)
    relation_types = {
        edge["relation"] for edge in architecture["relations"]
        if edge["relation"] not in {"supported-by", "grounds"}
    }
    required_layers = ["lead", "all-required-evidence"]
    if relation_types:
        required_layers.append("mechanism-or-comparison")
    if role in {"results", "comparison", "discussion", "conclusion"}:
        required_layers.append("qualification-or-implication")
    required_layers.append("source-attribution")
    return {
        "required_layers": required_layers,
        "information_density": program.information_density,
        "maximum_optional_source_details": min(policy["maximum_source_details"], available_details),
        "target_distinct_source_details": min(policy["target_source_details"], available_details),
        "minimum_numeric_marks": min(numeric_target, program.content_profile.numeric_count),
        "target_content_coverage": policy["content_coverage"] + " of the usable canvas on non-title slides; a composition guide, not a measured score",
        "functional_negative_space": policy["negative_space"] + "; preserve separation around the focal argument",
        "evidence_rich_policy": (
            "Aim to add two distinct supported details when available: experimental conditions, comparator context, "
            "mechanism annotations or limitations. Attach concise direct labels to the evidence; do not paste excerpts as paragraphs. "
            "Prefer a substantial comparison or evidence field over an oversized slogan/metric. "
            "On content pages aim for a compact header (about 16% height), but expand it if wrapped text requires space. "
            "Render the main proposition once; shorten a headline rather than repeating it in a sidebar, subtitle and takeaway. "
            "Do not add charts to non-numeric arguments. If supplied evidence is insufficient, keep whitespace: "
            "never fabricate facts, duplicate claims or force a target count. Keep all text readable and non-overlapping."
        ) if policy["rich_content"] else "Use the balanced evidence budget; do not add material just to fill space.",
        "hierarchy_rule": (
            "Required evidence is a semantic checklist, not a request for one visible block per item. "
            "Merge related facts into one visual statement and let a chart or diagram carry facts "
            "that would otherwise be repeated in prose. Never increase density by reducing body scale."
        ),
    }


def _layout_scaffold(program, library):
    """Compile a BAMS layout into adjustable grid tracks, not fixed boxes."""
    layout = library.items[program.composition.layout_inspiration_id]
    regions = layout.program.get("regions", [])

    def internal_cuts(axis, extent):
        values = []
        for region in regions:
            start = float(region.get(axis, 0) or 0)
            size = float(region.get(extent, 0) or 0)
            for value in (start, start + size):
                if 15 <= value <= 85:
                    values.append(value)
        # Collapse near-duplicate edges and keep at most two strong divisions.
        clusters = []
        for value in sorted(values):
            if clusters and abs(value - sum(clusters[-1]) / len(clusters[-1])) <= 3:
                clusters[-1].append(value)
            else:
                clusters.append([value])
        ranked = sorted(clusters, key=lambda group: (-len(group), sum(group) / len(group)))[:2]
        return sorted(round(sum(group) / len(group)) for group in ranked)

    def tracks(cuts):
        edges = [0, *cuts, 100]
        return [f"{max(1, edges[index + 1] - edges[index])}fr" for index in range(len(edges) - 1)]

    columns = tracks(internal_cuts("x", "w"))
    rows = tracks(internal_cuts("y", "h"))
    return {
        "macro": program.composition.layout_family,
        "strategy": program.composition.strategy,
        "focal_role": program.composition.focal_role,
        "reading_path": program.composition.reading_path,
        "massing": program.composition.massing,
        "whitespace": program.composition.whitespace,
        "adjustable_grid": {
            "columns": columns,
            "rows": rows,
            "css": (
                "display:grid;grid-template-columns:"
                + " ".join(f"minmax(0,{track})" for track in columns)
                + ";grid-template-rows:"
                + " ".join(f"minmax(0,{track})" for track in rows)
            ),
        },
        "adaptation_rule": (
            "Use these tracks as an initial compositional gesture. Merge tracks, move the focal "
            "element across a boundary, or drop a low-value region when the actual evidence needs "
            "it. Preserve the macro silhouette and reading path, not literal source coordinates."
        ),
    }


def _css_property(css, property_name, default):
    match = re.search(rf"(?:^|[;{{])\s*{re.escape(property_name)}\s*:\s*([^;}}]+)", css)
    return match.group(1).strip() if match else default


def _rule_weight(css):
    """Keep a source separator's stroke weight, never its page-relative length."""
    value = _css_property(css, "height", "1px")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)px", value)
    if not match:
        return "1px"
    return f"{min(5.0, max(1.0, float(match.group(1)))):g}px"


def _design_kernel(program, library):
    """Compile vocab code into a page-wide editorial substrate.

    Raw content selectors are intentionally not exposed.  They previously made
    models reproduce cards, timelines, and matrices literally.  The compiler
    instead preserves source-derived material values as executable CSS custom
    properties and supplies a small role-based type/rule system.
    """
    programs = {}
    source_ids = []
    for selection in program.vocab:
        vocab = library.items[selection.vocab_id]
        source_ids.append(vocab.id)
        programs[selection.kind] = vocab.program.get("css", "")

    typography = programs.get("typography", "")
    content = programs.get("content", "")
    separator = programs.get("separator", "")
    display_family = _css_property(typography, "font-family", "'Segoe UI',Arial,sans-serif")
    display_weight = _css_property(typography, "font-weight", "700")
    display_tracking = _css_property(typography, "letter-spacing", "0")
    radius = _css_property(content, "border-radius", "0px")
    gap = _css_property(content, "gap", "14px")
    separator_height = _rule_weight(separator)
    typography_selection = next(
        selection for selection in program.vocab if selection.kind == "typography"
    )
    title_ceiling = int(typography_selection.parameters.get("title_size_ceiling_px", 56))
    title_size = f"{min(title_ceiling, title_size_ceiling(program.content_profile.role, program.content_profile.title_length))}px"
    css = "\n".join([
        ":root{",
        f"  --kernel-display-family:{display_family};",
        f"  --kernel-display-weight:{display_weight};",
        f"  --kernel-display-tracking:{display_tracking};",
        f"  --kernel-title-size:{title_size};",
        "  --kernel-body-size:16px;",
        "  --kernel-note-size:12px;",
        f"  --kernel-rhythm:{gap};",
        f"  --kernel-radius:{radius};",
        f"  --kernel-rule-weight:{separator_height};",
        "}",
        ".slide{position:relative;width:1280px;height:720px;overflow:hidden;color:var(--ink-canvas);background:var(--surface-canvas)}",
        "[data-level='display']{font-family:var(--kernel-display-family);font-size:var(--kernel-title-size);font-weight:var(--kernel-display-weight);letter-spacing:var(--kernel-display-tracking);line-height:1.02;text-shadow:none}",
        "[data-level='section']{font:700 12px/1.15 'Segoe UI',Arial,sans-serif;letter-spacing:1.35px;text-transform:uppercase;color:color-mix(in srgb,var(--ink-canvas) 78%,transparent)}",
        "[data-level='body']{font:400 var(--kernel-body-size)/1.34 'Segoe UI',Arial,sans-serif}",
        "[data-level='note']{font:500 var(--kernel-note-size)/1.25 'Segoe UI',Arial,sans-serif;color:color-mix(in srgb,var(--ink-canvas) 68%,transparent)}",
        "[data-rule]{height:var(--kernel-rule-weight);background:color-mix(in srgb,var(--ink-canvas) 24%,transparent)}",
        "[data-ink='annotation']{border-left:2px solid color-mix(in srgb,var(--ink-canvas) 28%,transparent);padding-left:12px}",
        "[data-ink='signal']{background:linear-gradient(90deg,var(--accent-primary) 0 var(--value,50%),color-mix(in srgb,var(--ink-canvas) 10%,transparent) var(--value,50%) 100%);height:6px}",
        "[data-ink='comparison']{background:var(--surface-muted);border-block:1px solid color-mix(in srgb,var(--ink-canvas) 24%,transparent)}",
        "[data-ink='connector']{fill:none;stroke:color-mix(in srgb,var(--ink-canvas) 48%,var(--surface-canvas));stroke-width:1.5;vector-effect:non-scaling-stroke}",
        "[data-ink='secondary-connector']{fill:none;stroke:color-mix(in srgb,var(--ink-canvas) 38%,var(--surface-canvas));stroke-width:1.25;stroke-dasharray:5 5;vector-effect:non-scaling-stroke}",
        "[data-ink='tick']{width:1px;height:5px;background:color-mix(in srgb,var(--ink-canvas) 48%,transparent)}",
        "[data-chart]{color:var(--ink-canvas)}",
        "[data-chart-role='axis']{stroke:color-mix(in srgb,var(--ink-canvas) 38%,transparent);stroke-width:1;vector-effect:non-scaling-stroke}",
        "[data-chart-role='grid']{stroke:color-mix(in srgb,var(--ink-canvas) 14%,transparent);stroke-width:1;vector-effect:non-scaling-stroke}",
        "[data-chart-role='bar']{fill:var(--series-color,var(--accent-primary))}",
        "[data-chart-role='dot']{fill:var(--series-color,var(--accent-primary));stroke:var(--surface-canvas);stroke-width:2}",
        "[data-chart-role='series-line']{fill:none;stroke:var(--series-color,var(--accent-primary));stroke-width:2;vector-effect:non-scaling-stroke}",
        "[data-diagram-role='node']{color:var(--ink-canvas);padding-block-start:8px}",
        "figure{margin:0}",
        "table{border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{border-bottom:1px solid color-mix(in srgb,var(--ink-canvas) 18%,transparent)}",
    ])
    return {"source_ids": source_ids, "css": css}



def render_prompt(program, theme, slide, figures, total_slides, library, source_excerpt="", *, include_editorial_policy=True):
    if program.theme_id != theme.id:
        raise ValueError(f"program theme {program.theme_id} does not match {theme.id}")
    evidence = slide.get("must_cover_subset", [])
    supporting = _supporting_evidence(source_excerpt, slide)
    architecture = _semantic_architecture(program, slide, supporting)
    figure_id = slide.get("assigned_figure_id")
    figure = figures.get(figure_id) if figure_id and figure_id in figures else None
    table_data = None
    if figure and figure.get("kind") == "table" and program.content_profile.asset_mode != "preserve":
        content_selection = next(item for item in program.vocab if item.kind == "content")
        table_mode = content_selection.parameters.get("table_mode", "one coherent evidence field")
        table_data = (
            _table_display_plan(
                figure,
                slide.get("must_cover_subset", []),
                int(content_selection.parameters.get("max_display_rows", 6)),
                include_context_rows=content_selection.parameters.get("include_context_rows", False),
            )
            if table_mode == "claim-aligned-excerpt"
            else {
                "mode": table_mode,
                "source_row_count": figure.get("row_count", 0),
                "display_row_count": len(figure.get("rows", [])),
                "omitted_row_count": 0,
                "rows": figure.get("rows", []),
            }
        )
    visual_encoding = _visual_encoding_plan(program, architecture, figure, table_data)
    brief = {
        "schema_version": program.schema_version,
        "slide_id": program.slide_id,
        "dialect_id": program.dialect_id,
        "information_density": program.information_density,
        "presentation_role": program.content_profile.role,
        "evidence_profile": {
            "density": program.content_profile.density,
            "numeric_count": program.content_profile.numeric_count,
            "source_kind": program.content_profile.source_kind or "none",
            "asset_mode": program.content_profile.asset_mode,
            "row_count": program.content_profile.source_row_count,
            "column_count": program.content_profile.source_col_count,
        },
        "guardrails": program.guardrails.__dict__,
    }
    kernel = _design_kernel(program, library)
    style_grammar = compile_relational_style_grammar(program, library)
    layout_scaffold = _layout_scaffold(program, library)
    lines = [
        "## THEME TOKENS — HARD CONSTRAINT",
        f"```css\n{_theme_css(theme)}\n```",
        "",
        "## SLIDE DESIGN PROGRAM — BOUNDED CREATIVE BRIEF",
        "This brief describes evidence pressure and one adjustable compositional scaffold. "
        "Let the argument determine how the scaffold bends; do not treat it as a page template.",
        f"```json\n{json.dumps(brief, ensure_ascii=False, indent=2)}\n```",
        "",
        "## ADJUSTABLE BAMS COMPOSITION SCAFFOLD",
        "This is executable starting structure distilled from a BAMS page. Use its track ratio, silhouette, and reading direction, but resize, merge, span, or omit tracks to fit this slide. It is not a set of content slots.",
        f"```json\n{json.dumps(layout_scaffold, ensure_ascii=False, indent=2)}\n```",
        "",
        "## EXECUTABLE DESIGN KERNEL",
        "This is a source-derived, executable editorial substrate. Use its flat canvas, type levels, rhythm, rules, and material variables across the whole page. "
        "It deliberately contains no content-component skeleton; invent the composition from the evidence relationships.",
        f"Source vocab IDs (audit only): {json.dumps(kernel['source_ids'])}",
        f"```css\n{kernel['css']}\n```",
        "",
        "## EXECUTABLE RELATIONAL STYLE GRAMMAR",
        "This grammar carries evidence-compatible BAMS-derived relationships. Dominant/supporting priorities rank optional choices; they are not objects to draw. Omit a device if it lacks a named evidence role or duplicates the source figure. Do not add inactive operations. The CSS primitives may be combined and resized.",
        f"```json\n{json.dumps({key: value for key, value in style_grammar.items() if key != 'css'}, ensure_ascii=False, indent=2)}\n```",
        f"```css\n{style_grammar['css']}\n```",
    ]

    lines.extend([
        "",
        *([ART_DIRECTION] if include_editorial_policy else []),
        "",
        f"## SLIDE {program.slide_id} OF {total_slides}",
        f"Role: {program.content_profile.role}",
        "Typed evidence architecture (required-evidence must remain semantically present; optional source details are a reservoir, not mandatory visible copy):",
        f"```json\n{json.dumps(architecture, ensure_ascii=False, indent=2)}\n```",
        "Executable visual-encoding plan (data and relations are binding; geometry is free):",
        f"```json\n{json.dumps(visual_encoding, ensure_ascii=False, indent=2)}\n```",
    ])
    if figure_id and figure_id in figures and (figures[figure_id].get("path") or figures[figure_id].get("kind") == "table"):
        figure = figures[figure_id]
        if figure.get("kind") == "table" and program.content_profile.asset_mode != "preserve":
            content_selection = next(item for item in program.vocab if item.kind == "content")
            table_mode = content_selection.parameters.get("table_mode", "one coherent evidence field")
            if table_mode == "claim-aligned-excerpt":
                table_instruction = (
                    "Display the supplied claim-bearing rows and contextual comparison rows in one coherent evidence field. "
                    "Context rows follow source-group boundaries and source order; they are not a statistically representative sample. "
                    "Do not infer that an excerpt proves a universal ranking. Counts refer to extracted data rows, not group headings."
                ) if content_selection.parameters.get("include_context_rows") else (
                    "The runtime selected the source rows that directly support the must-cover claims. "
                    "Display these rows, not the full source table. Omitted rows are outside the page's "
                    "must-cover scope; mention only the provided omitted-row count if useful."
                )
            else:
                table_data = {
                    "mode": table_mode,
                    "source_row_count": figure.get("row_count", 0),
                    "display_row_count": len(figure.get("rows", [])),
                    "omitted_row_count": 0,
                    "rows": figure.get("rows", []),
                }
                table_instruction = (
                    "Rebuild the supplied source rows as one readable native HTML evidence field."
                    if table_data["rows"] else
                    "No source rows were extracted. Do not reconstruct or invent the missing table; "
                    "use only grounded values from required evidence as direct labels with units."
                )
            lines.extend([
                "Assigned source is a table; its screenshot is not an input.",
                table_instruction,
                "Cell values below are copied from the source. Do not add, interpolate, or alter values.",
                f"Source caption: {figure.get('caption', '')}",
                "Display table data:",
                f"```json\n{json.dumps({**table_data, 'col_count': figure.get('col_count', 0)}, ensure_ascii=False, indent=2)}\n```",
            ])
        else:
            width = int(figure.get("width") or 0)
            height = int(figure.get("height") or 0)
            aspect = round(width / height, 2) if width and height else None
            lines.extend([
                f"Assigned source {figure.get('kind', 'figure')}: <img src=\"{figure['path']}\" />",
                f"Source caption: {figure.get('caption', '')}",
                f"Intrinsic asset size: {width}×{height}px" + (f" (aspect ratio {aspect}:1)." if aspect else "."),
                "Treat it as primary evidence integrated into the scene, not as a thumbnail in a generic panel. "
                "Keep object-fit:contain and preserve its aspect ratio. Size the visual stage from that intrinsic aspect ratio; "
                "do not build a tall frame around a wide, shallow image or frame the resulting letterbox whitespace.",
            ])
    lines.extend([
        "CONTENT BOUNDARY: visible copy may express only the typed evidence architecture, assigned source caption/data, and short structural labels derived directly from them.",
        *([EDITORIAL_COPY_POLICY] if include_editorial_policy else []),
        "Before returning, inspect the whole 1280×720 scene for hierarchy, visual tension, alignment, text fit, and coherence—not merely the presence of every ingredient.",
        "Return the complete HTML slide now.",
    ])
    return "\n".join(lines)
