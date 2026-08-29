---
name: redeck-style-patterns
description: Apply diverse visual design patterns to ReDeck slide generation. Injects real CSS from a 297-pattern library for deck-consistent, high-quality styling. Use when user says "style pattern", "design pattern", "visual style", "slide style", or wants diverse slide aesthetics.
---

# ReDeck Style Pattern Library

Inject diverse, production-quality visual design patterns into slide generation. Each pattern carries **real CSS code** from faithful image-to-HTML reconstructions, ensuring the generated slides look like they were designed in PowerPoint/Keynote, not plain HTML.

## What It Does

1. **Auto-selects** a design pattern based on paper domain (CS → dark+tech, bio-med → light+clean, etc.)
2. **Injects real CSS** (not abstract descriptions) into every slide's generation prompt
3. **Enforces deck-level consistency** — same pattern applies to all slides in one deck
4. **297 patterns** across 7 dimensions, sampled via Latin Hypercube Sampling

## Quick Start

```bash
# Auto-select pattern based on paper content
python scripts/run_pdf_pipeline.py --configs html_codegen --html-codegen \
  --case <case_id> --max-turns 2 --style-pattern auto

# Specify a pattern by ID
python scripts/run_pdf_pipeline.py ... --style-pattern seed_042

# Specify by dimension keyword
python scripts/run_pdf_pipeline.py ... --style-pattern teal-cool
```

## How Pattern Selection Works

When `--style-pattern auto` is used:

1. Paper title is analyzed for domain keywords (neural/learning → CS/ML, protein/clinical → bio-med, etc.)
2. Domain maps to preferred pattern dimensions (CS → dark/mono-tech, bio-med → light/serif-classic)
3. All 297 patterns are scored against preferences + a universal bias toward clean/chart-friendly patterns
4. Top candidates are filtered; one is selected deterministically (md5-seeded by paper title)
5. Same paper title → always same pattern (reproducible)

## Pattern Dimensions (7)

| Dim | Values | Controls |
|-----|--------|----------|
| **bg** | solid, wave-curves, radial-gradient, linear-gradient, geometric, dots-grid, diagonal-lines | Canvas background |
| **lum** | light, dark, medium | Brightness & text contrast |
| **palette** | blue-cool, gray-mono, multi-vibrant, warm-earth, teal-cool, orange-sunset | Color scheme |
| **deco** | none, border-frame, shadow-cards, accent-lines, corner-shapes | Decorative elements |
| **typo** | sans-clean, serif-classic, mono-tech, mixed-editorial, slab-bold | Typography family |
| **layout** | two-column, grid-2x2, left-sidebar, asymmetric-hero, three-column | Spatial composition |
| **content** | chart-focus, data-table, comparison-columns, timeline-nodes, bullet-text | Content archetype |

## Architecture

```
app/style_patterns/
├── __init__.py           # Public API: select_pattern_for_deck, format_deck_style_contract
├── library.json          # 297 patterns with real CSS snippets (~640KB)
├── selector.py           # Domain detection + pattern scoring + deterministic selection
└── injector.py           # Formats pattern as prompt injection with actual CSS code
```

Integration points:
- `ExperimentConfig.style_pattern` — config field
- `HtmlCodeGenCompiler.__init__(style_pattern=...)` — compiler parameter
- `HtmlCodeGenCompiler.compile_deck()` — selects pattern once for entire deck
- `HtmlCodeGenCompiler._build_slide_prompt()` — injects CSS into every slide prompt

## Key Design Decision: Real CSS, Not Descriptions

The pattern library injects **actual CSS code** (up to 1800 chars) from faithful image reconstructions, not abstract keywords like "use blue colors". This is critical — LLMs respond much better to concrete CSS examples than to vague style descriptions.

Example injection:
```
## Deck Design Pattern (follow this visual style closely)
Visual properties: luminance=dark, background=radial-gradient, palette=green-forest

Reference CSS from a real slide design:
```css
body { background: #0a1628; }
.slide { background: radial-gradient(ellipse at 30% 20%, #1a3a2a 0%, #0a1628 70%); }
.title { color: #4ae3b5; font-family: 'Fira Code', monospace; font-size: 38px; }
...
```
```

## Verification

```python
# Test pattern selection
from app.style_patterns import select_pattern_for_deck, format_deck_style_contract

p = select_pattern_for_deck("Deep Learning for Protein Folding")
print(p["dims"])  # Shows selected dimensions
print(format_deck_style_contract(p)[:200])  # Shows CSS injection

# Different paper → different pattern
p2 = select_pattern_for_deck("Market Microstructure under High-Frequency Trading")
assert p["id"] != p2["id"]  # Different domains get different patterns
```
