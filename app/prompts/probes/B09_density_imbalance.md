# B09: Density Imbalance - density_imbalance

## Focus
Evaluate whether the rendered slide uses canvas area, visual weight, and element
scale in a way that supports scanning, inspection, reading order, comparison,
and whether the visible content appears complete for the slide's stated task.

## Core principle
Whitespace is not automatically a defect, and density is not automatically a
defect. Report B09 only when the amount or distribution of content visibly harms
how the slide is read or inspected.

## Evaluation calibration
Use rendered evidence and relative comparisons, not fixed coverage thresholds.
Useful signals include content-cluster location, contiguous blank regions,
relative scale between primary/secondary elements, group separation, line/label
inspectability, and peer region visual weight. Qualitative terms such as sparse,
cramped, or undersized must be tied to those observable signals; none is a pass/fail rule by itself.
When a clean figure/chart remains credible evidence but is too small, weakly
placed, or surrounded by awkward lower/side voids, evaluate the slide-body
composition here rather than as B17. Use B17 only when the source figure itself
cannot support the required internal inspection task despite adequate
placement/size.

## MUST specify sub_type
Every B09 issue MUST include exactly one of: `sparse_content` |
`cramped_content` | `element_undersized` | `column_height_mismatch`.

The historical subtype name `column_height_mismatch` covers peer visual-weight
contract failures, not just literal column bottom coordinates.

## Global reporting gate
Before reporting B09, all of the following must be true:
1. The problem is visible in the rendered full-slide view.
2. The problem harms at least one functional outcome: scanning, inspection,
   reading order, comparison, or whether the visible content appears complete
   for the slide's title/claim.
3. The root cause is density, scale, canvas use, or peer visual weight; it is not
   primarily overlap, clipping, layout skeleton mismatch, communication-mode
   mismatch, intrinsic raw-figure readability failure, or local alignment/spacing.
4. The fix can preserve the existing visible content by changing geometry,
   scale, grouping, hierarchy, or whitespace allocation.

## Pass if
1. The main subject is primary by visible cues such as scale, centrality, color
   weight, title linkage, container prominence, or reading-order position.
2. Whitespace separates, frames, or directs attention rather than creating an
   unexplained void.
3. Elements have readable internal spacing without being stretched or expanded
   only to fill area.
4. Typography remains readable for each information role. Repeated support copy,
   labels, and annotations may be smaller than focal values or conclusions when
   wrapping, contrast, separation, and hierarchy still support scanning.
5. Unequal column heights, panel sizes, or whitespace regions are explained by
   visible hierarchy, labels, source content length, or different semantic roles.
   **Exception**: if one column ends more than 200px above the other and the short
   column has empty dark/colored background visible, this IS a density failure even
   if the columns have different semantic roles. The short column's content should
   be enlarged, redistributed, or the layout should be restructured.
6. A sparse cover, quote, transition, roadmap, or single-message slide has a
   complete visual idea even when most of the canvas is empty.

## Fail if - sparse_content
Use for a content slide that is visibly under-composed. Require at least two
concrete rendered signals:
1. Substantive content is clustered in a corner, edge, or narrow band while a
   contiguous blank region of comparable or larger visual weight has no framing,
   counterweight, directional role, or hierarchy function.
2. The element implied by the title or claim as focal is smaller, less central,
   or lower contrast than secondary notes, decorations, or blank space, and its
   details are not comfortably inspectable.
3. A contiguous blank region sits between title and body, between related groups,
   or along the expected reading path, causing the visible sequence to break.
4. Related existing elements lack a shared container, alignment axis, proximity,
   or scale relationship, so they read as isolated fragments rather than one
   composition.
5. The visible elements do not establish a primary focal area or complete group
   structure for the slide's stated task, even though the issue can be fixed by
   rearranging/rescaling existing elements rather than adding new content.

## Fail if - cramped_content
Use when local density harms comprehension or scanning, not merely because the
slide has many words:
1. Multiple groups occupy the same visual zone with similar size/color weight and
   no separator, container, label, or spacing cue that assigns priority.
2. Gaps between semantic groups are comparable to or smaller than internal line,
   item, or label gaps, so group boundaries are not distinguishable at full-slide
   scale.
3. Content is technically visible, but scanning requires reading many adjacent
   elements of similar weight before the main sequence or grouping can be found.
4. A repair increases element size or adds structure but leaves neighboring
   groups with insufficient separation, causing a new crowding problem.

## Fail if - element_undersized
Use when a specific information-bearing element is too small relative to its
assigned role and available region, based on visible inspectability:
1. A chart, image, table, diagram, or focal panel cannot be inspected comfortably
   at full-slide scale.
2. The element is described or titled as central, but its rendered size makes it
   visually secondary to captions, side notes, decorations, or whitespace.
3. The element occupies much less visual weight than its assigned region while
   surrounding blank space, captions, notes, or decoration draw more attention.
4. Enlarging the element within its region would improve inspection and hierarchy
   without causing overlap, clipping, or loss of visible content.

## Fail if - column_height_mismatch
Use only when peer regions are visibly presented as equal-role items and their
visual weight breaks that shared contract:
1. Repeated peer panels, columns, cards, or list groups have no visible semantic
   reason for large differences in emptiness, height, density, or visual weight.
2. One peer region is compressed while another has avoidable internal slack,
   weakening comparison or reading order.
3. Equal-role peer groups use inconsistent scale or whitespace allocation that
   makes one item appear more important without semantic reason.
4. The mismatch is visible at the group level; it is not just a few pixels of
   bottom-edge difference or normal variation in text length.

## Do not flag
1. Large whitespace that frames a focal message, figure, quote, or section
   transition through title linkage, centering, strong focal scale, or directional
   placement.
2. A compact readable cluster whose scale and placement are supported by a clear
   title relationship, container, alignment axis, or surrounding hierarchy.
3. Unequal columns or panels with different semantic importance.
4. Minor corner gaps, normal margins, or breathing room between groups.
5. A slide solely because coverage, word count, quadrant fill, or bottom-edge
   coordinates are low/high.
6. Missing subject matter, missing evidence, or missing detail; route that to a
   C-family completeness probe.
7. Overlap, clipping, local alignment, text wall, communication-mode mismatch, or
   intrinsic raw-figure readability failure already explained by a more specific
   B probe.
8. A repeated-card, table, timeline, or dashboard composition solely because a
   generic detector reports small support text, many words, or high density.
   Report only when the rendered role hierarchy, separation, wrapping, or scanning
   actually fails.

## Severity
- critical: the slide is effectively unusable because density/canvas use blocks
  reading, inspection, or basic composition.
- major: the imbalance is visible at first glance and materially harms scanning,
  interpretation, or comparison.
- minor: the imbalance is clear but non-blocking; do not report personal style
  preference.

## Boundary - use another probe instead
- Wrong layout skeleton for the content task -> B02
- Literal overlap or occlusion -> B03
- Text or element clipping/overflow -> B04 or B15
- Generic unstructured text wall -> B16
- Source figure itself cannot support the slide's required internal inspection
  despite adequate placement/size -> B17
- Local alignment, anchors, gap rhythm, or grouping confusion -> B13
- Missing content or evidence -> C-series

## Evidence requirements
State the subtype, intended focal subject, reading order, specific elements whose
scale/density/visual weight fails, and the functional harm. Measurements may
support the judgment but must not replace rendered evidence; when using a
qualitative term, anchor it to a visible comparison. The planned fix must
preserve all visible content and specify concrete geometry, scale, grouping, or
hierarchy changes.

## B09 planned_fix requirements
For every B09 issue, the planned fix must be specific enough for a code repair
agent that cannot infer your visual intent:
1. Name the existing elements to move, resize, group, or align, using visible
   labels, roles, or positions.
2. Name the blank, crowded, undersized, or mismatched region that creates the
   failure.
3. State the target composition relationship: for example, which groups should
   share a column span, vertical span, baseline, focal hierarchy, or peer visual
   weight.
4. Use concrete operations such as enlarge the figure/table, expand the table
   rows, move the note block under the table, align two column tops, reduce
   internal gaps, or group related cards in one container. Do not rely on
   standalone abstract verbs such as "rebalance" or "redistribute".
5. Choose the scale of intervention and state why. Use a local resize/reposition
   only when it can visibly improve the rendered content itself without creating
   letterbox, clipping, overlap, or an awkward reading path. If the focal
   figure/chart is a complete embedded wide/shallow image, do not prescribe
   height growth as the main fix unless the actual rendered image content would
   become more useful. When a side rail is cramped while the lower or side canvas
   remains empty, write the plan as a body reflow: for example, give the evidence
   figure a more suitable span and move existing interpretation/callout text into
   a grouped lower support panel, or collapse a side rail into one compact
   takeaway while the remaining existing explanation occupies the former void.
   Do not prescribe this reflow for every wide figure; use it only when the void
   harms scanning, inspection, or reading order and local scaling would leave the
   same structural failure.
6. For `sparse_content`, fill the void by recomposing or scaling existing
   visible content; do not add new claims, bullets, figures, decorative filler,
   or unrelated source facts.
   Never prescribe new bullets for a B09 sparse-content fix.
   Do not use captions, source notes, citations, or footer text as the main
   filler for a large blank region; keep them compact and attached to their
   figure or source role.
7. Include a side-effect guard: preserve all visible content, keep footer/source
   regions readable, and avoid creating overlap, clipping, overflow, or a new
   cramped region.
