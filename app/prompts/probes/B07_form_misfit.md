# B07: Form Misfit - form_misfit

## Focus
Evaluate whether a chart, table, diagram, map, process graphic, or other visual
form matches the data type and relationship it is supposed to communicate.

## Core principle
The visual form should make the intended relationship easier to perceive. A form
misfit is a semantic/encoding error, not merely a preference for a different
graphic style.

## Evaluation calibration
Judge the mapping between relationship and encoding. Use the slide claim, axis
labels, categories, ordering, units, connectors, legends, and grouping structure
as evidence. Do not report a form as wrong only because another form could also
work.

## Natural visual form guide
1. Comparison across categories: bar chart, dot plot, ranked table, or aligned
   metric cards.
2. Trend over ordered time or steps: line chart, area chart, slope chart, or
   ordered timeline.
3. Composition or part-to-whole: stacked bar, 100% bar, treemap, or pie/donut
   only for few categories with clear proportions.
4. Distribution: histogram, density plot, box/violin plot, or summary table with
   distribution statistics.
5. Relationship or correlation: scatter plot, matrix, network, or paired
   comparison view.
6. Process, sequence, causal flow, or pipeline: flowchart, timeline, swimlane,
   Sankey, or step diagram.
7. Hierarchy, taxonomy, or decomposition: tree, nested list, matrix, or layered
   architecture diagram.
8. Architecture or system interaction: block diagram with labeled components and
   directional connectors.
9. Multi-metric results: table, small multiples, grouped bars, radar only when
   scale comparability is explicit and not misleading.

## Pass if
1. The chosen form matches the data relationship and helps the viewer see the
   intended pattern.
2. Encodings, axes, labels, and grouping preserve scale and category meaning.
3. Tables are used when exact lookup is more important than seeing a pattern.
4. Diagrams use arrows, nesting, layers, or proximity to represent real semantic
   relationships.

## Fail if
1. The form encodes the wrong relationship, such as using a pie chart for a
   trend, a line chart for unordered categories, or a flowchart for unrelated
   peer facts.
2. A table, chart, or diagram makes the intended comparison, trend, composition,
   distribution, relationship, process, hierarchy, or architecture harder to
   perceive than structured text would.
3. The visual encoding creates low discrimination for important differences,
   such as compressed bar/line variation, inappropriate axis domain, excessive
   aggregation, or too many nearly indistinguishable series.
4. The axis or scale minimizes meaningful differences by using an inappropriate
   range, baseline, transformation, or aggregation for the stated claim.
5. The axis or scale exaggerates minor differences by truncating, stretching, or
   transforming values without clear labeling and justification.
6. A process, causal, or architecture diagram has semantic connector errors,
   such as wrong arrow direction, missing input/output, false sequence, or
   unlabeled component interactions.
7. Diagram elements do not match the concepts they represent, such as using
   hierarchy/nesting for non-hierarchical items or peer boxes for parent-child
   relationships.
8. The visual merely restates adjacent text while occupying a main content
   region and adding no structural relationship, lookup value, or pattern
   perception.
9. A chart or diagram is not interpretable because essential labels are missing,
   such as both axis labels and value labels, unexplained units, or unlabeled
   series/legend.
10. A multi-metric or multi-series result is encoded in a form that prevents fair
   comparison because scales, baselines, or groupings are inconsistent.

## Do not flag
1. A simple table instead of a chart when exact values or lookup are the main
   task and the table is readable.
2. Metric cards for a small set of headline values when the goal is emphasis,
   not trend or distribution analysis.
3. A visual merely because another chart type could also work; report only when
   the current form obscures, distorts, or misrepresents the relationship.
4. Redundant chart plus repeated text; use B14.
5. Numeric prose that lacks any visualization; use B10.

## Severity
- critical: the form actively misleads about the data, process, hierarchy, or
  system relationship.
- major: the form encodes the relationship incorrectly enough to impede
  interpretation.
- minor: one local encoding choice reduces clarity, but the intended relationship
  remains recoverable.

## Boundary - use another probe instead
- Chart data or source numbers are wrong -> D04 or D02
- Numeric results need a visualization but no visual exists -> B10
- Chart plus text redundantly repeat the same information -> B14
- Labels are unreadable due to contrast, overlap, clipping, or tiny text -> B05,
  B03, B04, B15, or B16
- Raw academic figure needs slide adaptation -> B17

## Evidence requirements
Identify the visual element, the relationship it claims to show, the mismatch
between relationship and form/encoding, and the target form that would expose
that relationship. The planned fix must specify the replacement form or encoding
adjustment, including axis, grouping, labels, or connector changes when relevant.
