# B02: Layout Appropriateness - layout_inappropriate

## Focus
Evaluate whether the slide's structural layout pattern fits the content task.

## Core principle
The layout skeleton should make the content task inferable from visible
structure. A comparison should expose comparable slots, a process should expose
order, a figure-centric slide should reserve an inspectable figure region, and a
single takeaway slide should expose one primary focal region plus a next-step
reading path.

## Evaluation calibration
Use observable signals: title wording, element roles, containers, labels,
relative size, placement, color weight, and reading order. Do not require a
universal pixel threshold, but the mismatch must be verifiable from the rendered
slide and spatial map.

## Pass if
1. The layout pattern matches the content task and audience can infer how to read
   it without extra explanation.
2. The primary message has a clear structural role, even when supporting content
   is visually rich.
3. Secondary material is lower in hierarchy by at least one visible cue, such as
   smaller scale, peripheral placement, lighter color weight, or placement inside
   a supporting container.
4. The reading path can be described from the visible structure at full-slide
   scale, such as title -> figure -> caption, left column -> right column, or
   step 1 -> step 2 -> step 3.

## Fail if
1. The slide uses a layout skeleton that does not match the content task, such as
   a process shown as unrelated cards, a comparison shown as disconnected prose,
   or a figure-centric point placed in a layout that prevents figure inspection.
2. The slide has no identifiable first focal region or reading path because
   co-equal regions share similar size/weight/placement and lack sequence,
   hierarchy labels, or grouping cues.
3. A secondary region, note, decoration, metadata block, or supporting image is
   larger, darker, more central, or more saturated than the actual core message,
   causing the core message to be compressed or visually subordinated.
4. Multiple major regions, typically four or more, are presented as competing
   peers even though titles, labels, or content semantics indicate hierarchy,
   sequence, or grouping.
5. Title and subtitle/body roles are structurally ambiguous because they use
   near-identical placement, size, weight, and spacing, making the heading stack
   read as one undifferentiated block.
6. A slide that needs side-by-side comparison, ordered stages, or input-output
   reasoning uses a free-form scatter of boxes/text/images that forces the viewer
   to infer the relationships from content alone.

## Do not flag
1. A layout merely because it has large whitespace, high density, or uneven
   column heights; use B09 when the root cause is canvas use or density.
2. Peer alignment, gap rhythm, or grouping errors inside an otherwise suitable
   layout; use B13.
3. A chart, table, or diagram whose specific visual form is wrong; use B07.
4. A text-heavy slide when prose is the appropriate content mode; use B16 only
   for unstructured text walls.
5. Structured multi-panel layouts when labels, numbering, containers, or visual
   hierarchy make each panel's role clear.
6. Cover, section divider, quote, or roadmap layouts whose title, focal element,
   and supporting metadata form a complete readable structure.

## Severity
- critical: the layout skeleton makes the main message or content relationship
  incomprehensible.
- major: the layout choice visibly works against the content task and slows or
  confuses reading.
- minor: one local structural choice slows reading, but the intended message and
  reading path remain recoverable.

## Boundary - use another probe instead
- Content density, under-composed canvas use, or peer visual weight mismatch -> B09
- Alignment, spacing, anchor, or grouping inconsistency within a suitable layout -> B13
- Wrong chart/table/diagram form -> B07
- Generic unstructured text wall -> B16
- Source figure itself cannot support the slide's required internal inspection
  task -> B17
- Cross-slide title/footer/style drift -> B01

## Evidence requirements
Name the content task, the current layout skeleton, the structural mismatch, and
the element or relationship that should become primary. Cite the visible cues
that support the diagnosis. The planned fix must describe a concrete
restructuring action, not just "make the layout better". When the mismatch is a
figure/chart evidence slide with a cramped side rail and an unused lower or side
region, specify the intended reading path and skeleton explicitly, such as
title -> evidence figure -> interpretation panel -> takeaway. This may be a
top/bottom evidence-then-interpretation layout, a reduced side takeaway plus
lower interpretation band, or another structure that fits the content. Do not
force this pattern for every figure slide; use it when the current skeleton
makes local resizing insufficient or would leave the same void/reading-path
break in place. If the figure is a complete embedded wide/shallow asset, do not
ask the repair agent to solve the skeleton mismatch by simply increasing the
image height. The plan should preserve the image's integrity and instead name
which existing callouts, notes, captions, or comparison elements should become a
lower/adjacent support region so the unused area becomes part of the reading
path.
