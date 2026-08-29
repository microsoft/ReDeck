# B03: Overlap / Occlusion - overlap

## Focus
Evaluate whether rendered slide elements physically overlap or occlude each
other in a way that hides content, data, labels, or intended visual boundaries.

## Core principle
Every meaningful element must remain visibly separable and inspectable in the
final rendered pixels. Geometry maps are useful hints, but the visible rendered
state is the final evidence.

## Evaluation calibration
Use bounding boxes to find candidate collisions, then verify with rendered
pixels. Report only when one element visually covers, crosses through, or masks
another meaningful element enough to change readability, inspectability, or
semantic interpretation.

## Pass if
1. Text, images, charts, icons, tables, badges, rules, headers, footers, and
   decorative shapes remain visually separated or intentionally layered.
2. Text-over-image or text-over-shape layering uses contrast, padding, and
   background treatment that keeps the foreground readable.
3. Chart labels, legends, axis labels, tick labels, and data marks do not cover
   each other in a way that prevents interpretation.
4. Decorative lines, bands, frames, and accents do not pass through meaningful
   text or data.

## Fail if
1. A text block, label, number, icon, table cell, chart mark, legend, or image is
   visibly covered by another element and the covered content becomes unreadable,
   ambiguous, or only partially inspectable.
2. A foreground/background layering choice lacks the contrast, padding, or
   overlay treatment needed to make the foreground content readable.
3. Chart internals collide: labels overlap labels, labels cover data marks, a
   legend covers plotted data, or axis/tick text collides with marks or captions.
4. An image, screenshot, figure, or video frame is placed over nearby text or a
   panel so that either the image or the text/panel cannot be inspected.
5. Decorative shapes, dividers, diagonal rules, badges, header/footer bands, or
   container backgrounds cut through or cover meaningful content.
6. A repair moves or scales an element so that a previously readable neighbor is
   now partially hidden, even if the moved element itself looks larger or more
   prominent.

## Inspection steps
1. Identify all visible element regions from the rendered slide and spatial map.
2. Check pairs whose boxes intersect or nearly intersect; then confirm against
   the actual pixels, not box math alone.
3. Inspect dense regions manually: chart labels, legends, figure/caption edges,
   title bars, footer/takeaway bands, badges, and panel corners.
4. Report the issue only when the overlap changes readability, inspectability,
   or semantic interpretation.

## Do not flag
1. Planned layering that remains readable, such as text on a darkened image
   overlay or a label inside a padded badge.
2. Minor edge contact, shared borders, or adjacent containers that touch without
   covering content.
3. Internal overlaps inside an uneditable embedded bitmap or source figure; flag
   only the placement, scale, clipping, or visibility of the image element itself.
4. Text that extends beyond its container without another element covering it;
   use B04 or B15.
5. Crowding, weak spacing, or poor alignment without literal visible occlusion;
   use B09 or B13.

## Severity
- critical: primary content, key data, or the main figure is hidden enough that
  the slide cannot be interpreted.
- major: meaningful content is partially occluded and reading or inspection is
  clearly impaired.
- minor: non-primary overlap affects a local label, icon, or decorative-adjacent
  element, but the main message remains recoverable.

## Boundary - use another probe instead
- Text clipped by its own container or overflowing canvas -> B04 or B15
- Density/crowding with no physical occlusion -> B09
- Alignment or spacing inconsistency with no occlusion -> B13
- Low foreground/background contrast without physical coverage -> B05
- Raw source figure whose internal labels overlap before slide placement -> B17

## Evidence requirements
Name both overlapping elements, where the overlap occurs, what visible content is
covered, and why that coverage affects reading or inspection. The planned fix
must specify whether to move, resize, re-layer, crop less, add padding, or change
an overlay treatment.
