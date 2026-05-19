# B03: Overlap — overlap

## Focus
Evaluate whether elements are visually separated and no content is hidden behind other elements.

## Core principle
Every content element must be fully visible and legible — nothing should be occluded.

## Pass if
1. No element is hidden behind another
2. No text overlaps other text
3. No decorative shapes cover content
4. No chart labels overlap each other

## Fail if
1. Content elements overlap making text or data unreadable
2. Decorative shape covers meaningful content
3. Chart labels overlap each other
4. Image placed on top of text, obscuring it

## Do not flag
1. Intentional layering with good contrast (e.g., text over image with overlay)
2. Minor edge-pixel touching without readability impact

## Severity
- critical: primary content completely hidden or unreadable due to overlap
- major: significant content partially obscured
- minor: minor overlap with minimal readability impact

## Boundary — use another probe instead
- Content squeezed into corner → B09
- Text extending beyond containers → B04 or B15

## Evidence requirements
Identify the overlapping elements, their positions, and what content is obscured. Note whether the overlap affects readability.
