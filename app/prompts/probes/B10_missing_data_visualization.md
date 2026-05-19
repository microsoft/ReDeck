# B10: Missing Data Visualization — missing_data_visualization

## Focus
Evaluate whether data-heavy results use appropriate visual summaries rather than raw numbers in prose.

## Core principle
Quantitative comparisons and trends are faster to perceive visually — charts and tables reduce cognitive load.

## Pass if
1. Quantitative content uses charts, tables, heatmaps, or other visual summaries
2. Audience can see comparisons and trends quickly
3. Raw numbers are not dumped as plain bullet lists

## Fail if
1. Many numeric results presented in prose where a chart would be more effective
2. Trends are hard to perceive from a long list of numbers
3. Large raw table presented without any visual summary
4. Data-heavy content increases cognitive load unnecessarily

## Do not flag
1. Small number of key metrics presented as bullets (≤3–4 values)
2. Compact table used when exact values matter more than trends

## Severity
- major: significant data that would clearly benefit from visualization presented as text
- minor: moderate data where visualization would help but text is still functional

## Boundary — use another probe instead
- Wrong chart type chosen → B07
- Text-visual balance issues → B06

## Evidence requirements
Identify the numeric data presented as text, explain what pattern or comparison it represents, and suggest what visualization would be more effective.
