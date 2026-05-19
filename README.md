# ReDeck: Step-Level Render-Grounded Refinement for Document-to-Slide Generation

> **Re**fine + **Deck** = ReDeck

An LLM-powered system that generates presentation slide decks from academic papers, using multi-granular feedback to combine step-level render-grounded repair with turn-level adaptive critique.

## Overview

ReDeck takes a PDF paper as input and produces a polished slide deck through:

1. **PDF Extraction** -- Parse paper into structured content (text sections, figures, tables, formulas) via Marker
2. **Deck Planning** -- LLM generates a slide blueprint with layout specifications and evidence linking
3. **Code Generation** -- Each slide is generated as HTML/CSS, rendered to PNG via Playwright, then packaged into PPTX
4. **Turn-Level Adaptive Deck Critic** -- Five specialized judge families (correctness, completeness, fidelity, visual, narrative) update a persistent issue list for deck-wide semantic and design guidance
5. **Step-Level Render-Grounded Repair** -- An LLM agent performs atomic edits and receives renderer-derived observations after each step via tools such as apply_edits, verify_layout, and render_preview

The system runs multiple refinement turns until convergence or a turn budget is exhausted.

## Architecture

```
PDF Paper
    |
    v
[Marker Processor] --> source_pack/ (paper_full.md + figures/ + tables/)
    |
    v
[Source Indexer] --> EvidenceState (chunks + figures + tables + BM25 index)
    |
    v
[Deck Planner] --> DeckBlueprint (slide titles, layouts, evidence links)
    |
    v
[HTML CodeGen Compiler] --> HTML slide code --> Playwright PNG render --> PPTX packaging
    |
    v
[Turn-Level Adaptive Deck Critic] --> persistent issue list (per-slide, multi-judge)
    |       \
    |        [Step-Level Render Feedback] (overlap, overflow, clipping)
    |        [Correctness Judge] (factual accuracy vs source)
    |        [Completeness Judge] (content coverage)
    |        [Fidelity Judge] (faithfulness to source)
    |        [Visual Judge] (layout quality, readability)
    |        [Narrative Judge] (flow, coherence)
    |
    v
[Step-Level Repair Agent] --> fixed HTML code --> re-render --> re-evaluate
    |
    v
[Turn Settler] --> convergence check --> next turn or stop
```

## Project Structure

```
app/
  orchestrator/          # Pipeline orchestration
    run_manager.py       # Main entry: multi-turn loop
    eval_router.py       # Dispatches evaluation across judges
    render_manager.py    # PPTX rendering via Playwright/LibreOffice
    turn_settler.py      # Convergence & turn budget logic
  modules/
    deck_planner.py      # Blueprint generation
    slide_layout_designer.py  # Layout constraint specification
    source_indexer.py    # PDF content indexing (BM25)
    evaluators/          # 5 judges + geometry checks
    redeck/              # Agent-based repair loop
      agent_repair.py    # Core repair agent with tool use
      repair_worker.py   # Multi-slide repair orchestration
  backends/
    html_codegen/        # HTML/CSS slide generation, Playwright rendering, PPTX packaging
      html_codegen_compiler.py  # Main slide compiler
  schemas/               # Pydantic data models
  prompts/               # System prompts for all LLM calls
  llm_client.py          # OpenAI-compatible API wrapper
configs/                 # Experiment configurations
scripts/                 # Pipeline runner scripts
skills/                  # Standalone Claude Code skill prompt
demo/                    # Static project website and demo assets
tests/                   # Unit tests
```

## Quick Start

### Prerequisites

- Python 3.11+
- OpenAI API access or an OpenAI-compatible API endpoint
- Playwright (for HTML to PNG rendering)
- LibreOffice (for PPTX to PDF conversion, optional)

### Setup

```bash
pip install -e .
playwright install chromium
```

### Environment Variables

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-4o"

# Optional: set this for an OpenAI-compatible proxy or local server.
export OPENAI_BASE_URL="https://api.example.com/v1"
```

### Run

```bash
# Create a case from a PDF
python3.11 scripts/run_pdf_pipeline.py \
    --case my_paper \
    --html-codegen \
    --max-turns 3

# Repair an existing directory of HTML slides
python3.11 scripts/redeck_loop.py \
    --dir path/to/slides \
    --max-turns 3
```

### Input Format

Place source materials in `cases/<case_id>/source_pack/`:
```
source_pack/
  paper_full.md          # Full paper text (Markdown, from Marker)
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
- `deck_blueprint.json` -- Slide plan
- `slide_code/` -- Generated HTML per slide
- `slide_png/` -- Rendered slide images
- `eval/issues.jsonl` -- Detected issues
- `turn_summary.json` -- Metrics and convergence info

## Claude Code Skill

This repository also includes a standalone Claude Code skill in `skills/redeck.md`. The skill packages the core ReDeck prompt and an embedded Playwright-based `verify_layout` tool so Claude Code can generate or repair HTML slides with a lightweight edit-render-observe loop. It is intended for use cases where a user wants step-level render feedback without running the full multi-turn pipeline.

## Demo Website

The `demo/` directory is a static website: plain HTML, CSS, images, and video assets. It can be hosted directly with GitHub Pages from the repository's `demo/` folder, or by copying `demo/` into a `gh-pages` branch.

For an official Microsoft-owned GitHub repository, the simplest setup is:

1. Keep the static site in `demo/`.
2. Enable GitHub Pages in repository settings.
3. Set the Pages source to GitHub Actions or to a branch/folder policy approved for the organization.
4. If using Actions, publish `demo/` as the Pages artifact; no Node build step is required.

## Key Design Decisions

- **HTML as intermediate representation**: Slides are generated as HTML, rendered to PNG via Playwright, then converted to PPTX. This gives full CSS layout control vs. python-pptx's limited API.
- **Multi-granular feedback**: Step-level render feedback catches local spatial errors immediately, while the turn-level Adaptive Deck Critic tracks semantic, design, and evidence-grounding issues across the deck.
- **Persistent issue list**: Critic outputs are stored as structured issues, so an issue is resolved only after re-evaluation rather than by agent self-report.
- **Step-level repair**: The repair agent uses tools such as apply_edits, verify_layout, and render_preview to perform atomic edits and observe rendered consequences within the same turn.
- **Evidence-grounded generation**: Every slide is linked to source evidence chunks, enabling factual verification by judges.

## License

MIT
