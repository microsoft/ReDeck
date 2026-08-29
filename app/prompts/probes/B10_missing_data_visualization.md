# B10: Missing Data Visualization - missing_data_visualization

## Focus
Evaluate whether quantitative or result-heavy content is forced into prose when
a chart, table, heatmap, matrix, or other visual summary is needed for pattern
perception.

## Core principle
Numbers that ask the viewer to compare, rank, track change, inspect variation,
or understand multi-metric results should be visually organized. Exact values
can remain in text only when there are few of them or lookup precision is the
main task.

## Evaluation calibration
Judge whether the numeric content requires pattern perception. Use observable
evidence such as count of numeric items, repeated methods/datasets/time points,
comparative words, trend language, rankings, ablation/result labels, table size,
and whether the slide claim depends on comparing values.

## Pass if
1. Quantitative comparisons, trends, distributions, and multi-metric results use
   charts, tables, heatmaps, matrices, or aligned metric structures.
2. A small set of headline numbers is presented as bullets or metric cards when
   exact emphasis is enough.
3. The audience can see the key comparison, trend, ranking, or result pattern
   without mentally reconstructing it from prose.
4. Tables are used when exact lookup matters more than visual pattern detection.

## Fail if
1. Five or more numeric results, percentages, measurements, model scores, or
   benchmark values are presented mainly as prose or unaligned bullets and the
   slide asks the viewer to compare them.
2. A trend, before/after change, ablation, ranking, distribution, or multi-metric
   result is described in text but not visually organized, so the viewer must
   compare values manually to see the pattern.
3. A raw quantitative table with multiple rows/columns/groups is shown without
   grouping, highlighting, sorting, sparklines, heatmap treatment, or summary
   structure, so the key result is not visually discoverable.
4. Numeric evidence is central to the slide's claim, but the current prose makes
   the viewer manually compute direction, magnitude, or relative importance.
5. Multiple datasets, methods, conditions, cohorts, or time points are compared
   in sentences where an aligned chart/table/matrix would materially reduce
   cognitive load.
6. A repair preserves numeric prose but still fails to expose the intended
   quantitative pattern or comparison.

## Do not flag
1. Three or four headline values presented as bullets or metric cards when no
   trend, ranking, or multi-way comparison is required.
2. A compact readable table when exact values are the main purpose and the table
   already reveals the key comparison through ordering, grouping, or emphasis.
3. Generic dense prose without quantitative comparison; use B16 or B06.
4. A visualization that exists but uses the wrong chart or diagram form; use B07.
5. Wrong or unsupported numbers; use D02, D04, or other correctness probes.

## Severity
- critical: central quantitative evidence is impossible or highly error-prone to
  interpret because it is not visually organized.
- major: the current prose/table form slows or obscures interpretation of a
  central quantitative comparison, trend, ranking, or result pattern.
- minor: visualization would improve scanning, but the numeric message remains
  understandable.

## Boundary - use another probe instead
- Generic text wall or excessive bullets without quantitative pattern -> B16
- Communication mode mismatch not specifically quantitative -> B06
- Wrong chart/table/diagram type after a visualization exists -> B07
- Redundant chart plus repeated text -> B14
- Data accuracy or chart-source mismatch -> D02 or D04

## Evidence requirements
Identify the quantitative items, the pattern or comparison they imply, why prose
or raw table form forces manual comparison, and the target visual summary. The
planned fix must name the chart/table/matrix structure and the fields or groups
it should encode.
