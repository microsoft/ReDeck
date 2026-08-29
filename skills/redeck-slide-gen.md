---
name: redeck-slide-gen
description: Generate and repair HTML presentation slides using ReDeck's style schema + spatial verify loop. Use when creating, editing, or fixing HTML slides (1280×720px viewport).
---

# ReDeck Slide Generation & Spatial Repair

**Use when:** generating, editing, or reviewing HTML presentation slides.

This skill combines three core mechanisms:
1. **Style Schema** — infographic-quality design recipes with concrete code templates
2. **Spatial Oracle** — step-level render-verify-fix loop with atomic edits and instant feedback
3. **VLM Visual Review** — aesthetic self-audit for layout balance, density, and form fit

---

## Part 1: Style Schema — BOLD, SPACIOUS, VISUAL-FIRST

### Design Philosophy

Every slide should feel like an **infographic poster**, not a document page. Follow these principles:

1. **Scale up, not out.** Fewer elements, each one LARGE. One hero visual dominates the body zone.
2. **Color saturation ≥ 35%.** At least 35% of the body zone area should use theme color fills (colored cards, table headers, sidebar panels, chart fills). A slide that is 85% white with tiny colored accents looks washed out.
3. **Visual hierarchy is dramatic.** Hero numbers are 64-78px. Section labels are 13px uppercase. The size contrast between primary and secondary elements should be at least 3:1.
4. **Generous spacing.** Cards use 22-28px padding. Table rows are 44-52px tall. Flow boxes are 150-180px wide.
5. **Bottom takeaway bar is MANDATORY.** Every slide (except title) must end with a full-width colored bar (64-72px tall) containing a one-sentence takeaway in bold white text.
6. **DATA VISUALIZATION OVER TEXT.** When presenting numeric data — ALWAYS prefer SVG chart/diagram over text bullets. Bar charts for comparisons, donut charts for percentages, flow diagrams for pipelines.

### Technical Foundation

```
width: 1280px; height: 720px; overflow: hidden;
font-family: 'Liberation Sans', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
```

Single `<html>`, all CSS in `<style>` or inline. No external resources except provided figure paths.

---

### Slide Structure — 3 Vertical Zones

Every slide has 3 zones (adapt proportions to content):

1. **Header band** (65-84px): full-width colored background, white title text (28-32px bold)
2. **Body zone** (~96px to ~630px): ONE dominant visual element; everything else supports it
3. **Bottom bar** (64-72px): full-width ACCENT/PRIMARY_DARK background, one-sentence takeaway in white bold text (15-17px)

### Header Style Rotation — VARY across slides

| Style | CSS | Best for |
|-------|-----|----------|
| **Dark gradient** | `background: linear-gradient(135deg, PRIMARY_DARK, PRIMARY_MID)` + white text | Title, method, conclusion |
| **Light/white** | `background: #ffffff; border-bottom: 4px solid ACCENT` + dark text | Data-heavy results, tables |
| **Accent-dominant** | `background: ACCENT` + white text | Key findings, "big reveal" |
| **Muted tint** | `background: LIGHT_BG` + dark text with left accent bar | Context, background |

**Rule:** In a 10+ slide deck, never use the same header style on 3+ consecutive slides.

### Body Layout Variants

- **Asymmetric split (default, ~50%)**: 62-68% left (dominant visual) + 32-38% right (sidebar cards). Max 2 sidebar cards.
- **Full-width visual (~25%)**: Single chart/figure/table spanning full width, compact annotation row below.
- **Three-column (~15%)**: Three equal-width panels for comparing 3 items/stages.
- **Inverted split (~10%)**: 32-38% left (text sidebar) + 62-68% right (dominant visual).

---

## Visual Technique Catalog (CONCRETE CODE TEMPLATES)

**Pick 2-3 techniques per slide.** These are copy-paste ready — adapt colors to your palette.

### Technique Selection Guide

- Method/pipeline → SVG Flow Diagram (#6)
- Results with numbers → SVG Bar Chart (#7) or Data Table (#3)
- Results with percentages → Donut Chart Row (#5)
- Key findings → Hero Number Card (#1)
- Comparisons → Comparison Matrix (#4)

### 1. Hero Number Card

```html
<div style="background: PRIMARY_MID; color: #fff; border-radius: 10px; padding: 26px 28px;">
  <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 10px;">
    <div style="width: 48px; height: 48px; border-radius: 50%; background: rgba(255,255,255,0.18);
                display: flex; align-items: center; justify-content: center;">
      <svg width="26" height="26" viewBox="0 0 24 24"><path d="M..." fill="#fff"/></svg>
    </div>
  </div>
  <div style="font-size: 68px; font-weight: 700; line-height: 0.95;">71.93</div>
  <div style="font-size: 16px; margin-top: 12px; font-weight: 600; opacity: 0.9;">
    Best score — Macro-F1
  </div>
</div>
```

Hero number MUST be 64-78px. Card padding at least 24px. Use on results, conclusions, motivation.

### 2. Sidebar Card Stack (MAX 2 cards)

```html
<!-- Dark card with icon -->
<div style="background: PRIMARY_MID; color: #fff; border-radius: 10px; padding: 20px 22px; margin-bottom: 14px;">
  <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 10px;">
    <div style="width: 44px; height: 44px; border-radius: 50%; background: rgba(255,255,255,0.15);
                display: flex; align-items: center; justify-content: center;">
      <svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="5" fill="#fff"/></svg>
    </div>
    <div style="font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">SECTION TITLE</div>
  </div>
  <ul style="margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.55;">
    <li>Key point one</li>
    <li>Key point two</li>
  </ul>
</div>
<!-- Light card -->
<div style="background: LIGHT_BG; border-radius: 10px; padding: 18px 20px;">
  <div style="font-size: 14px; font-weight: 700; color: PRIMARY_DARK; text-transform: uppercase;
              letter-spacing: 0.8px; margin-bottom: 10px;">SECTION TITLE</div>
  <ul style="margin: 0; padding-left: 18px; font-size: 14px; line-height: 1.55; color: #2d2d2d;">
    <li>Key point one</li>
    <li>Key point two</li>
  </ul>
</div>
```

Max 2 bullets per card. Every dark card MUST include an icon circle. Alternate dark/light for rhythm.

### 3. Data Table with Inline Bars

```html
<table style="width: 100%; border-collapse: collapse; font-size: 15px;">
  <thead>
    <tr style="background: PRIMARY_DARK; color: #fff;">
      <th style="padding: 14px 16px; text-align: left;">Method</th>
      <th style="padding: 14px 16px; text-align: center;">Score</th>
    </tr>
  </thead>
  <tbody>
    <tr style="background: #f5f5f5;">
      <td style="padding: 12px 16px;">Baseline</td>
      <td style="padding: 12px 16px; text-align: center;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div style="height: 15px; width: 55%; background: #c8c8c8; border-radius: 3px;"></div>
          <span style="font-weight: 500;">66.5</span>
        </div>
      </td>
    </tr>
    <!-- Best row highlighted -->
    <tr style="background: ACCENT; color: #fff;">
      <td style="padding: 12px 16px; font-weight: 700;">Ours</td>
      <td style="padding: 12px 16px; text-align: center; font-weight: 700;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div style="height: 15px; width: 82%; background: rgba(255,255,255,0.4); border-radius: 3px;"></div>
          <span>69.7</span>
        </div>
      </td>
    </tr>
  </tbody>
</table>
```

Zebra-stripe rows. Highlight best row with ACCENT + white text. Max 6-7 rows, 4-5 columns. Row height 44-52px.

### 4. Comparison Matrix

```html
<table style="width: 100%; border-collapse: separate; border-spacing: 0; border-radius: 10px; overflow: hidden;">
  <tr>
    <th style="background: PRIMARY_DARK; color: #fff; padding: 18px; width: 34%;">PRIOR WORK</th>
    <th style="background: PRIMARY_MID; color: #fff; padding: 18px; width: 33%;">THIS PAPER</th>
    <th style="background: ACCENT; color: #fff; padding: 18px; width: 33%;">IMPACT</th>
  </tr>
  <tr>
    <td style="background: #e8eaee; padding: 18px; vertical-align: top;">Prior approach description</td>
    <td style="background: PRIMARY_MID; color: #fff; padding: 18px; font-weight: 600;">New approach</td>
    <td style="background: ACCENT; color: #fff; padding: 18px;">+15% improvement</td>
  </tr>
</table>
```

3-4 rows max. Cell padding 16-18px.

### 5. Donut/Ring Chart Row

```html
<div style="display: flex; justify-content: space-around; align-items: flex-start; padding: 10px 0;">
  <div style="text-align: center; width: 240px;">
    <div style="position: relative; width: 180px; height: 180px; margin: 0 auto;">
      <svg width="180" height="180" viewBox="0 0 180 180">
        <circle cx="90" cy="90" r="70" fill="none" stroke="#e0e0e0" stroke-width="18"/>
        <circle cx="90" cy="90" r="70" fill="none" stroke="ACCENT" stroke-width="18"
                stroke-dasharray="316 440" transform="rotate(-90 90 90)" stroke-linecap="round"/>
      </svg>
      <div style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;">
        <span style="font-size: 44px; font-weight: 700; color: PRIMARY_DARK;">72%</span>
      </div>
    </div>
    <div style="font-size: 15px; font-weight: 700; margin-top: 10px;">LABEL</div>
    <div style="font-size: 13px; color: #666; margin-top: 4px;">Description</div>
  </div>
  <!-- repeat for 2nd and 3rd donut -->
</div>
```

Each donut 170-190px diameter. Ring stroke-width 16-20. Use for conclusions with 2-3 percentage outcomes.

### 6. SVG Flow Diagram

```html
<svg width="700" height="300" viewBox="0 0 700 300">
  <defs>
    <marker id="arr" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <path d="M0,0 L8,3 L0,6" fill="none" stroke="PRIMARY_MID" stroke-width="1.5"/>
    </marker>
  </defs>
  <!-- Stage box: 150×120 MINIMUM -->
  <rect x="10" y="80" width="150" height="120" rx="10" fill="PRIMARY_DARK"/>
  <foreignObject x="10" y="80" width="150" height="120">
    <div xmlns="http://www.w3.org/1999/xhtml" style="color:#fff; text-align:center; padding:14px;">
      <div style="font-weight:700; font-size:16px; margin-bottom:8px;">Stage 1</div>
      <div style="font-size:12px; opacity:0.85;">description</div>
    </div>
  </foreignObject>
  <!-- Arrow -->
  <line x1="160" y1="140" x2="200" y2="140" stroke="PRIMARY_MID" stroke-width="2.5" marker-end="url(#arr)"/>
</svg>
```

3-5 stages. Boxes 150-180px wide, 110-140px tall. Alternate PRIMARY_DARK and PRIMARY_MID fills. Include icon circles inside boxes.

### 7. SVG Grouped Bar Chart

```html
<svg width="700" height="420" viewBox="0 0 700 420">
  <!-- Grid lines -->
  <g stroke="#e6e6ea" stroke-width="1">
    <line x1="140" y1="0" x2="140" y2="400"/>
    <line x1="280" y1="0" x2="280" y2="400"/>
    <line x1="420" y1="0" x2="420" y2="400"/>
    <line x1="560" y1="0" x2="560" y2="400"/>
  </g>
  <!-- Bars -->
  <rect x="140" y="12" width="380" height="15" rx="2" fill="PRIMARY_DARK"/>
  <rect x="140" y="29" width="340" height="15" rx="2" fill="PRIMARY_MID"/>
  <!-- Value labels -->
  <text x="528" y="25" font-size="13" font-weight="600" fill="#2d2d2d">95.9</text>
  <!-- Y-axis labels -->
  <text x="135" y="34" text-anchor="end" font-size="13" fill="#3a3a3a">Model A</text>
</svg>
```

Horizontal bars (easier to label). Include color legend. Light gray grid lines. Value labels right of bars.

---

## Role-Specific Recipes

### Title Slide
- **NO standard header band.** Use: dark banner (PRIMARY_DARK, 150-200px tall) with paper title (38-44px bold white)
- Below banner: left = 3-4 large pipeline stage boxes (flex:1 each, ~170px wide, 150-180px tall, bold color fills, white text, icon circles) connected by → arrows; right = single author/affiliation card
- Each stage box: colored fill + numbered step circle (48px) + bold name (16-18px) + short description (12px)
- **NEVER substitute pipeline with metadata cards or hero numbers**

### Method / Architecture
- **Header:** Dark gradient
- **Main visual:** Paper figure via `<img>` (preferred) OR SVG Flow Diagram (#6) with LARGE boxes
- **Sidebar:** 1 hero number + 1 supporting card (max 2 bullets)
- Flow boxes must be 140-170px wide with bold color fills — not tiny gray boxes

### Results / Evaluation
- **Header:** Light/white with ACCENT border, OR accent-dominant for "big reveal"
- **Main visual:** Data Table (#3) or Grouped Bar Chart (#7)
- **Sidebar:** Hero Number Card (#1) at top (64-78px number) + at most 1 wins card
- The hero number is the most prominent element. Let data speak.

### Motivation / Problem
- **Header:** Muted tint (LIGHT_BG + left ACCENT bar)
- **Main visual:** Flow Diagram (#6) showing cause→effect, or paper figure
- **Sidebar:** Dark card with core claim in large text (18-22px bold white)
- Bottom bar strongly recommended — state why this matters

### Conclusion / Takeaway
- **Header:** Accent-dominant (climax of deck)
- **Main visual:** 2-3 large hero number cards (64-78px each) in horizontal flex row, each with DIFFERENT colored fill (PRIMARY_DARK, PRIMARY_MID, ACCENT)
- Below hero row: at most 1 single text container (can have internal flex columns)
- Bottom bar required — capstone sentence

---

## Color Palettes (USE THESE — do not invent colors)

Pick ONE palette per deck. These are designed with complementary color theory — primary + accent are always harmonious.

| Theme | PRIMARY_DARK | PRIMARY_MID | ACCENT | LIGHT_BG | Best for |
|-------|-------------|-------------|--------|----------|----------|
| **Deep Navy** | #122040 | #264178 | #d24834 | #eaf0fa | Most papers (safe default) |
| **Ocean Teal** | #0a343e | #006978 | #cc5500 | #e4f4f6 | Vision, biology, sustainability |
| **Sage Slate** | #203630 | #386458 | #942a62 | #eaf4f0 | NLP, clinical, social science |
| **Royal Purple** | #301254 | #522d94 | #be8c00 | #f0eafa | Theory, math, creative AI |
| **Espresso** | #341e16 | #6e4430 | #008080 | #f2ece6 | Systems, HCI, enterprise |
| **Crimson Modern** | #50121c | #942030 | #1e5a96 | #f8eaee | Security, fintech, medical |

**Rules:**
- Never use raw Material Design colors (#1b5e20, #ff6f00, etc.) — they look garish on slides
- PRIMARY_DARK must pass WCAG AA on white (≥ 4.5:1)
- ACCENT should be complementary or split-complementary to PRIMARY hue
- If the user provides a palette, use it. Otherwise pick from this table.

---

## Paper Figures — USE `<img>`, DO NOT REDRAW

When evidence includes a figure:
- Place as `<img>` with `width:100%; max-height:480px; object-fit:contain;`
- Do NOT recreate in SVG — it will look worse
- The figure IS the dominant visual

When NO figure available:
- Create SVG diagram (flow, bar chart, donut) — a themed SVG is better than blank space
- SVG should fill 60-70% of body zone

---

## Typography Reference

| Element | Size | Weight |
|---------|------|--------|
| Hero numbers | 64-78px | 700 |
| Paper title (title slide) | 38-44px | 700 |
| Slide title (header band) | 28-36px | 700 |
| Section heading | 16-20px | 700 |
| Body text | 14-17px | 400 |
| Card label | 13-14px | 700, uppercase, letter-spacing: 0.8-1.2px |
| Caption | 12-13px | 400 |

Never below 12px. Hero numbers MUST be 64px minimum.

---

## Anti-Patterns — NEVER Do These

- ❌ Redrawing paper figures in SVG → use `<img>`
- ❌ 3+ columns of bullet lists → asymmetric split with ONE visual
- ❌ 5+ content sections per slide → max 3 visual groups
- ❌ Full sentences in bullets → max 6 words each
- ❌ Cards-only slides without charts → use SVG for numeric data
- ❌ Gray/muted flow boxes → bold PRIMARY_DARK or PRIMARY_MID fills
- ❌ Hero numbers < 60px → MUST be 64-78px
- ❌ Mostly-white slides (85%+ white) → at least 35% body uses color fills
- ❌ Cramped cards (8-10px padding) → cards need 18-28px padding
- ❌ Missing bottom takeaway bar → MANDATORY on every non-title slide
- ❌ 3+ sidebar cards → MAX 2 per slide
- ❌ 3+ bullets per card → MAX 2 bullets
- ❌ Dark cards without icon circles → every dark card needs a 44-48px icon circle
- ❌ Multiple hero cards with same fill → use DIFFERENT colors per card
- ❌ Title slide without pipeline preview → must show visual method pipeline
- ❌ Same header style 3+ slides in a row → rotate styles

---

## Content Guidelines

- **Total visible words per slide: ≤120.** Tables/labels count.
- **Max 3 visual groups** in body (e.g. table + hero card + info card = 3)
- Bullets: ≤ 6 words each, max 3 per card
- Tables: max 5-6 data rows, 4-5 columns
- Evidence text is raw material — extract key phrases, don't copy sentences
- Every number and claim MUST come from provided evidence (never fabricate)

---

## Part 2: Spatial Oracle (Render-Verify-Fix Loop)

### The Core Mechanism

After generating or editing slide HTML, **always verify spatial correctness**:

```
generate/edit HTML
    ↓
render with Playwright (1280×720 viewport)
    ↓
extract DOM bounding boxes for every element
    ↓
run deterministic spatial checks:
  - overlap: two elements' bboxes intersect > threshold
  - text_overflow: element.scrollHeight > element.clientHeight
  - out_of_bounds: element extends past 1280×720 canvas
  - clipping: ancestor with overflow:hidden cuts content
    ↓
if issues found → enter step-level repair loop
```

### The Step-Level Verify Loop (Core Innovation)

**Do NOT batch all fixes then check once. Verify after EVERY SINGLE EDIT:**

```
WRONG (turn-level):
  plan 5 fixes → apply all 5 → render → check
  Problem: fix #3 broke something, but #4 #5 built on it.

RIGHT (step-level):
  plan → edit #1 → verify → ok
       → edit #2 → verify → REGRESSION! → rollback #2
       → edit #2b (different approach) → verify → ok
       → edit #3 → verify → ok
       → submit
```

**Protocol:**
1. **Plan** — list issues, prioritize by severity (plan is MUTABLE)
2. **Edit ONE thing** — single atomic CSS/HTML change
3. **Verify immediately** — render and spatial check
4. **Read feedback** — what resolved, what regressed
5. **Decide**: clean → next issue; regression → rollback; plan wrong → update plan
6. **Repeat** until clean or max 10 steps

**Why step-level beats turn-level:**

| | Turn-level | Step-level (ReDeck) |
|---|---|---|
| Feedback delay | After ALL edits | After EACH edit |
| Error attribution | Can't isolate cause | Know exactly which edit |
| Rollback | Everything or nothing | Just the bad edit |
| Fix rate | ~37% | ~93% |

### Regression Gates (after EVERY step)

- New issue count ≤ old count (no net regressions)
- No text content deleted (text-freeze)
- No visual elements removed (element preservation)
- Contrast ≥ 4.5:1 for all text

If any gate fails → **immediately revert**, try different strategy.

---

## Part 3: VLM Visual Review

After rendering to PNG, evaluate:

1. **First impression (2s)**: Infographic poster or web page?
2. **Color coverage**: Is ≥35% of body zone using color fills?
3. **Visual dominance**: What does eye land on first? Is it the key information?
4. **Layout balance**: Any large accidental empty regions?
5. **Form fit**: Would a different viz type work better?

If ANY problem → fix → re-render → re-review.

**NEVER rationalize empty space.** If a card/container has > 30% unused internal space (content clusters in one area, rest is just background color), it IS a problem — not "generous spacing" or "intentional breathing room." Fix by: making the content elements larger (bigger font, more padding between items, add sub-content), or shrinking the container. A 400px tall card with 150px of content centered inside it is WRONG — either make the card shorter or make the content fill 70%+ of the card height.

---

## Workflow Summary

```
1. GENERATE  — apply recipes from Visual Technique Catalog
2. RENDER    — Playwright at 1280×720
3. CHECK     — spatial oracle detects hard defects
4. FIX       — step-level repair (max 10 atomic edits)
5. REVIEW    — VLM self-audit: MUST write explicit critique before proceeding
6. REFINE    — if aesthetic problems → adjust → re-render
7. RE-CHECK  — spatial check again (layout changes may introduce new issues)
8. DONE      — spatial clean + VLM passes
```

### VLM Review Protocol (MANDATORY — do not skip)

After rendering each slide to PNG, **read the screenshot** and **write answers to ALL of these before proceeding:**

1. What % of the 720px height is actual content vs background/empty?
2. Is there any empty block > 100px between content elements? Where?
3. Do cards/containers have > 30% internal empty space? (content clustered, rest blank)
4. Is color coverage ≥ 35% of the body zone?
5. Would this look good next to a professionally designed conference slide?

**If ANY answer reveals a problem → you MUST fix before moving to the next slide.**
**"It's fine" / "intentional spacing" / "looks good enough" are NOT acceptable reasons to skip fixing. When in doubt, fix it.**
