# ReDeck: Source-Grounded Slide Generation and Repair

[![Paper](https://img.shields.io/badge/Paper-arXiv-b31b1b)](https://arxiv.org/abs/2609.00194) [![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/) [![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

ReDeck generates static HTML slides from documents, inspects their actual browser rendering,
and repairs layout and source-grounded content in one bounded controller. This is a research
preview: machine acceptance is not a substitute for human visual and factual review.

This distribution contains one typed design-library generator and one unified repair runtime.
Historical engines and experiment harnesses are not included in the runtime. The repository retains
the [project website](demo/index.html), [demo video](demo/video.html), [video source](redeck-video/README.md)
and [repair examples with provenance](demo/repair_pairs/README.md) as showcase materials.
Historical paper scores are not claims for this version. Showcase provenance and manual edits
are documented alongside the examples and video.

## Install

Use Python 3.11 or newer, from the repository root:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m playwright install chromium
export OPENAI_BASE_URL="https://your-openai-compatible-endpoint/v1"
export OPENAI_API_KEY="your-api-key"
```

All content probes and their prompts are included; no sibling checkout or private Python
environment is required. `.env.example` is documentation, not an automatically loaded file.
Use `--model` and `--judge-model` to select models supported by your endpoint; the default is
`gpt-5.5`. Requests send source material to that provider and may incur charges.
The optional `--api trapi` route also requires an explicit `OPENAI_BASE_URL` and authorized
Azure credentials; no organization-specific deployment endpoint is bundled.

## Quick Start

Run the bundled synthetic example without a model call:

```bash
redeck generate --case content_repair_smoke --cases-root examples/validation \
  --blueprint examples/validation/content_repair_smoke/blueprint.json \
  --out runs/synthetic-dry --dry-run
```

For a real generation plus joint repair, use a fresh output directory and replace `--dry-run`
with `--repair`. The example reports a controlled 48/100 measurement, not a research result.

Generate from a PDF, including source extraction and blueprint planning:

```bash
redeck generate --pdf /path/to/document.pdf --case my_document \
  --pages 8,12 --out runs/my-document --repair
```

Digital PDF text and figures are extracted locally. OCR/Marker support is optional; scanned
PDFs may need a separately prepared source pack. Empty extraction or failed planning is not
silently accepted as a completed deck.

Already have source materials? Place `paper_full.md`, optional `figures/` and `tables/` with
JSON sidecars under `cases/<case_id>/source_pack/`, then use `--case <case_id>`. Supply
`--blueprint plan.json` to reuse an explicit plan. `redeck codegen` is the lower-level
prepared-plan entry point; `redeck generate` also handles preparation and optional repair.

## Repair and Review

```bash
# Existing generated run: spatial and content routes, parallel checks, one writer per slide
redeck repair --dir runs/my-document/slide_code --source-run runs/my-document \
  -o runs/my-document-repair --attempts 6

# Imported HTML with no source document: explicitly spatial-only
redeck repair slide.html -o runs/layout-repair \
  --probe-routes spatial --content-repair off

# Deterministic checks only; this does not establish visual/content acceptance
redeck spatial slide.html -o runs/spatial-check

# Source-grounded content review of a generation run
redeck judge runs/my-document --output runs/content-review
```

`--probe-routes spatial content` and `--probe-execution parallel` are defaults. Use `serial`
for debugging, or select one route explicitly. `--content-repair off` disables content edits,
not content detection. Six candidates is the default and maximum CLI budget per slide;
content, layout and final-review reentry share that budget. There is no extra spatial loop.

`ready_for_human_review` is not an unconditional pass. Spatial-only runs retain
`needs_evaluation` overall because content was not checked. Counts separate geometry,
readability, style advisories and repair blockers; an unchanged decorative gradient is not
an unresolved overlap. See [runtime architecture](docs/ARCHITECTURE.md).

## Design Controls

```bash
redeck generate --case my_document --blueprint plan.json --out runs/my-style \
  --palette blue-corporate --lum dark --style-archetype technical-instrument \
  --information-density evidence-rich --asset-mode preserve --repair
```

- Theme owns colors; `--design-family` selects non-color materials (`--dialect` is an alias).
- One Slide Design Program combines content requirements, typed materials and compatibility checks.
- `--asset-mode auto|preserve|table|chart` controls assigned source visuals. `preserve` embeds the
  original image; table/chart reconstruction requires extracted table data. Per-asset overrides
  use `--asset-policy`. Do not invent chart values when source data is unavailable.
- Source images are evidence. Full BAMS templates and their screenshots are not generation inputs.

Use `redeck codegen --help` for the complete options. Library artifacts are packaged with the
runtime; rebuilding from original seeds is an offline operation requiring separately supplied materials.

## Artifacts and Compatibility

Generation saves its frozen source context, design programs, prompts, HTML, screenshots and
review reports in the chosen directory. Repair saves T0, candidates, diagnostics, acceptance
decisions and formal T1 without overwriting its input. Use fresh directories for new experiments.

`slide-agent` and `python -m app.main` dispatch to the same current CLI. The old script names
`redeck_repair.py`, `redeck_loop.py`, `redeck_spatial.py`, `redeck_judge.py` and
`run_pdf_pipeline.py` are thin aliases, not independent engines. Their historical argument
sets are not universally interchangeable; see [migration and compatibility](docs/MIGRATION.md).

The historical `redeck-legacy` entry point and its implementation are removed. Compatibility
aliases only call the current runtime; unsupported historical experiment configs fail explicitly.

## Development

```bash
python -m pytest
python -m pytest tests/showcase
python -m build
```

`pyproject.toml` is the dependency source of truth; the requirements files are install aliases.
Wheels include design artifacts, content-probe prompts and synthetic examples. Current tests
live under `tests/current/`; they cover runtime behavior, content authorization, snapshot integrity
and packaging boundaries.
The planner's deterministic regression fixture lives under `tests/fixtures/`, not in runtime inputs.
Repository-only showcase tests check website links, demo assets, narration and deployment files;
CI runs them alongside runtime tests. They are excluded from Python packages with the showcase assets.
See [release structure and compatibility](docs/MIGRATION.md) for the retained file boundaries.

Offline builders under `scripts/build_*library.py` and `scripts/extract_*.py` remain so the typed
library can be maintained. Their metadata is intermediate design material, not source-document
answers or a second online generation engine. Original seeds must be provided separately.
`scripts/extract_patterns.py --seeds-dir SEEDS --catalog CATALOG --out OUTPUT` rebuilds seed metadata.
`scripts/build_runtime_library.py --seeds-dir SEEDS --out OUTPUT` rebuilds the typed artifacts;
it requires a seed HTML file for every catalog entry and refuses incomplete inputs.
`scripts/build_probe_registry.py --out OUTPUT` compiles atomic checks from the maintained probe
definitions and rubrics. Use `python -m build` to create Python distributions.

Do not treat raw HTML execution as sandboxed, export private source packs, or redistribute
third-party materials without checking their permissions. See [SECURITY.md](SECURITY.md).
The existing project [license](LICENSE) is unchanged by this runtime migration.
