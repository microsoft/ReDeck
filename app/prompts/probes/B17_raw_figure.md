# B17: Raw Figure - raw_figure

## Focus
Evaluate whether an embedded paper/source figure has been adapted enough for
the slide's actual communication task: readable inspection when inspection is
needed, recognizable context when it is only supporting, and visible emphasis
when the slide asks the audience to find a specific takeaway inside the figure.
B17 is not a general "make academic figures look like native slide graphics"
probe.

## Core principle
Small internal labels are not automatically a defect. Report B17 only when the
slide needs viewers to inspect the embedded figure's internal details and the
current rendering makes that inspection or takeaway discovery fail.
If the title, body text, caption, or callout already carries the message and the
figure is credible supporting evidence, do not report B17 merely because a more
designed remake is imaginable.

## Evaluation calibration
Judge the full slide first. A figure can pass even if some source-figure labels
are small when the surrounding title, captions, callouts, bullets, or side panel
already explain the relevant takeaway and the image is used as supporting visual
context. A figure fails when the image itself is a focal evidence object and the
important internal marks, labels, panels, or trends cannot be read or found at
slide scale.

For quantitative charts and plots, treat the original rendered figure as
high-fidelity evidence. Do not report or plan B17 in a way that replaces a clean
chart with an approximate hand-drawn summary merely because some labels are
small, the chart uses a dense paper style, or the surrounding layout has awkward
whitespace. If the chart's main curves, axes, legend, and title-linked takeaway
are already inspectable or explained by nearby text, do not report B17. If the
remaining problem is unused lower/side canvas, an awkward side rail, weak body
hierarchy, or an undersized-but-clean figure slot, route it to B09/B02/B13 as a
layout/composition issue rather than asking B17 to redraw the chart.

## Global reporting gate
Before reporting B17, all of the following must be true:
1. The target is an embedded paper/source figure, table image, screenshot, or
   generated image standing in for such a figure.
2. The slide's title, claim, or surrounding text requires the audience to inspect
   internal figure details, compare panels, read labels, or locate a highlighted
   finding inside the figure.
3. The rendered figure does not support that task because essential labels,
   marks, panels, or trends are unreadable, visually buried, cropped, or not
   emphasized.
4. The failure is not already better explained by placement/size (B09), clipping
   or overflow (B04/B15), overlap (B03), form mismatch (B07), or missing content
   (C-series).
5. A viewer would materially misunderstand, miss, or be unable to verify the
   slide's claim unless the figure itself is adapted. Borderline polish issues
   should pass or be routed elsewhere.

## Pass if
1. The figure is clean enough to inspect at full-slide scale for the role it is
   assigned.
2. The image is used mainly as recognizable support, and nearby slide text states
   the needed takeaway without requiring viewers to read every internal label.
3. The visible crop contains the intended subject and has coherent frame edges,
   with no source-page margin, neighboring panel fragment, or accidental artifact
   that harms reading.
4. Key data points, branches, or workflow stages are externally explained or
   visibly emphasized when the slide asks viewers to find them.
5. The figure style is compatible enough with the deck that it does not distract
   from the slide's hierarchy.

## Fail if
Require at least two concrete rendered signals, and at least one must be an
essential task failure rather than style preference:
1. Essential figure text, labels, legends, tick marks, node labels, or panel
   labels are unreadable at full-slide scale, and the slide relies on those
   details for its claim.
2. The slide asks the viewer to compare or locate specific panels, series,
   branches, stages, or marks inside a dense figure, but the relevant targets
   cannot be found from the rendered image and surrounding text.
3. The intended subject is mixed with source-page margins, partial neighboring
   panels, clipped prose, or extraction artifacts that weaken the figure frame.
4. A key trend, branch, or result is present but not highlighted or annotated,
   while surrounding slide text does not guide the viewer to it.
5. The figure is presented as the primary evidence, but the rendered image is so
   miniaturized, blurred, cropped, or internally cluttered that the specific
   evidence named by the slide cannot be identified.

## Do not flag
1. A visually acceptable source figure only because some nonessential internal
   labels are below an ideal size.
2. A conclusion, overview, or context slide where the figure functions as a
   recognizable illustration and the adjacent text carries the message.
3. A clean, simple figure embedded directly with readable focal labels or clear
   surrounding explanation.
4. Style mismatch alone unless it creates a real readability, hierarchy, or
   takeaway-discovery problem.
5. Internal problems inside an immutable bitmap that the slide system cannot
   faithfully edit unless the issue can be fixed by presentation adaptation of
   the image as a whole.
6. A clean quantitative chart/plot whose plotted relationships and title-linked
   takeaway are understandable, even if some ticks, minor labels, or paper-style
   details are not comfortable to read.
7. A figure whose main weakness is the slide body's blank space, side-rail
   composition, or overall hierarchy while the source figure itself remains
   credible evidence.

## Repair strategy gate
The planned fix must choose the least destructive adaptation that can solve the
rendered failure:
1. **Keep original figure / local geometry**: use when the figure is basically
   acceptable and only needs a larger display slot, cleaner frame, or nearby
   existing annotation. Do not replace the figure.
   Do not treat "wide shallow strip", "many panels", "dense chart", or "paper
   style" as automatic proof that local/source-preserving adaptation is
   insufficient. Escalate only when rendered evidence shows the slide still
   cannot support the specific inspection task after preserving the original
   figure.
2. **Real crop or recomposed source asset**: use when the original figure has
   irrelevant margins, neighboring panels, or only a subset of panels is needed.
   Preserve the recognizable source subject and state the exact crop/recompose
   target.
3. **Source-grounded SVG/chart summary asset**: use only when crop/recomposition
   would still leave essential content unreadable, or the slide explicitly needs
   a simplified conceptual progression rather than literal figure evidence. The
   planned_fix must explicitly say to replace the image source with a generated
   source-grounded summary asset and list the labels, relations, data, or stages
   that must be preserved.
   For quantitative charts, prefer `generate_chart` only when exact source data
   are available. Do not prescribe a hand-drawn SVG summary that approximates
   plotted curves, axes, legends, tick values, or measured relationships from
   visual memory; that loses the evidentiary value of the original chart. If the
   original chart is basically good but hard to fit, preserve it and repair the
   body layout or leave B17 unresolved for a downstream layout issue.
4. If the figure looks acceptable enough and the benefit of replacement is
   mostly stylistic, recommend KEEP or a minimal patch rather than redrawing it.
5. If the figure is acceptable but the slide composition is not, do not force a
   B17 fix. State that the figure should remain and route the problem to layout
   reflow or density/spatial probes.

## Severity
- critical: the figure is essential evidence and is effectively unusable or
  misleading in the rendered slide.
- major: the unreadable or unadapted figure materially harms inspection,
  hierarchy, or takeaway discovery.
- minor: the adaptation weakness is visible but the slide remains understandable;
  do not report personal style preference.

## Boundary - use another probe instead
- Figure/table is too small for its assigned region but otherwise clean -> B09
- Figure/chart is good evidence but the body layout leaves awkward lower or
  side voids -> B09 or B02
- Wrong visual form or chart type -> B07
- Text or element clipping/overflow outside the bitmap -> B04 or B15
- Literal overlap/occlusion with other slide elements -> B03
- Missing figure, missing data, or missing evidence -> C-series
- Content inside the source bitmap is wrong but faithfully embedded -> source
  or content-family issue, not B17

## Evidence requirements
State the figure's role in the slide, which internal details the viewer must
inspect, the rendered signals that make those details unreadable or buried, and
why adjacent text does not already carry the takeaway. The planned_fix must name
the target figure, choose one repair strategy from the gate above, preserve
visible slide text, and explicitly say whether the original image should remain,
be cropped/recomposed, or be replaced by a source-grounded summary asset.
For a chart/plot replacement, the planned fix must explain how data fidelity is
preserved: exact source data for a regenerated chart, or a source-preserving
crop/recomposition of the original. Without that evidence, do not recommend a redraw.
If the recommendation starts with local resize/reposition, include what evidence
would make that insufficient and what the next strategy should be. Do not rely
on numeric thresholds; use observable task evidence such as whether the internal
labels/panels needed by the slide become inspectable and whether the surrounding
layout still contains an accidental lower/side void.
