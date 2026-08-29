# ReDeck: Step-Level Render-Grounded Refinement for Document-to-Slide Generation

*Generate presentation slides from documents — then automatically detect and repair spatial layout issues through render-grounded feedback, without manual intervention.*

[![Project Page](https://img.shields.io/badge/Project%20Page-ReDeck-4285f4)](https://microsoft.github.io/ReDeck/) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎬 Demo Video

https://github.com/user-attachments/assets/c3f5d87e-d96e-4da0-b5de-f242e23bbc54

---

## Overview

Most iterative slide agents follow a monolithic "one version, one feedback" loop: they rewrite a slide or deck, render it afterward, and receive feedback only at the turn boundary. That delayed feedback makes local spatial failures — overflow, overlap, clipping, low contrast, occlusion — hard to attribute to the edit that caused them.

**ReDeck changes the refinement loop to "one edit, one observation."** During a refinement turn, the agent edits the deck through atomic actions and receives Playwright-rendered observations after each step. This lets the agent fix local layout errors while their causes are still clear, while the turn-level critic tracks global issues such as narrative flow, completeness, correctness, and source fidelity.

<p align="center">
  <img src="assets/redeck_pipeline.png" alt="ReDeck pipeline" width="780"/>
</p>

## Method

Each ReDeck refinement turn nests two feedback scales:

1. **Turn-level Adaptive Deck Critic** — At the start of each turn, the critic evaluates the deck source and rendered slides, schedules a focused subset of checks, and updates a persistent issue list. The issue list records what remains unresolved across narrative, visual layout, completeness, correctness, and source fidelity.
2. **Step-level render feedback** — Within the turn, every atomic edit is followed by rendering and structured observation. The observation reports the violation delta relative to the turn-start baseline and a layout anchor containing key element positions, dimensions, and text previews.
3. **Submission-level validation gate** — Step-level feedback is an observation, not a verdict: temporary invalid states are allowed during repair. The hard gate appears only when the agent submits the turn, where newly introduced hard layout violations must be resolved before the deck state can advance.

This separation assigns feedback to the level where it is most reliable: deterministic renderer observations handle local spatial failures, the critic handles deck-wide semantic and design direction, and the submission gate prevents transient layout defects from becoming persistent progress.

## Spatial Issue Detection

ReDeck's detection engine (`app/modules/redeck/html_spatial_state.py`) renders each HTML slide via Playwright and extracts a structured spatial state through DOM geometry analysis. It detects:

| Category | What it catches |
|----------|----------------|
| **Overlap** | Sibling elements colliding (partial or full containment), with filters for legitimate nesting (parent-child, SVG rect+text) |
| **Text overflow** | Content exceeding its container via `scrollHeight > clientHeight`, styled-boundary overflow (`overflow:visible` past CSS height), and SVG text exceeding sibling rects (using `getComputedTextLength()`) |
| **Clipping** | Content hidden by `overflow:hidden` ancestors |
| **Out-of-bounds** | Elements extending past the 1280×720 slide canvas |
| **Low contrast** | WCAG AA violations for text (including SVG `fill`-based text) |
| **Occlusion** | Higher z-index opaque elements covering content (full and partial) |
| **SVG internals** | viewBox clipping of all SVG elements (not just text), text-rect overflow within SVG |

All detections pass through `count_significant_issues()` — the single source of truth for defect thresholds — ensuring the repair agent and external scorers agree on issue counts.

## Pipeline

ReDeck takes documents such as scientific papers, technical reports, or business analyses as input and produces editable presentation decks through:

1. **Document Extraction** — Parse the source document into structured text, figures, tables, formulas, and page screenshots.
2. **Evidence Indexing** — Build a searchable evidence state over source chunks, figures, tables, and page-level context.
3. **Deck Planning** — Generate a slide blueprint with slide intentions, layout specifications, and evidence links.
4. **HTML/CSS Code Generation** — Generate each slide as HTML/CSS, render it to PNG via Playwright, and package the rendered slides into PPTX.
5. **Adaptive Deck Critic** — Update the persistent issue list using specialized checks for correctness, completeness, source fidelity, visual quality, and narrative flow.
6. **Step-Level Repair Agent** — Apply atomic edits, observe rendered consequences, rollback or retry when needed, and submit only after validation passes.

## Architecture

```
Document
    |
    v
[Document Processor] --> source_pack/ (text + figures + tables + screenshots)
    |
    v
[Source Indexer] --> EvidenceState (chunks + figures + tables + retrieval index)
    |
    v
[Deck Planner] --> DeckBlueprint (slide intents, layouts, evidence links)
    |
    v
[HTML CodeGen Compiler] --> HTML slide code --> Playwright PNG render --> PPTX packaging
    |
    v
[Turn-Level Adaptive Deck Critic] --> persistent issue list
    |       \
    |        [Narrative]       flow and coherence
    |        [Visual/Layout]   readability and spatial quality
    |        [Completeness]    coverage of required content
    |        [Correctness]     factual accuracy vs source
    |        [Source Fidelity] faithfulness and traceability
    |
    v
[Step-Level Repair Agent]
    |  atomic edit -> render -> observe -> rollback/retry/submit
    v
[Submission Gate] --> next turn or further repair
```

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

## Quick Start

### Prerequisites

- Python 3.11+
- An OpenAI API key (or Azure OpenAI endpoint)
- Playwright for HTML rendering

### Setup

```bash
pip install -e .
playwright install chromium
```

### Environment Variables

```bash
# Option 1: OpenAI-compatible API (recommended)
export OPENAI_BASE_URL="https://your-api-endpoint/v1"
export OPENAI_API_KEY="your-key"

# Option 2: Azure OpenAI
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
# Uses AzureCliCredential by default; set REDECK_AZURE_AUTH=api_key for static keys
```

### Repair a Single Slide

```bash
# Fix spatial issues in one HTML slide
python scripts/redeck_repair.py my_slide.html -o repaired/ --model gpt-5.5
```

### Repair a Batch of Slides

```bash
python scripts/redeck_repair.py --dir path/to/slides/ -o repaired/ --model gpt-5.5
```

### Run the Full Pipeline

```bash
# Generate a deck from a prepared document case
python scripts/run_pdf_pipeline.py \
    --case my_document \
    --configs html_codegen \
    --html-codegen \
    --max-turns 3 \
    --model gpt-5.5

# Multi-turn repair loop on existing slides
python scripts/redeck_loop.py \
    --dir path/to/slides \
    --max-turns 3 \
    --model gpt-5.5
```

### HTML Design Profile

Default HTML generation uses the demo-derived `demo_curated` palette pool and
selects a content-driven composition grammar for each slide. The default set
includes editorial statements, annotated figures, quantitative stories,
comparative fields, process/system diagrams, timelines, evidence dashboards,
and structured evidence grids. The generated design contract specifies the
dominant object, evidence structure, visual devices, spatial rhythm, and depth
strategy instead of selecting a fixed slide template.

The compiler also retrieves two or three component-level HTML visual skills for
each slide. These are compact CSS/HTML/SVG references for elements such as
editorial headers, inspectable figures, process topology, metric rails, ranked
evidence rows, quantitative tables, comparison fields, and phase paths. Skills
describe local element language and composition affordances; they do not
provide whole-page coordinates. A deck keeps one deterministic palette while
its slides may compose different skills and layouts.

Use `--html-theme coral_tide` on the PDF pipeline CLI, or set `html_theme`
in an experiment config to control palette selection:

```json
{
  "use_html_codegen": true,
  "html_theme": "coral_tide"
}
```

Use `"legacy"` to select from the original five-theme pool, or pin any concrete
theme ID such as `"ocean_breeze"`, `"sea_glass"`, or `"editorial_slate"`.

### Input Format

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


## Demo Website

The `demo/` directory includes a static website with project pages, examples, and video assets. It can be hosted with GitHub Pages.

## License

This project is licensed under the [MIT License](LICENSE).
