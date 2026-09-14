# Current Runtime Architecture

## One default pipeline

```text
PDF / source_pack + optional explicit blueprint
  → shared CaseCreator / CaseLoader / DeckPlanner
  → content profile + theme + typed material selection + compatibility graph
  → one Slide Design Program per slide
  → model-generated static HTML → shared browser snapshot
  → deterministic spatial + VLM visual + source-grounded content probes
  → one bounded joint repair controller → formal T1 + evidence trail
```

`redeck_style/cli.py` dispatches public commands. `scripts/generate.py` prepares sources/plans
and calls `scripts/codegen.py`; it does not reimplement generation. Planning uses the same
transport as codegen. New planning fails closed rather than silently using the historical
skeleton fallback. `scripts/repair.py` and `scripts/repair_session.py` own the current repair
entry point and session orchestration; compatibility commands invoke them directly.

## Responsibilities

| Component | Responsibility |
| --- | --- |
| `redeck_style/domain/` | Typed programs, constraints, density and asset presentation |
| `redeck_style/library/` | Load versioned materials; compatibility and interface checks |
| `redeck_style/planning/` | Content profiling, deck consistency and slide-level selection |
| `redeck_style/rendering/` | One authoritative generation prompt from the program |
| `pattern_library/artifacts/` | Runtime typed vocabulary, material families and graph |
| `pattern_library/metadata/` | Color themes and offline source metadata; not extra prompt authorities |
| `redeck_style/evaluation/` | Shared snapshots, reading view, probe routing, evidence contracts and reporting |
| `scripts/content_probe_worker.py` | Isolated worker using bundled `app.modules.evaluators.ProbeRunner` |
| `redeck_style/repair.py`, `typography.py` | Scope, semantics, typography and acceptance policy |
| `redeck_style/content_repair.py` | Source inventory, scoped proposals and content authorization |
| `app/modules/source_store/`, `app/schemas/`, `app/prompts/probes/` | Shared source models, schemas and C/D/E probe definitions |

Content probes are not copied into a second implementation. The worker defaults to the
installed package root and current Python interpreter. `--probe-root`/`REDECK_PROBE_ROOT`
is an explicit trusted override, not automatic discovery of another checkout.

## Generation decisions

Theme controls colors only. A design family (historically called a dialect) constrains
non-color materials: background treatment, typography, separators and motifs. Content and
layout vocabularies supply semantic forms and coarse spatial organization. Typed graph
edges contribute layout/content matching, same-source coherence and interface checks.
They do not prove that a rendered page will be readable or factual.

The planner resolves those decisions into a single program. The realization model can vary
composition within its constraints but cannot use a complete original BAMS page as a template.
Density and source-asset presentation are independent options, not alternate repair engines.

## Unified repair

- Checks may run in parallel; each slide still has one writer and one candidate sequence.
- Content edits need confirmed, in-scope findings and frozen source evidence. Unresolved
  observations, malformed probe output or missing source context do not authorize edits.
- Layout-only repair preserves visible information. Content and layout can be changed together
  when source-authorized correction requires reflow.
- Candidate budget, working state, accepted state, final review and original fallback remain
  explicit. The CLI uses at most six candidates per page, including final-review reentry.
- Current typography policy retains original role identity across SVG line wrapping; permits
  modest role-aware font reduction; distinguishes SVG viewport reflow from explicit compression;
  enforces effective rendered font floors and requests visual review when appropriate.
- Regional/table capacity feedback and browser Range rectangles detect actual cell-word overflow.
  Whole-page screenshots and VLM inspection complement, rather than replace, those checks.
- Raw counts remain auditable. Geometry and low contrast block repair acceptance; pre-existing
  gradient advisories remain visible without masquerading as spatial defects.

## Distribution boundary

The historical orchestrator, backends, agent repair, style-template implementation and their
entry points are removed. `app/` contains only shared preparation, source models, schemas,
probe implementations and their dependencies. Compatibility scripts dispatch to the current CLI.
Offline library builders remain separate from online decisions; their metadata supports library
maintenance and scene diagnostics. The repository retains the website, demo media, diagrams and
video project as a separate showcase layer. They are excluded from Python wheel/sdist packages,
not deleted from the repository. Raw experiment runs remain excluded.

Current security remains local-research oriented: browser JavaScript and remote resources are
disabled for snapshots, but this is not OS isolation. Use disposable environments for untrusted HTML.
