# B12: Formatting Consistency — formatting_error

## Focus
Evaluate whether typography is consistent within text blocks — no unexpected font size changes, spacing shifts, or capitalization inconsistencies.

## Core principle
Within a single text block or group of same-role elements, formatting should be uniform.

## Pass if
1. Font size is consistent within each text block
2. Line spacing is consistent within each text block
3. Capitalization is consistent across similar elements (all titles same style)
4. No formatting artifacts visible

## Fail if
1. Font sizes change inconsistently within a single text block
2. Line spacing varies within a single text block
3. Capitalization is inconsistent across similar elements (some titles capitalized, others not)
4. Visible formatting artifacts (extra spaces, broken formatting)
5. Footnote-level elements using body-text-sized fonts instead of appropriately smaller sizing
6. LaTeX rendering artifacts: raw `$...$` syntax visible, backslash commands showing as text

## Severity
- major: formatting inconsistency clearly visible and distracting
- minor: subtle inconsistency noticeable on close inspection

## Boundary — use another probe instead
- Cross-slide style consistency → B01
- Character rendering/encoding errors → B11
- Alignment and spacing between elements → B13

## Evidence requirements
Identify the text block or elements with inconsistent formatting, describe what changes (font size, spacing, capitalization), and note whether it appears intentional or accidental.
