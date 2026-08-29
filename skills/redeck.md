# ReDeck: Judge-Repair Quality Assurance for HTML Slides

**Load this skill when:** generating, editing, or reviewing HTML slides (1280×720px viewport) to detect and fix layout/content issues.

---

## Core Insight: Edit-Verify Feedback Loop

The central mechanism of ReDeck is **`verify_layout`** — a Playwright-based renderer that the repair agent calls **after every edit** to get immediate, pixel-precise spatial feedback. This creates a tight closed loop *inside* each repair session:

```
tool call 1:  plan           → "Fix 3 overlaps + 1 overflow"
tool call 2:  apply_edits    → Move .content down 80px, reduce font to 18px
tool call 3:  verify_layout  → "✅ overlap resolved, but ❌ NEW clipped: 24px hidden"
tool call 4:  apply_edits    → Increase parent height by 30px
tool call 5:  verify_layout  → "✅ all clean, coverage 72%"
tool call 6:  submit
```

**Why this matters:** Layout issues (overlap, overflow, clipping) are invisible in source code. An LLM editing CSS has no way to know if `top: 380px` causes an overlap without rendering. `verify_layout` gives the agent a **ground-truth spatial oracle** at every tool call — it can see the consequences of each edit, catch regressions instantly, and rollback bad changes before they compound.

**Without ReDeck** (screenshot-only self-repair): the LLM gets one screenshot, guesses at pixel positions, writes CSS blindly, and hopes it works. Fix rate: 37%.

**With ReDeck** (`verify_layout` after every edit): the agent gets exact bounding boxes, overflow amounts in pixels, and intersection areas — and can course-correct in real time. Fix rate: 93%.

---

## Architecture

### The Spatial Oracle

At the foundation of ReDeck is a single Playwright-based spatial detection engine: `extract_html_slide_state()`. It renders HTML, queries every DOM element's bounding box, scrollHeight, contrast ratio, z-index, etc., and returns a structured `SlideState` — pixel-precise ground truth about the layout.

This one engine is invoked at **three levels**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    extract_html_slide_state()                       │
│                    (the spatial oracle)                              │
│                                                                     │
│  Used by:                                                           │
│                                                                     │
│  1. redeck_spatial.py    — standalone CLI for quick spatial checks   │
│                            ("does this slide have layout issues?")   │
│                                                                     │
│  2. Judge Layer 1        — first layer of redeck_judge.py           │
│     (DeterministicGeomChecks)  produces Issue[] for the outer loop  │
│                                                                     │
│  3. verify_layout tool   — called by repair agent after EVERY edit  │
│                            provides per-tool-call feedback in the   │
│                            inner edit-verify loop                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Two Nested Feedback Loops

The workflow is **Judge → Repair → Re-judge**:

```
OUTER LOOP (turns — managed by run_manager / redeck_loop.py):
┌──────────────────────────────────────────────────────────┐
│ Turn 0: Judge → Issue[]                                  │
│ Turn 1: Repair → Re-judge → Issue[] (diff vs Turn 0)     │
│ Turn 2: Repair → Re-judge → Issue[] (diff vs Turn 1)     │
│ ...until convergence or max turns                        │
└──────────────────────────────────────────────────────────┘
        ▲ spatial oracle invoked per turn
        │ (produces Issue list for repair)

INNER LOOP (tool calls — within a single AgentRepair session):
┌──────────────────────────────────────────────────────────┐
│ plan → apply_edits → verify_layout → apply_edits →       │
│ verify_layout → ... → submit                             │
│                                                          │
│ verify_layout called after EVERY structural edit.        │
│ If regression detected → rollback → try different fix.   │
└──────────────────────────────────────────────────────────┘
        ▲ spatial oracle invoked per tool call
        │ (provides instant feedback within one repair session)
```

### CLI Tools

| Script | Role | LLM Required |
|--------|------|-------------|
| `scripts/redeck_spatial.py` | Spatial oracle CLI — standalone spatial checks | No |
| `scripts/redeck_judge.py` | Full evaluation (Layer 1 = spatial oracle; Layers 2-6 = LLM judges) | Layer 1: No; Layers 2-6: Yes |
| `scripts/redeck_repair.py` | Repair agent with inner edit-verify loop (uses spatial oracle via `verify_layout`) | Yes |
| `scripts/redeck_loop.py` | Outer loop: judge → repair → re-judge | Yes |

`redeck_spatial.py` is not a separate pipeline stage — it's the **same oracle** that Judge Layer 1 and `verify_layout` use, exposed as a CLI for quick checks and CI integration.

---

## 1. Judge (`redeck_judge.py`)

Evaluates HTML slides through 6 layers. Layer 1 (deterministic spatial checks via Playwright) requires no LLM; layers 2-6 are LLM-based judges that need screenshots and/or source paper.

```bash
# Layer 1 only: spatial checks (fast, no LLM)
python scripts/redeck_judge.py --dir ./slides/ --spatial-only

# All 6 layers (requires source paper for C/D/E families)
python scripts/redeck_judge.py --dir ./slides/ --paper paper.md

# JSON output
python scripts/redeck_judge.py --dir ./slides/ --paper paper.md --json -o issues.json
```

Convenience shortcut for Layer 1 only (spatial oracle CLI):
```bash
python scripts/redeck_spatial.py --dir ./slides/
python scripts/redeck_spatial.py slide.html --json
```

**Exit code:** 0 = clean, 1 = issues found.

### The 6 Evaluation Layers

| Layer | Judge | Family | What It Checks | Input | LLM |
|-------|-------|--------|----------------|-------|-----|
| 1 | **DeterministicGeomChecks** | B | overlap, OOB, empty slide, clipping, overflow, contrast, occlusion | Playwright DOM | No |
| 2 | **VisualJudge** | B | density, alignment, typography, layout quality, color semantics | Screenshots (PNG) + spatial signals from L1 | Yes |
| 3 | **NarrativeJudge** | A | logical flow, title quality, weak thesis/closing | Slide text | Yes |
| 4 | **CompletenessJudge** | C | missing key points, missing data, missing sections | Source paper | Yes |
| 5 | **CorrectnessJudge** | D | factual errors, wrong numbers, entity errors | Source paper | Yes |
| 6 | **FidelityJudge** | E | fabrication, unfaithful compression, misleading omission | Source paper | Yes |

Layer 1's spatial signals are injected as context into Layer 2 (VisualJudge), so the visual judge is aware of Playwright-detected defects and can focus on higher-level aesthetic issues.

### Layer 1: Deterministic Spatial Detection (= the spatial oracle)

This layer calls `extract_html_slide_state()` — the same spatial oracle that `verify_layout` uses inside the repair agent and that `redeck_spatial.py` exposes as a CLI. It renders HTML via Playwright, queries DOM bounding boxes, and detects spatial defects programmatically:

| Issue Type | How Detected | Rubric |
|-----------|-------------|--------|
| **Overlap** | Bounding box intersection area between elements | B03 |
| **Text overflow** | `scrollHeight > clientHeight` or `scrollWidth > clientWidth` | B04 |
| **Out-of-bounds** | Element bbox extends beyond 1280×720 canvas | B03 |
| **Clipped content** | Content hidden by parent's `overflow:hidden` | B04 |
| **Occlusion** | One element fully covers another (z-index ordering) | B03 |
| **Low contrast** | WCAG AA contrast ratio < 4.5:1 for normal text | B05 |
| **Broken image** | `<img>` src fails to load | — |

#### Spatial Detection Output (JSON)

```json
{
  "slide_id": 4,
  "n_elements": 18,
  "n_issues": 10,
  "issues": [
    {
      "type": "overlap",
      "elements": ["blk_03", "blk_07"],
      "area_sq_in": 2.145,
      "a_bbox_px": [560, 400, 600, 200],
      "b_bbox_px": [560, 380, 600, 250]
    },
    {
      "type": "overflow",
      "element": "blk_05",
      "overflow_bottom_px": 48,
      "overflow_right_px": 0
    },
    {
      "type": "clipped",
      "element": "blk_08",
      "clipped_bottom_px": 24
    },
    {
      "type": "occlusion",
      "front": "blk_10",
      "back": "blk_02"
    },
    {
      "type": "low_contrast",
      "element": "blk_06",
      "contrast_ratio": 2.31,
      "fg": "rgb(180,180,180)",
      "bg": "rgb(255,255,255)"
    }
  ]
}
```

#### Human-Readable Output

```
❌ slide_04.html: 10 issues
SLIDE 4 — 18 elements | canvas 1280×720 px

🚨 ISSUES TO FIX (10):
❌ OVERLAP: "Pipeline step 3..." ↔ "Key design decisions..."
   A: (560, 400, 600×200) px   B: (560, 380, 600×250) px
   intersection: 600×220 px
❌ TEXT OVERFLOW: "Results show that..."
   scrollHeight: 180px | clientHeight: 120px | overflow: 60px vertical
❌ CLIPPED: "The same methodology..."
   24px of content hidden by overflow:hidden

📐 LAYOUT ANCHOR (18 elements):
  div .title: (60,30) 1160×40px font:32px  "Pipeline Architecture..."
  div .content: (60,90) 560×500px font:18px "The proposed method..."
  ...

SPACE MAP (each cell ~71×72 px, # = content, . = empty):
+------------------+
|##################|
|##################|
|.################.|
|..................|  <- empty
+------------------+
Coverage: 65%
```

### Issue Families and Types (Layers 1-6)

**A — Narrative (Layer 3):**
`weak_thesis`, `missing_context`, `poor_flow`, `title_content_mismatch`, `weak_closing`, `misallocated_detail`, `placeholder_slide`, `spelling_error`, `grammar_error`, `language_inconsistency`, `non_slide_content`

**B — Visual/Layout (Layers 1-2):**
`overlap` (B03), `text_overflow` (B04), `low_contrast` (B05), `out_of_bounds`, `empty_slide`, `empty_placeholder`, `content_anomaly` — *deterministic, Layer 1*
`visual_inconsistency`, `layout_inappropriate`, `text_visual_imbalance`, `form_misfit`, `irrelevant_visual`, `density_imbalance` (B09), `missing_data_visualization`, `typography_error`, `formatting_error`, `alignment_inconsistency` (B13), `form_redundancy`, `container_contract_breach` (B15), `text_wall`, `raw_figure`, `color_semantic_mismatch` — *LLM-based, Layer 2*

**C — Completeness (Layer 4):**
`missing_section` (C01), `missing_point` (C02), `missing_evidence` (C03), `missing_entity` (C04), `missing_conclusion` (C05)

**D — Correctness (Layer 5):**
`incorrect_claim` (D01), `numeric_error` (D02), `entity_error` (D03), `chart_misinterpretation` (D04), `unsupported_causality` (D05)

**E — Fidelity (Layer 6):**
`untraceable` (E01), `fabricated` (E02), `unfaithful_compression` (E03), `misleading_omission` (E04)

### Issue Schema

Each issue returned is an `Issue` object:

```
Issue:
  issue_id: str              # unique identifier
  rubric_id: str             # e.g. "B03", "D01", "C02"
  issue_type: str            # e.g. "overlap", "fabricated"
  severity: CRITICAL|MAJOR|MINOR
  confidence: HIGH|MEDIUM|LOW
  affected_slides: list[int] # slide numbers
  evidence:
    description: str         # human-readable description with pixel values
    render_ref: str          # reference to rendered screenshot
    object_refs: list[str]   # element IDs (block_id) involved
    source_refs: list[str]   # source document references (for C/D/E)
  verdict: FAIL|WARN|PASS
  why_this_fails: str        # explanation of impact on viewer
  planned_fix: str           # suggested fix approach
  fix_detail:                # concrete fix spec (primarily for C/D issues)
    correct_content: str     # exact text from source paper
    source_ref: str          # source chunk ID
    target_location: str     # e.g. "bullet 3", "subtitle"
    action_type: str         # replace_text, add_bullet, add_data_row, remove_text, rewrite_claim
  recommended_action: KEEP|PATCH|REGEN
  status: OPEN|RESOLVED|WONT_FIX|DEFERRED
  fixability: easy_local_patch|medium|hard|requires_redesign
```

### Issue Classification

```
UNSOLVABLE (skip in repair):  poor_flow, visual_inconsistency
HIGH_VALUE (prioritize):      overlap, out_of_bounds, text_overflow,
                              container_contract_breach, fabricated,
                              incorrect_claim, numeric_error, entity_error
DETERMINISTIC (Layer 1 only): empty_slide, empty_placeholder,
                              out_of_bounds, content_anomaly
```

Cross-family dedup — when both appear on the same slide, only the higher-severity survives:
- `fabricated` vs `numeric_error` / `incorrect_claim` / `unsupported_causality`
- `density_imbalance` vs `overlap` / `text_overflow`
- `title_content_mismatch` vs `text_overflow`

### Differential Evaluation (Re-judge, Turn > 0)

On re-judge after repair, each LLM judge receives the previous issues for slides that were modified. The judge triages them:
- **RESOLVED**: issue no longer present after repair
- **PERSISTED**: issue still present, same severity
- **WORSENED**: issue got worse after repair

This enables tracking issue lifecycle across the outer loop: `OPEN → RESOLVED` or `OPEN → PERSISTED → RESOLVED`.

---

## 2. Repair Agent (`redeck_repair.py`)

Uses `AgentRepair` — an autonomous tool-calling agent. The agent receives the Issue list from the judge, plans coordinated fixes, and executes them in an edit-verify loop.

```bash
# Single file
python scripts/redeck_repair.py slide_01.html -o ./repaired/

# Directory batch with screenshots
python scripts/redeck_repair.py --dir ./slides/ -o ./repaired/ --screenshot

# Custom model
python scripts/redeck_repair.py slide.html -o ./repaired/ --model gpt-5.4
```

### Agent Tools

One tool call per LLM message (the agent calls one tool, gets the result, then decides the next tool call):

| Tool | Purpose |
|------|---------|
| `plan` | Submit repair plan: `{summary, steps: [{action, expected_outcome, verify_criterion}]}` |
| `update_plan` | Mark steps done/skipped, add new steps, revise descriptions |
| `apply_edits` | Search-and-replace on HTML/CSS: `{edits: [{search, replace}]}`, up to 10 per call |
| **`verify_layout`** | **Render via Playwright → return full spatial state** (same oracle as Judge Layer 1) |
| `rollback` | Undo last N edit batches (checkpoint stack) |
| `search_source` | Search source paper for facts/numbers (budget: 10 calls shared with lookup_table) |
| `lookup_table` | Search for tables/metrics from source paper |
| `generate_chart` | Generate matplotlib chart as `<img>` |
| `get_current_code` | View current HTML code |
| `regen_slide` | Regenerate from scratch (costs 5 tool calls, limit 2 per session). Use when ≥8 issues or repositioning failed 2+ times — prefer regen over deleting figures/charts |
| `submit_repair_summary` | Record: issues targeted, actions taken, confidence, unresolved concerns |
| `submit` | Finalize and return repaired code |

### The Edit-Verify Inner Loop (tool calls within one repair session)

```
tool call 1:  plan           → Analyze ALL issues, plan coordinated fixes
tool call 2:  apply_edits    → Make CSS/HTML changes
tool call 3:  verify_layout  → Playwright renders, returns pixel-precise spatial state
              ├─ Clean?      → update_plan (mark step done), next plan step
              ├─ Regression? → rollback → try different approach
              └─ Partial?    → apply_edits again with adjusted values (using exact px)
tool call 4+: (repeat apply_edits → verify_layout for each plan step)
   ...
tool call N-1: submit_repair_summary → Summarize what was fixed
tool call N:   submit → Return final code
```

**What `verify_layout` returns** (the agent sees this after every `apply_edits` tool call):

```
❌ TEXT OVERFLOW: ".content" — scrollHeight=180px vs clientHeight=120px, overflow=60px
❌ OVERLAP: ".title" ↔ ".subtitle" — intersection 400×20 px
✅ Previously reported clipping on ".footer" is now resolved
⚠ FONT DEGRADATION: median body font 22px → 16px
🚨 CONTENT LOSS: word count 120 → 78 (65% retained)
📐 LAYOUT ANCHOR: (every element's (x,y) position, w×h size, font-size, text preview)
SPACE MAP: ASCII grid of content vs empty areas, coverage %
Baseline delta: -3 issues (improvement vs original code)
```

The agent compares this against its plan step's `expected_outcome` and `verify_criterion`, then decides: proceed / rollback / adjust. The key insight: **every pixel value in the verify_layout output is actionable** — "overflow=60px" tells the agent exactly how much to increase the container height. The quality signals (font degradation, content loss) prevent the agent from trading spatial correctness for visual quality — if ❌ decreases but ⚠ appears, the agent should try a different strategy (restructure or regen) instead of continuing down the degradation path.

### Budget and Safeguards

```
MAX_TOOL_CALLS_PER_ISSUE: 8    # tool call budget per issue
MAX_TOOL_CALLS_CAP:      30    # hard cap per repair session
MAX_NO_PROGRESS:          4    # abort if N consecutive tool calls without code change
MAX_SEARCH_CALLS:        10    # search_source + lookup_table budget
```

**Spatial regression gate** (two levels):

1. **Agent-internal (per tool call)**: `verify_layout` after each `apply_edits` — agent sees regressions in real time and rolls back
2. **Outer loop (per turn)**: after AgentRepair returns, the loop checks `overlap_pairs + oob_blocks` — if count increased, the entire repair is rejected and the original HTML is kept

### Key Repair Principles

1. **First do no harm.** A repair creating new issues is a net negative.
2. **Scale edits to the problem.** 20px adjustment on 1280×720 is invisible.
3. **Spatial compensation.** Shrinking content → must expand remaining elements to maintain density.
4. **Content integrity.** Never introduce claims not backed by source evidence.
5. **Overflow = restructure, not just condense.** Prefer removing an entire section over shrinking font to 12px.
6. **Persistent clipping = aggressive action.** If clipping persisted from prior turn, remove entire sections.
7. **Content-only fixes must not touch layout.** D/E/C fixes must not change positions/dimensions.
8. **Zero tolerance for new content errors.** Use `search_source` before adding any new claims.

---

## 3. Iterative Loop (`redeck_loop.py`)

Composes judge + repair into the outer loop: **Judge → Repair → Re-judge → Repair → ...** until convergence.

```bash
# Spatial-only loop (Layer 1 judge + repair, no LLM judges)
python scripts/redeck_loop.py --dir ./slides/ --max-turns 3

# With output directory
python scripts/redeck_loop.py --dir ./slides/ -o ./repaired/ --max-turns 3

# JSON summary
python scripts/redeck_loop.py --dir ./slides/ -o ./repaired/ --json
```

### Loop Behavior

```
Turn 0: Judge (spatial) → count issues per slide
Turn 1: Repair slides with issues → Re-judge → count remaining
Turn 2: Repair remaining → Re-judge → count remaining
...
Stop when: total issues = 0 OR turn = max_turns
```

Each turn applies the **outer spatial regression gate** — repairs that increase `overlap_pairs + oob_blocks` are rejected. Meanwhile, within each repair session, the **inner edit-verify loop** catches and rolls back regressions in real time via `verify_layout`.

### Output

```json
{
  "history": [
    {"turn": 0, "total_issues": 42, "per_slide": {"1": 0, "2": 7, ...}},
    {"turn": 1, "total_issues": 5, "per_slide": {"2": 0, "4": 3, ...}},
    {"turn": 2, "total_issues": 0, "per_slide": {"4": 0, ...}}
  ],
  "initial_issues": 42,
  "final_issues": 0,
  "turns_used": 2
}
```

Repaired HTML files and `loop_history.json` saved to the output directory.

---

## Underlying Data Model

### ContentBlock (per-element spatial data from Playwright)

```
ContentBlock:
  block_id: str           # "blk_01", "blk_02", ...
  var_name: str           # HTML tag name
  shape_type: str         # textbox, picture, table, chart, title
  css_selector: str       # "#id" or ".class" — for locating in code
  bbox_px: (x, y, w, h)  # CSS pixel coordinates on 1280×720 canvas
  font_size_px: float     # rendered font size in px
  text_lines: list[str]   # visible text content
  # Overflow (from Playwright DOM queries)
  is_overflowing: bool
  overflow_bottom_px: int # scrollHeight - clientHeight (vertical overflow)
  overflow_right_px: int  # scrollWidth - clientWidth (horizontal overflow)
  scroll_h_px: int        # full content height
  client_h_px: int        # visible content height
  # Clipping (parent overflow:hidden detection)
  is_clipped: bool
  clipped_bottom_px: int  # pixels of content hidden
  # Contrast (WCAG)
  contrast_ratio: float   # 0 = not computed (e.g. image element)
  fg_color: str           # e.g. "rgb(255,255,255)"
  bg_color: str           # e.g. "rgb(0,51,102)"
  # Image status
  img_broken: bool
  img_src: str
  # Z-index (for occlusion analysis)
  z_index: int
```

### SlideState (per-slide spatial summary)

```
SlideState:
  slide_id: int
  blocks: list[ContentBlock]
  total_area: float                    # total canvas area
  used_area: float                     # area covered by elements
  overlap_pairs: list[(a_id, b_id, area_sq_in)]  # intersecting element pairs
  overflow_blocks: list[block_id]      # elements with scrollHeight > clientHeight
  oob_blocks: list[block_id]           # elements extending beyond 1280×720
  clipped_blocks: list[block_id]       # elements clipped by parent overflow:hidden
  low_contrast_blocks: list[block_id]  # WCAG AA violation
  occlusion_pairs: list[(front_id, back_id)]  # front fully covers back
  broken_images: list[block_id]        # <img> failed to load
```

### Spatial Thresholds

```
Canvas:               1280×720 CSS pixels, device scale factor 2
OVERLAP_MIN_PCT:      0.10     # <10% of smaller element's area → ignored
OVERLAP_MAJOR_PCT:    0.25     # ≥25% → MAJOR severity
OOB_MIN_INCHES:       0.1      # <0.1" beyond canvas edge → ignored
OVERLAP_TRIVIAL_AREA: 0.5      # <0.5 sq in intersection → tolerated
```

---

## Manual Fix Strategies

If you prefer to fix issues yourself instead of using the repair agent:

### Overlap (B03)
Move the lower element down by at least the intersection height + 10px margin:
```css
/* Before: elements overlap by 220px vertically */
.element-b { top: 380px; }
/* After: clear of element A which ends at y=400+200=600px */
.element-b { top: 610px; }
```

### Text Overflow / Clipped (B04)
Act in one coordinated step — do not iterate:
1. Reduce `font-size` (minimum 14px body, 26px title)
2. Increase container height
3. Tighten `line-height` or `padding`
4. If still overflowing: **restructure** — remove a section entirely rather than shrinking everything
5. **Never** remove `overflow:hidden` from body — that breaks the slide boundary

### Out of Bounds
Reduce element size or reposition to fit within 1280×720px.

### Low Contrast (B05)
Ensure WCAG AA ratio ≥ 4.5:1 for normal text, ≥ 3:1 for large text. Never use accent colors (orange, light green, yellow) as text color on white backgrounds. Use `font-weight: 700` or dark colors for emphasis.

### Key CSS Rule
Elements with `bottom: -Npx` or `top: calc(100% + Npx)` inside a container with `overflow:hidden` **will be clipped**. Use absolute positioning relative to `.slide` instead.

---

## Requirements

- Python 3.11+
- Playwright: `pip install playwright && playwright install chromium`
- For repair/judge layers 2-6: LLM API endpoint (configured via `app/llm_client.py`)
- Conda env: `redeck` (see `CLAUDE.md`)

---

## Validated Performance

Tested across 3 cases (36 slides, 250 spatial issues):

| Method | Issues Fixed | Fix Rate |
|--------|-------------|----------|
| Claude self-repair (screenshot only, no spatial analysis) | 93/250 | 37% |
| **ReDeck (verify_layout feedback loop + AgentRepair)** | **233/250** | **93%** |

The 56pp gap comes from the edit-verify inner loop: when the agent can call `verify_layout` after every CSS change and see exactly what happened in pixels, it stops guessing and starts converging. Without it, the LLM applies edits blindly from a single screenshot — and 63% of the time, the fix either doesn't work or creates new problems it can't see.
