# ReDeck: Environment-Grounded Slide Generation and Refinement

*Turn slide refinement from “one draft, one verdict” into “one edit, one observation” — so the model can see what it changed before it moves on.*

[![Project Page](<https://img.shields.io/badge/Project%20Page-ReDeck-FF6B35>)](https://aka.ms/ReDeck) [![Paper](https://img.shields.io/badge/Paper-arXiv-b31b1b)](https://arxiv.org/abs/2609.00194) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview

Today's slide agents can produce an impressive first draft, but they still revise it almost blind. A model may fix one overlap while creating another, or improve the layout at the cost of content fidelity. Templates avoid some of these failures, but only by limiting what the model can design.

**ReDeck treats the rendered deck as part of the agent's environment.** It breaks revision into small edits, renders after every step, and shows the agent the spatial consequences before it continues. A deck-level critic handles narrative and content quality, while a final validation gate keeps new layout failures from slipping through.

With this repo, you can:

- **Generate** a complete, source-grounded deck from a paper or document.
- **Repair** existing HTML slides with overflow, overlap, clipping, contrast, and other spatial issues.
- **Inspect and extend** every stage through saved slide code, renders, issue traces, and turn-by-turn artifacts.

ReDeck is designed for researchers, students, educators, designers, and developers who need to turn source documents into presentation decks or systematically improve decks they already have. Across GPT-5.4, Claude-4.6, and Gemini-3.1, it consistently improves document-to-slide generation; on GPT-5.4, refinement raises spatial clean rate by **27.4 points**, content fidelity by **8.2 points**, and aesthetics by **0.69** over the initial draft. See the [paper](https://arxiv.org/abs/2609.00194) for the full evaluation and the [project page](https://aka.ms/ReDeck) for examples.

## 🎬 Demo Video

https://github.com/user-attachments/assets/c3f5d87e-d96e-4da0-b5de-f242e23bbc54

---

## Quick Start

### Setup

```bash
pip install -e .
playwright install chromium
```

### Environment Variables

```bash
export OPENAI_BASE_URL="https://your-api-endpoint/v1"
export OPENAI_API_KEY="your-key"
```

### Generate slides from a document

```bash
python scripts/run_pdf_pipeline.py \
    --case my_document \
    --configs html_codegen \
    --html-codegen \
    --max-turns 3 \
    --model gpt-5.5
```

### Fix layout issues in existing slides

```bash
# Single slide
python scripts/redeck_repair.py my_slide.html -o repaired/ --model gpt-5.5

# Batch of slides
python scripts/redeck_repair.py --dir path/to/slides/ -o repaired/ --model gpt-5.5

# Multi-turn repair loop
python scripts/redeck_loop.py --dir path/to/slides --max-turns 3 --model gpt-5.5
```

### Theme selection

A theme is automatically selected based on the input document. To override:

```bash
python scripts/run_pdf_pipeline.py --case my_doc --html-codegen --theme-id coral_tide
```

Available themes include `ocean_breeze`, `coral_tide`, `sea_glass`, `editorial_slate`, and others. See `app/themes.py` for the full list.

### Input format

Place source materials in `cases/<case_id>/source_pack/`:

```
source_pack/
  paper_full.md          # Source document text in Markdown
  figures/               # Extracted figures with JSON sidecar
    fig_p1_fig1.png
    fig_p1_fig1.json     # {caption, page, bbox, ...}
  tables/                # Extracted tables with JSON sidecar
    tbl_p5_tbl1.png
    tbl_p5_tbl1.json
  screenshots/           # Page screenshots (optional)
```

### Output

Each run produces per-turn artifacts in `runs/<run_id>/turn_XX/`:

- `deck_blueprint.json` — Slide plan
- `slide_code/` — Generated HTML per slide
- `slide_png/` — Rendered slide images
- `eval/issues.jsonl` — Persistent issue list updates
- `turn_summary.json` — Turn-level convergence summary

---

## How it works

ReDeck runs a multi-turn pipeline:

1. **Document Extraction** — Parse the source into text, figures, tables, and formulas
2. **Deck Planning** — Generate a slide blueprint with layout and evidence links
3. **HTML/CSS Generation** — Generate each slide as HTML/CSS, render via Playwright
4. **Adaptive Critic** — Evaluate the deck across 5 dimensions (visual, narrative, correctness, completeness, fidelity)
5. **Step-Level Repair** — An LLM agent applies atomic edits, gets render feedback after each edit, and rolls back or retries as needed

The key insight: **the repair agent sees rendered results after every edit, not just at the end of a turn.** This lets it catch and fix spatial issues (overflow, overlap, clipping) while their causes are still clear.

<p align="center">
  <img src="assets/redeck_pipeline.png" alt="ReDeck pipeline" width="780"/>
</p>

## Spatial Issue Detection

The detection engine (`app/modules/redeck/html_spatial_state.py`) renders each slide via Playwright and extracts spatial state through DOM geometry analysis:

| Category                | What it catches                                                                                                                                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Overlap**       | Sibling elements colliding (partial or full containment), with filters for legitimate nesting (parent-child, SVG rect+text)                                                                                   |
| **Text overflow** | Content exceeding its container via`scrollHeight > clientHeight`, styled-boundary overflow (`overflow:visible` past CSS height), and SVG text exceeding sibling rects (using `getComputedTextLength()`) |
| **Clipping**      | Content hidden by`overflow:hidden` ancestors                                                                                                                                                                |
| **Out-of-bounds** | Elements extending past the 1280×720 slide canvas                                                                                                                                                            |
| **Low contrast**  | WCAG AA violations for text (including SVG`fill`-based text)                                                                                                                                                |
| **Occlusion**     | Higher z-index opaque elements covering content (full and partial)                                                                                                                                            |
| **SVG internals** | viewBox clipping of all SVG elements (not just text), text-rect overflow within SVG                                                                                                                           |

All detections pass through `count_significant_issues()` — the single source of truth for defect thresholds — ensuring the repair agent and external scorers agree on issue counts.

## Project Structure

```
app/
  orchestrator/          # Pipeline orchestration
    run_manager.py       # Main entry: multi-turn loop
    eval_router.py       # Dispatches evaluation across judges
    render_manager.py    # Rendering via Playwright/LibreOffice
    turn_settler.py      # Convergence & turn budget logic
  modules/
    deck_planner.py      # Blueprint generation
    source_indexer.py     # Document content indexing (BM25)
    evaluators/           # Critic checks, judges, and geometry probes
    redeck/               # Step-level repair loop
      agent_repair.py     # Core repair agent with tool use
      html_spatial_state.py  # Playwright-based spatial detection engine
      spatial_state.py    # ContentBlock / SlideState data structures
  backends/
    html_codegen/         # HTML/CSS slide generation and Playwright rendering
  schemas/                # Pydantic data models
  prompts/                # System prompts for LLM calls
    probes/               # 30+ evaluation probes across 5 dimensions
  llm_client.py           # OpenAI / Azure OpenAI API wrapper
configs/                  # Run configurations
scripts/                  # Pipeline and repair CLI scripts
demo/                     # Static project website and demo assets
  repair_pairs/           # 14 before/after repair examples (HTML + PNG)
assets/                   # README and paper figures
tests/                    # Unit tests
```

## Demo Website

The `demo/` directory includes a static website with project pages, examples, and video assets. It can be hosted with GitHub Pages.

## License

This project is licensed under the [MIT License](LICENSE).
