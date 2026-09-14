"""BAMS-derived relational style grammars.

The grammar provides executable relationships, not a page template.  A deck
keeps one archetype, while each slide selects evidence-compatible operations.
Rotation breaks ties; it never invents a reason to add a visual device.
"""

from redeck_style.planning.content_profiler import DIRECTED_RELATIONS

STYLE_GRAMMARS = {
    "editorial-contrast": {
        "operations": [
            {"op": "scale-break", "ratio": "2.6-4.2x", "apply_to": "one claim, number, or short quotation", "selector": "hero-type"},
            {"op": "asymmetric-counterweight", "mass_ratio": "58:42 to 72:28", "apply_to": "lead argument versus proof", "selector": "counter-field", "creates_surface": True},
            {"op": "editorial-rule", "weight": "1-4px", "apply_to": "a real argumentative transition", "selector": "editorial-rule"},
            {"op": "margin-annotation", "width": "12-22%", "apply_to": "qualification, source, or compact evidence", "selector": "margin-note"},
        ],
        "css": {
            "scale-break": "[data-style-role='hero-type']{font-family:var(--kernel-display-family);font-size:clamp(46px,5.4vw,76px);line-height:.94;letter-spacing:-.035em}",
            "asymmetric-counterweight": "[data-style-role='counter-field']{background:var(--surface-contrast);color:var(--ink-contrast);border-radius:0;padding:22px 26px}",
            "editorial-rule": "[data-style-role='editorial-rule']{height:1px;background:color-mix(in srgb,var(--ink-canvas) 28%,transparent)}",
            "margin-annotation": "[data-style-role='margin-note']{border-inline-start:2px solid var(--accent-primary);padding-inline-start:14px}",
        },
    },
    "technical-instrument": {
        "operations": [
            {"op": "indexed-rail", "width": "7-15%", "apply_to": "sequence, legend, or section identity", "selector": "index-rail"},
            {"op": "measurement-lattice", "apply_to": "a labeled quantitative scale; tick positions come from data, never fixed decorative intervals", "selector": "calibration"},
            {"op": "numeric-scale-break", "ratio": "3.0-5.0x", "apply_to": "one grounded metric or index", "selector": "major-number"},
            {"op": "instrument-readout", "apply_to": "supplied values with their units and shared baselines", "selector": "readout"},
        ],
        "css": {
            "indexed-rail": "[data-style-role='index-rail']{border-inline-end:2px solid var(--accent-primary);padding-inline-end:16px;font-family:var(--kernel-display-family)}",
            "measurement-lattice": "[data-style-role='calibration']{border-block-end:1px solid color-mix(in srgb,var(--ink-canvas) 28%,transparent);font-variant-numeric:tabular-nums}",
            "numeric-scale-break": "[data-style-role='major-number']{font:800 clamp(48px,6vw,86px)/.88 var(--kernel-display-family);color:var(--accent-primary)}",
            "instrument-readout": "[data-style-role='readout']{font-variant-numeric:tabular-nums;border-block:1px solid color-mix(in srgb,var(--ink-canvas) 28%,transparent);padding-block:8px}",
        },
    },
    "display-architecture": {
        "operations": [
            {"op": "edge-band", "canvas_share": "10-20%", "apply_to": "identity, sequence, or decisive conclusion", "selector": "edge-band", "creates_surface": True},
            {"op": "display-crop", "scale": "56-92px", "apply_to": "short semantic phrase or numeral; never crop required words", "selector": "display-block"},
            {"op": "hard-field-interlock", "overlap": "8-24px", "apply_to": "two related evidence layers", "selector": "interlock", "creates_surface": True},
            {"op": "directional-marker", "count": "1-3", "apply_to": "real reading transition", "selector": "direction"},
        ],
        "css": {
            "edge-band": "[data-style-role='edge-band']{background:var(--surface-contrast);color:var(--ink-contrast);border-radius:0}",
            "display-crop": "[data-style-role='display-block']{font:900 clamp(52px,6.8vw,92px)/.88 var(--kernel-display-family);letter-spacing:-.025em;text-transform:uppercase}",
            "hard-field-interlock": "[data-style-role='interlock']{position:relative;border-inline-start:3px solid var(--accent-primary);border-radius:0}",
            "directional-marker": "[data-style-role='direction']{color:var(--ink-canvas);border-inline-start:2px solid var(--accent-primary);padding-inline-start:10px}",
        },
    },
    "chromatic-system": {
        "operations": [
            {"op": "semantic-color-routing", "apply_to": "explicit named variables or evidence classes, not arbitrary boxes or mark shapes", "selector": "channel-a/channel-b/channel-c"},
            {"op": "segmented-edge-band", "apply_to": "a labeled composition, proportion, or sequence grounded in the source", "selector": "segment"},
            {"op": "cross-zone-bridge", "overlap": "10-28px", "apply_to": "one relationship crossing otherwise separate evidence zones", "selector": "bridge"},
            {"op": "anchor-field", "canvas_share": "18-32%", "apply_to": "one high-priority evidence group", "selector": "anchor-field", "creates_surface": True},
        ],
        "css": {
            "semantic-color-routing": (
                "[data-style-role='channel-a']{--channel-color:var(--accent-primary);border-color:var(--channel-color)}\n"
                "[data-style-role='channel-b']{--channel-color:var(--accent-secondary);border-color:var(--channel-color)}\n"
                "[data-style-role='channel-c']{--channel-color:var(--accent-tertiary);border-color:var(--channel-color)}\n"
                "[data-style-role^='channel-']{color:var(--ink-canvas)}"
            ),
            "segmented-edge-band": "[data-style-role='segment']{border-block-start:3px solid var(--series-color,var(--accent-primary));padding-block-start:10px}",
            "cross-zone-bridge": "[data-style-role='bridge']{position:relative;color:var(--ink-canvas);border-inline-start:2px solid var(--accent-primary);padding-inline-start:10px}",
            "anchor-field": "[data-style-role='anchor-field']{background:var(--accent-primary);color:var(--ink-accent);border-radius:0}",
        },
    },
}


FLOW_PRIMITIVES = """[data-flow='open']{background:none;border:0;box-shadow:none;padding:0}
[data-flow='run-in']{display:flex;align-items:baseline;gap:var(--kernel-rhythm)}
[data-flow='shared-axis']{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);align-items:end;gap:var(--kernel-rhythm)}
[data-flow='marginal']{max-width:22%;align-self:start}
[data-flow='overlap']{position:relative;z-index:2;margin-inline-start:calc(-1 * var(--kernel-rhythm))}
[data-flow='rule-led']{border-block-start:var(--kernel-rule-weight) solid color-mix(in srgb,var(--ink-canvas) 28%,transparent);padding-block-start:var(--kernel-rhythm)}"""


def _active_operations(program, operations):
    """Filter by evidence first; rotate only within the eligible vocabulary.

    An existing source figure owns the visual grammar of its data. Surrounding
    type/rules may support it, but do not manufacture another visual system.
    Eligibility is permission, not proof of a causal/quantitative relationship.
    """
    profile = program.content_profile
    source_figure = profile.has_figure and profile.source_kind != "table"
    has_relations = bool(profile.evidence_relations)
    has_direction = any(edge.kind in DIRECTED_RELATIONS for edge in profile.evidence_relations)
    quantitative = profile.numeric_count >= 3 and profile.role in {
        "results", "comparison", "evaluation",
    }
    requirements = {
        "measurement-lattice": quantitative and not source_figure,
        "numeric-scale-break": profile.numeric_count > 0,
        "instrument-readout": profile.numeric_count >= 2,
        "semantic-color-routing": profile.item_count >= 2 and not source_figure,
        "segmented-edge-band": profile.item_count >= 2 and not source_figure,
        "cross-zone-bridge": has_relations and not source_figure,
        "hard-field-interlock": has_relations and not source_figure,
        "directional-marker": has_direction and not source_figure,
    }
    eligible = [
        operation for operation in operations
        if requirements.get(operation["op"], True)
        and not (
            (profile.title_length > 105 or source_figure)
            and operation.get("creates_surface")
        )
    ]
    if not eligible:
        return []
    start = (program.slide_id - 1) % len(eligible)
    ordered = eligible[start:] + eligible[:start]
    selected = []
    for operation in ordered:
        if selected and operation.get("creates_surface") and selected[0].get("creates_surface"):
            continue
        selected.append({
            **operation,
            "priority": "dominant" if not selected else "supporting",
            "usage": "optional; bind to named evidence or omit",
        })
        if len(selected) == 2:
            break
    return selected


def resolve_style_archetype(explicit, dialect_id, typography_family):
    if explicit:
        if explicit not in STYLE_GRAMMARS:
            raise ValueError(f"unknown style archetype: {explicit}")
        return explicit
    if typography_family in {"mixed-editorial", "serif-classic"}:
        return "editorial-contrast"
    if typography_family in {"mono-tech", "small-dense"}:
        return "technical-instrument"
    if typography_family in {"large-display", "sans-bold"}:
        return "display-architecture"
    return "editorial-contrast"


def compile_relational_style_grammar(program, library):
    selected = {selection.kind: library.items[selection.vocab_id] for selection in program.vocab}
    typography = selected["typography"].compatibility.get("typo_family", "sans-clean")
    background = selected["background"].compatibility.get("bg_family", "solid-flat")
    decoration = selected.get("decoration")
    motif = decoration.compatibility.get("motif_family", "none") if decoration else "none"
    archetype = program.style_archetype
    grammar = STYLE_GRAMMARS[archetype]
    operations = _active_operations(program, grammar["operations"])
    active_names = [operation["op"] for operation in operations]
    css = "\n".join(grammar["css"][name] for name in active_names)
    return {
        "archetype": archetype,
        "source_traits": {"typography": typography, "field": background, "motif": motif},
        "active_operations": operations,
        "surface_policy": {
            "maximum_dominant_filled_fields": 1,
            "open_content_default": True,
            "filled_field_copy_limit": "one short claim or metric; never a paragraph-length thesis",
            "rule": (
                "Most evidence should share the canvas directly. Use a filled surface only for "
                "the single semantic anchor named by an active operation; do not wrap each fact."
            ),
        },
        "composition_rule": (
            "The dominant operation is a preferred vocabulary, not a mandatory object. "
            "Use an operation only when its named evidence relationship is actually present; "
            "omit it when alignment, direct labeling, or the source figure already does the job. "
            "The supporting operation is optional. Do not add inactive "
            "archetype operations merely for consistency. Keep at least one substantial evidence "
            "sequence unboxed and let it connect through baseline, proximity, or continuous type. "
            "Do not reproduce source coordinates. "
            "Accent colors may carry lines, large numerals, and filled fields, but small text must "
            "use the appropriate ink token for its immediate surface."
        ),
        "css": FLOW_PRIMITIVES + "\n" + css,
    }
