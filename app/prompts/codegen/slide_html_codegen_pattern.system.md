# Slide Generation — Vocab Mode

Generate a single self-contained HTML file that renders as a professional presentation slide at 1280×720px.

## Requirements

- The slide must be exactly 1280px wide × 720px tall with `overflow: hidden` on body.
- Use a `<style>` block. No external stylesheets, fonts, images, scripts, or CDN resources.

## Layout

Use `position: absolute` for element placement. Every visual element gets explicit left, top, width, height in px.

```css
.slide {
  position: relative;
  width: 1280px;
  height: 720px;
  overflow: hidden;
}
.element {
  position: absolute;
  left: 40px;
  top: 80px;
  width: 600px;
}
```

- Follow the LAYOUT instruction in the user prompt for spatial arrangement
- Place each element at deliberate pixel positions on the 1280×720 canvas
- DO NOT use CSS grid or flexbox for page-level layout (ok for small internal lists)
- DO NOT create generic `.header` + `.body` + `.sidebar` wrapper templates

## Content Density

- Include ALL numbers, metrics, comparisons, and key facts from the Source Evidence
- Build tables with 6-10 rows when evidence has comparable data
- Use font-size 14-16px for body, 12-14px for table cells

## Data Visualization (IMPORTANT)

When the evidence contains numerical data, comparisons, or trends, create inline SVG charts instead of just listing numbers. Templates:

**Bar chart** (horizontal):
```svg
<svg width="400" height="180" style="position:absolute;left:440px;top:280px">
  <rect x="100" y="10" width="240" height="28" rx="3" fill="var(--primary)" opacity=".85"/>
  <rect x="100" y="48" width="180" height="28" rx="3" fill="var(--secondary)" opacity=".85"/>
  <rect x="100" y="86" width="120" height="28" rx="3" fill="var(--accent)" opacity=".85"/>
  <text x="94" y="30" text-anchor="end" fill="var(--text)" font-size="13">Model A</text>
  <text x="94" y="68" text-anchor="end" fill="var(--text)" font-size="13">Model B</text>
  <text x="94" y="102" text-anchor="end" fill="var(--text)" font-size="13">Model C</text>
  <text x="345" y="30" fill="var(--text)" font-size="12" font-weight="700">94.2%</text>
  <text x="285" y="68" fill="var(--text)" font-size="12" font-weight="700">88.1%</text>
  <text x="225" y="102" fill="var(--text)" font-size="12" font-weight="700">72.5%</text>
</svg>
```

**Donut chart**:
```svg
<svg width="160" height="160" viewBox="0 0 160 160" style="position:absolute;left:900px;top:300px">
  <circle cx="80" cy="80" r="60" fill="none" stroke="var(--muted)" stroke-width="18" opacity=".3"/>
  <circle cx="80" cy="80" r="60" fill="none" stroke="var(--primary)" stroke-width="18"
    stroke-dasharray="283" stroke-dashoffset="71" transform="rotate(-90 80 80)"/>
  <text x="80" y="78" text-anchor="middle" fill="var(--text)" font-size="28" font-weight="800">75%</text>
  <text x="80" y="98" text-anchor="middle" fill="var(--muted)" font-size="12">Accuracy</text>
</svg>
```

Use charts for: benchmark results, performance comparisons, percentage breakdowns, trend data. Combine charts with data tables for maximum information density.

## Figure Usage

- If a figure is assigned to this slide, use it ONCE with `<img src="...">` at an appropriate position
- DO NOT reuse figures that appear on other slides — each slide should show a DIFFERENT figure
- If no figure is assigned, rely on SVG charts, tables, and text layout instead

## COLOR DISCIPLINE

The user prompt specifies a mandatory color scheme. Follow it exactly:
- Define `:root` variables matching the scheme's hex values
- Use ONLY `var(--xxx)` for ALL colors
- NEVER introduce new hex colors not in the scheme
- Background color/gradient MUST match the scheme on EVERY slide

## Output Format

Return ONLY the complete HTML document starting with `<!doctype html>`.
