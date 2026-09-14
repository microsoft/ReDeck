---
name: redeck
description: Generate document-grounded HTML slides or repair existing slides using the installed ReDeck pipeline, its design controls and auditable probe reports.
---

# ReDeck

Use the installed `redeck` CLI, not a hand-written detector or an additional edit loop.
Start with `redeck --help`; use each subcommand's `--help` for the installed option contract.
If the CLI is unavailable, install the project and Playwright Chromium before running slides.

## Choose the entry point

- `redeck generate --pdf document.pdf --case my_document --out runs/new-run --repair`
  prepares sources, plans and generates before optional unified repair.
- `redeck generate --case my_document --blueprint plan.json --out runs/new-run`
  uses prepared sources and an explicit plan. `--dry-run` avoids model calls and requires a plan.
- `redeck repair --dir runs/new-run/slide_code --source-run runs/new-run -o runs/new-repair`
  repairs against frozen source evidence, with parallel spatial/content checks by default.
- For imported HTML without source evidence, explicitly choose
  `redeck repair slide.html -o runs/layout-only --probe-routes spatial --content-repair off`.
- `redeck spatial slide.html -o runs/new-check` runs deterministic checks only.

Use fresh output paths. Do not overwrite frozen experiments or feed historical repaired/golden
slides into a live repair request. Source documents must be authorized for the configured provider.

## Preserve the runtime contract

Choose theme, design family, density and asset presentation through CLI options. Do not inject
an additional full-page style template. `preserve` retains assigned source images; `table` or
`chart` reconstruction requires extracted data, not guessed numbers.

Checks can be parallel, but a page has one writer and at most six shared candidate attempts.
Do not add a spatial-only retry budget after joint repair. Content-edit permission comes from
confirmed source-scoped findings, not from visually noticing that wording could be different.

Inspect formal T1 PNGs and reports, not only the last candidate. Distinguish geometry/readability
blockers from style advisories. `ready_for_human_review` is not perfect factual/visual quality;
`needs_evaluation` in spatial-only mode correctly records missing content coverage.
Report remaining defects and budget exhaustion instead of silently expanding the loop.
