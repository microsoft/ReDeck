# HTML Slide Generation

## Task
Generate a 1280×720px presentation slide as self-contained HTML. Infographic quality — layered, dense, visually rich. Not a web page or wireframe.

## Viewport
```
width: 1280px; height: 720px; overflow: hidden;
font-family: 'Liberation Sans', 'Segoe UI', Arial, sans-serif;
```
Single HTML, inline CSS, no external resources except provided figures.
Content beyond 720px gets clipped — repair system fixes it later.

## Rules
1. **MAX density**: ALL evidence data on slide. 10-20 row tables, ALL metrics/numbers. Aim for 800px+ of content.
2. **40-70 DOM elements**: Eyebrows, section titles, KPI panels, accent bars, annotations, badges, footnotes. Not just a title + table.
3. **Color fill ≥ 40%**: Colored panels, tinted backgrounds, chart fills. Not mostly white.
4. **No rounded cards**: No `border-radius` on containers, no `box-shadow`.
5. **Overflow is OK**: Don't hold back. Repair compresses later.
6. **Follow MANDATORY LAYOUT** from user prompt — NEVER default to header+body two-column.

## Reference Patterns (real CSS from high-quality slides — adapt freely)

### Pattern A: KPI Dashboard
```css
.eyebrow { font-size:14px; font-weight:700; letter-spacing:1.8px; text-transform:uppercase; color:var(--primary); }
.hero-number { font-size:88px; font-weight:800; line-height:.9; color:var(--accent); letter-spacing:-2px; }
.metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }
.kpi { padding:14px; background:linear-gradient(180deg, rgba(var(--primary-rgb),.10), transparent 50%); }
.kpi-value { font-size:44px; font-weight:900; line-height:.9; }
.kpi-label { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin-top:6px; }
.kpi-delta { font-size:11px; font-weight:700; } /* ▲ +5.2% green or ▼ -3.1% red */
```

### Pattern B: Dense Table + Annotation
```css
table { width:100%; border-collapse:collapse; font-size:11px; }
thead tr { background:var(--primary); color:#fff; }
th, td { padding:7px 12px; }
tbody tr:nth-child(even) { background:rgba(0,0,0,.03); }
.best-row { font-weight:700; border-left:4px solid var(--accent); }
.table-caption { font-size:11px; color:var(--muted); margin-top:6px; }
.floating-note { position:absolute; font-size:11px; color:var(--muted); border-left:3px solid var(--accent); padding-left:10px; max-width:260px; }
.badge { display:inline-block; padding:2px 7px; font-size:9px; font-weight:700; text-transform:uppercase; background:var(--accent); color:#fff; }
```

### Pattern C: Timeline / Process
```css
.timeline { display:flex; position:relative; padding:0 20px; }
.timeline::before { content:''; position:absolute; top:18px; left:40px; right:40px; height:3px; background:var(--primary); }
.node { flex:1; text-align:center; z-index:1; }
.node-dot { width:36px; height:36px; background:var(--primary); color:#fff; font-weight:800; font-size:14px; display:flex; align-items:center; justify-content:center; margin:0 auto 8px; }
.node-title { font-size:12px; font-weight:700; }
.node-desc { font-size:10px; color:var(--muted); margin-top:3px; line-height:1.3; }
.phase-tag { display:inline-block; padding:3px 10px; font-size:10px; font-weight:700; background:rgba(var(--primary-rgb),.12); color:var(--primary); }
```

### Pattern D: Section Structure
```css
.section-head { display:flex; justify-content:space-between; align-items:flex-end; border-bottom:2px solid rgba(0,0,0,.10); padding-bottom:8px; margin-bottom:10px; }
.section-title { font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
.left-accent { border-left:4px solid var(--accent); padding-left:12px; }
.insight { font-size:13px; line-height:1.4; color:var(--text); padding:10px 14px; background:rgba(var(--primary-rgb),.06); }
.footer { position:absolute; left:36px; right:36px; bottom:14px; display:flex; justify-content:space-between; font-size:11px; color:var(--muted); border-top:1px solid rgba(0,0,0,.06); padding-top:6px; }
```

### Pattern E: Charts
```svg
<!-- Horizontal bar chart -->
<svg width="400" height="140" viewBox="0 0 400 140">
  <rect x="90" y="6" width="260" height="20" fill="var(--primary)" opacity=".85"/>
  <rect x="90" y="32" width="195" height="20" fill="var(--secondary)" opacity=".85"/>
  <rect x="90" y="58" width="150" height="20" fill="var(--accent)" opacity=".7"/>
  <text x="85" y="20" text-anchor="end" fill="var(--text)" font-size="11">Model A</text>
  <text x="355" y="20" fill="var(--text)" font-size="10" font-weight="700">94.2%</text>
</svg>
```
```svg
<!-- Donut -->
<svg width="100" height="100" viewBox="0 0 100 100">
  <circle cx="50" cy="50" r="36" fill="none" stroke="var(--muted)" stroke-width="12" opacity=".2"/>
  <circle cx="50" cy="50" r="36" fill="none" stroke="var(--primary)" stroke-width="12"
    stroke-dasharray="226" stroke-dashoffset="57" transform="rotate(-90 50 50)"/>
  <text x="50" y="48" text-anchor="middle" fill="var(--text)" font-size="20" font-weight="800">75%</text>
  <text x="50" y="62" text-anchor="middle" fill="var(--muted)" font-size="9">Accuracy</text>
</svg>
```

## Mix & Match
Combine patterns freely. A good data slide might use: **eyebrow + hero-number + KPI grid + dense table + floating-note + badge + footer**. A method slide: **section-head + timeline + insight panels + footer**. Each slide should feel uniquely composed.

## Color & Figures
- Copy `:root` from user prompt. Use only `var(--xxx)`.
- Assigned figure: use ONCE. No reuse across slides.

## Output
Return ONLY complete HTML starting with `<!doctype html>`.
