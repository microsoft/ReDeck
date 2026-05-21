# B17: Raw Figure — raw_figure

## Focus
Evaluate whether figures from the source document have been adapted for presentation context — readable text, visual emphasis, and style consistency.

## Core principle
Source document figures need adaptation for slides — text must be readable at projection size and key findings should be visually highlighted.

## Pass if
1. Figure text is ≥10pt at presentation size
2. Key data points or findings are highlighted or annotated
3. Figure style matches the overall deck aesthetic

## Fail if
1. Figure text is <10pt and would be unreadable when projected
2. Dense source formatting clashes with the deck's style
3. Figure has key findings but no visual emphasis or annotation to guide the viewer

## Do not flag
1. Clean, simple figures with readable text
2. Slides that provide text annotations alongside the figure to explain it

## Severity
- major: figure text is unreadable at presentation size, or key findings are buried without emphasis
- minor: style mismatch with no readability impact

## Boundary — use another probe instead
- Text too small across the slide generally → B11
- Data visualization form wrong → B07

## Evidence requirements
Describe the figure, estimate its text size, note whether key findings are highlighted, and assess style fit with the deck.
