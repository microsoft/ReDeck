# B02: Layout Appropriateness — layout_inappropriate

## Focus
Evaluate whether the layout is structurally appropriate for the content it presents.

## Core principle
Layout should serve the content's communication goal — the right structure makes the message immediately clear.

## Pass if
1. No >50% whitespace with content squeezed into a small area
2. Reading order follows left-to-right, top-to-bottom convention
3. Core point is visually prominent

## Fail if
1. Important content squeezed into a wrong layout type
2. No clear reading path — viewer cannot determine where to look first
3. Secondary element dominates while the core message is compressed
4. 4+ competing visual elements with no hierarchy
5. Subtitle styled too close to the title (insufficient visual distinction)

## Do not flag
1. Intentional high-whitespace section breaks
2. Bullet layouts for text-heavy content
3. Metric cards or tables used instead of charts
4. Up to 20% unused space
5. Content density issues (→ B09)

## Severity
- critical: layout completely wrong for content type, message incomprehensible
- major: layout clearly inappropriate, reading path confused
- minor: layout suboptimal but message still comes through

## Boundary — use another probe instead
- Content density problems → B09
- Alignment/spacing within a layout → B13
- Bullet list where comparison table would be better → B07

## Evidence requirements
Describe the content type, the layout used, and why the layout is inappropriate. Note which element should be prominent and what currently dominates.
