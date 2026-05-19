# B05: Low Contrast — low_contrast

## Focus
Evaluate whether text has sufficient contrast against its background for readability.

## Core principle
WCAG AA standards: 4.5:1 contrast ratio for normal text, 3:1 for large text (≥18pt or ≥14pt bold).

## Pass if
1. All text is clearly readable with good contrast
2. Dark text on light backgrounds or light text on dark backgrounds
3. Contrast ratios meet WCAG AA thresholds

## Fail if
1. Insufficient contrast making text hard to read
2. Light gray text on white, cream, or light purple backgrounds
3. Light-colored text on pastel backgrounds
4. Low-contrast footnotes or captions

## Do not flag
1. Medium gray (#666, #777) footnotes on white background (these meet 4.5:1+)
2. Subtle color differentiation on non-text elements (borders, dividers, backgrounds)

## Severity
- critical: nearly invisible primary text (title, heading, key message)
- major: body text with poor contrast affecting readability
- minor: secondary text (footnotes, captions) with marginal contrast

## Boundary — use another probe instead
- Color conveying wrong meaning → B18
- Text rendering/character issues → B11

## Evidence requirements
Identify the text element, its approximate color, the background color, and the estimated contrast ratio. Note the text's role (title, body, caption, etc.).
