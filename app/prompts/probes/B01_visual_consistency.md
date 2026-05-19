# B01: Visual Consistency — visual_inconsistency

## Focus
Evaluate whether typography, color logic, spacing, margins, and hierarchy are consistent across the deck.

## Core principle
A cohesive deck looks like one designer made it; inconsistency signals carelessness or template mismatch.

## Pass if
1. Title and body styles are consistent across slides
2. Colors follow a stable logic throughout the deck
3. Recurring elements (cards, callouts, headers) share a common grid
4. Local variation serves the content rather than appearing arbitrary

## Fail if
1. Inconsistent type scales or margins across slides
2. Arbitrary color changes between slides with no logical basis
3. Inconsistent recurring components (e.g., cards styled differently for no reason)
4. Deck feels assembled from unrelated templates

## Do not flag
1. Deliberate section-divider variation
2. Common palette with different card arrangements
3. Minor ±2pt font variation
4. Different layouts for different content types
5. Title/cover slide using a different background
6. Dark-to-light transition between sections

## Severity
- critical: deck-wide inconsistency across multiple dimensions (type, color, spacing)
- major: clear inconsistency in one dimension across multiple slides
- minor: subtle inconsistency noticeable only on close inspection

## Boundary — use another probe instead
- Mixed fonts within a single text block → B12
- Alignment/spacing issues within a single slide → B13

## Evidence requirements
Cite specific slides and elements that are inconsistent, noting what differs (font size, color, margin, component style).
