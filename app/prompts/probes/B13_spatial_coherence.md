# B13: Spatial Coherence / Alignment - alignment_inconsistency

## Focus
Evaluate whether elements that belong to the same logical group, peer set, or
parent-child structure share a coherent spatial contract.

## Core principle
Alignment and spacing matter when they express meaning. Within a logical group,
same-role elements should share anchors, gaps, proximity, and internal rhythm so
the viewer can immediately see what belongs together, what should be compared,
and where to read next.

## Evaluation calibration
Do not judge generic neatness. Judge whether a named group violates a spatial
contract that can be observed in the rendered slide. Useful evidence includes
shared edges, centerlines, baselines, repeated gap rhythm, container padding,
relative proximity, grouping boundaries, and whether an element aligns more
strongly with the wrong group than with its intended group.

## Required report gate
Before reporting B13, identify all of the following:
1. The named logical group or relationship, such as peer cards, a label-value
   pair, a figure-caption pair, a sidebar group, a title/body stack, or repeated
   process steps.
2. The spatial contract that should be shared, such as left/right/top/bottom
   edge, centerline, baseline, gap, width, height, internal padding, proximity,
   or grouping boundary.
3. The visible rendered violation at full-slide scale.
4. The functional harm: weakened grouping, comparison, association, or reading
   path.
5. The root cause is spatial anchoring/grouping, not overlap, clipping, density,
   layout skeleton mismatch, or cross-slide style drift.

## Pass if
1. Same-role peers share a clear alignment edge, centerline, baseline, width,
   height, or other visible anchor appropriate to their role.
2. Repeated items have a gap rhythm that is consistent within each peer set, or
   the variation is explained by hierarchy, content length, or grouping.
3. Parent-child or label-value pairs are closer to each other and share stronger
   anchors than they do with unrelated elements.
4. Related elements are grouped by proximity, shared container, consistent
   padding, boundary, or directional alignment.
5. Different hierarchy levels use different spatial treatment while preserving a
   clear parent-child or reading-order relationship.

## Fail if
1. Same-role peers that should share an edge, centerline, baseline, width, or
   height visibly deviate from that shared anchor, weakening comparison or making
   the peer set read as unrelated placements.
2. Repeating peer items have visibly uneven gaps that are not explained by
   hierarchy, content length, or grouping structure.
3. A label/value, icon/text, figure/caption, title/body, or callout/target pair
   uses mismatched anchors or a larger-than-peer gap, weakening the association.
4. A related element is orphaned from its logical group because it is farther
   from its group than comparable group members are, lacks their shared anchor,
   or sits outside the group boundary/proximity cue.
5. Unrelated elements appear grouped because they are closer to each other, share
   an anchor, sit in the same container, or align more strongly with each other
   than with their true groups.
6. A natural group lacks a visible grouping cue, such as proximity, shared
   boundary, consistent padding, repeated alignment, or connector, so the viewer
   must infer the grouping only from text.
7. Peer panels, columns, or cards with equal semantic role use inconsistent
   internal padding, edge rhythm, label placement, or slack distribution that
   weakens comparison or implies a role difference not supported by content.
8. A repair fixes one element's position but leaves the peer set with a new
   near-miss alignment, uneven gap rhythm, or broken parent-child association.

## Do not flag
1. Different hierarchy levels using different alignment, indentation, size, or
   spacing to show rank.
2. Asymmetry where anchors, grouping, and reading order remain explicit.
3. Overall sparse, crowded, or uneven canvas use without a specific logical group
   contract violation; use B09.
4. Wrong layout skeleton for the content task; use B02.
5. Literal overlap/occlusion or clipping/overflow; use B03, B04, or B15.
6. Cross-slide title/footer/style drift; use B01.
7. Tiny differences that are not visible at full-slide scale and do not affect
   grouping, comparison, association, or reading path.

## Severity
- critical: spatial contract failures make the slide's grouping, comparison, or
  reading path materially ambiguous.
- major: a visible group-level alignment, gap, anchor, or proximity failure harms
  scanning, comparison, association, or reading order.
- minor: a local spatial inconsistency is visible but the group relationship and
  message remain clear.

## Boundary - use another probe instead
- Overall density, under-composition, cramped canvas, or peer visual weight -> B09
- Wrong content-task layout skeleton -> B02
- Literal overlap or occlusion -> B03
- Text/element overflow or clipping -> B04 or B15
- Generic text wall -> B16
- Cross-slide visual style inconsistency -> B01

## Evidence requirements
Name the logical group, the expected spatial contract, the observed violation,
and the functional harm. Use concrete spatial terms such as left edge, top edge,
baseline, gap, width, height, padding, proximity, or container boundary. The
planned fix must specify the anchor/gap/grouping change and its target relation,
not just "align it". Exact pixel thresholds are optional, but the evidence must
be reproducible from the rendered slide or spatial map.
