# B07: Form Misfit — form_misfit

## Focus
Evaluate whether charts, diagrams, tables, and other visual forms are appropriate for the data and relationships being communicated.

## Core principle
The visual form should match the data's nature — the right chart makes the pattern obvious, the wrong one obscures it.

## Pass if
1. Visual form matches the data relationship (comparison, trend, composition, distribution)
2. Visual helps interpretation rather than hindering it
3. Visual doesn't distort scale or proportions
4. Chart type matches data type (categorical, temporal, continuous)

## Fail if
1. Chart type inappropriate for the data (pie chart for trends, line chart for unordered categories)
2. Table or chart creates confusion rather than clarity
3. Visual adds no information beyond what text already states (occupying >25% of slide)
4. Flowchart used for non-sequential information
5. Bar chart where all bars are nearly the same height (<10% difference between values)
6. Y-axis range minimizes or exaggerates actual differences
7. Flowchart has semantic errors (wrong arrow directions, illogical flow)
8. Diagram elements don't match the concepts they represent
9. Architecture diagram used for non-hierarchical data
10. Diagram merely restates adjacent text with no added structure
11. Unreadable chart — no axis labels AND no value labels

## Do not flag
1. Simple table used instead of chart when the data is clear
2. Metric cards for ≤4 values

## Severity
- critical: visual form actively misleads about the data
- major: form clearly wrong for the data type, impedes understanding
- minor: suboptimal form choice but data still interpretable

## Boundary — use another probe instead
- Chart data accuracy (wrong numbers) → D-series (D04)
- Redundant chart + text restating same data → B14

## Evidence requirements
Identify the visual element, the data it represents, why the current form is inappropriate, and what form would better serve the content.
