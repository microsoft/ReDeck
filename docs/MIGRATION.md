# Release Structure and Compatibility

This distribution contains the current HTML generator, source-grounded probes and unified
repair controller. It does not ship the original paper-era runtime. The repository also retains
the public website and historical showcase materials, separate from the Python runtime package.

## Repository structure

| Path | Purpose |
| --- | --- |
| `redeck_style/` | Current design planning, rendering contracts, source authorization and repair policies |
| `app/` | Shared PDF/source preparation, schemas, probe runner and required helpers only |
| `scripts/` | Current CLI implementations, thin compatibility aliases and offline library builders |
| `pattern_library/artifacts/` | Typed runtime vocabulary, design families and compatibility graph |
| `pattern_library/metadata/` | Theme data and intermediate inputs for rebuilding/evaluating the design library |
| `examples/validation/content_repair_smoke/` | Small synthetic source, explicit blueprint and HTML for trying the runtime |
| `tests/current/`, `tests/fixtures/` | Maintained regression suite; fixtures are not generation defaults or benchmark claims |
| `tests/showcase/` | Repository-only checks for website/video resources |
| `docs/`, `skills/`, `.github/` | Architecture, compatibility, agent usage, CI and dependency maintenance |
| `demo/` | Public website, video, poster, and 14 before/after pairs with provenance disclosures |
| `redeck-video/`, `assets/` | Remotion source, narration, licensed music, trajectory images and project diagrams |

Scene-extraction helpers support spatial diagnostics as well as offline library maintenance.
The planner regression fixture is explicitly passed by tests, not selected by case ID.
Lower-level codegen accepts an explicit blueprint or an existing local run;
use `redeck generate` to prepare a new document and plan it.

Raw runs and showcase assets are not included in wheel/sdist. The website and video project
remain available in the repository, with [example provenance](../demo/repair_pairs/README.md)
documented separately from runtime behavior.

## Supported compatibility

| Previous command | Current destination |
| --- | --- |
| `slide-agent`, `python -m app.main` | Current `redeck` command dispatcher |
| `scripts/redeck_repair.py`, `scripts/redeck_loop.py` | `redeck repair` |
| `scripts/redeck_spatial.py` | `redeck spatial` |
| `scripts/redeck_judge.py` | `redeck judge` |
| `scripts/run_pdf_pipeline.py` | `redeck generate` |

Compatibility `--spatial-only` maps to `--probe-routes spatial --content-repair off`.
`--max-turns` maps, with a warning, to a single shared `--attempts` budget in the range 1–6.
Historical experiment configs and PPTX-specific workflows are not supported and do not silently
fall back to a deleted engine. PDF input remains supported; this release produces HTML and PNG.

`--legacy-root` remains a deprecated alias for a trusted `--probe-root` override; it does not
enable a legacy repair implementation. No sibling checkout or private interpreter is required.

## Build and test

`pyproject.toml` is the dependency source of truth. PyMuPDF provides PDF input; PPTX export is not
supported. Runtime resources use explicit
package-data declarations. Tests and documentation are included in the source distribution,
but not imported by the installed application.

Run `python -m pytest` and `python -m build`. Exercise the installed wheel from a directory outside
the checkout to verify that it does not rely on source-only files. Regression tests validate
implementation behavior; they do not measure model output quality.
Run `python -m pytest tests/showcase` in the repository for website/video integrity; these checks
are also required by CI but do not ship in Python source distributions without their assets.

The Pages workflow publishes `demo/`. The Remotion project builds the MP4 into `demo/assets/`.
See the [video source and build instructions](../redeck-video/README.md).
