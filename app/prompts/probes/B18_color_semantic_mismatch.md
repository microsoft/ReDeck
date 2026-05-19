# B18: Color Semantic Mismatch — color_semantic_mismatch

## Focus
Evaluate whether decorative and accent colors inadvertently convey value judgments that don't match the content.

## Core principle
Colors carry meaning — red signals danger/bad, green signals good/go. Using these on neutral content sends false signals.

## Pass if
1. Colors are consistent with content semantics
2. Neutral items use neutral coloring

## Fail if
1. Green and red used for neutral parallel items (implying good/bad where none exists)
2. Same-type containers use inconsistent hero colors (suggesting different importance)
3. Strong accent color highlights a non-conclusive or neutral number

## Do not flag
1. Brand colors applied uniformly across the deck
2. Red/green used in genuine good/bad or increase/decrease contexts
3. Sequential color palettes for ordered data

## Severity
- major: color actively misleads the viewer about meaning or importance
- minor: color is inconsistent but not actively misleading

## Boundary — use another probe instead
- Overall color inconsistency across deck → B01
- Contrast/readability issues → B05

## Evidence requirements
Identify the colored elements, their colors, the content they represent, and explain why the color choice creates a misleading semantic signal.
