# B20: SVG Visual Integrity — svg_visual_defect

## Focus
Evaluate whether a rendered SVG forms a coherent visual system. The first image
for a slide is the full slide. Each SVG region then has an enlarged crop and a
2x2 overlapping detail sheet in the order listed in `inspection_image_order`.

## Core principle
A professional vector visual must make the role, ownership, and relationship of
every visible layer understandable at presentation scale. Judge perceptual
results, not SVG syntax, primitive types, or compliance with a preferred drawing
style. A scene can be readable item by item and still fail when nearby layers
compete, merge, or support more than one plausible interpretation.

## General visual model
Build the model from rendered pixels before judging defects. Classify visible
parts by the job they perform, such as:

- **subject**: the information-bearing object or data mark;
- **owner**: the region or boundary to which content visibly belongs;
- **relation**: a visual path or mark that connects, orders, or compares subjects;
- **label**: text or a symbol that identifies another part;
- **decoration**: a supporting layer with no independent information role.

These are perceptual roles, not SVG tags. A part may appear to have more than one
role; when those roles cannot be separated reliably, that ambiguity is itself a
candidate defect.

## Required inspection procedure
Inspect every enlarged SVG region and its detail sheet independently, then
return to the full slide. Complete all passes even after finding one defect.

1. **Role inventory** — identify the visible subjects, owners, relations, labels,
   decorations, repeated peer sets, and foreground/background order. State what
   visual evidence gives each part that role. Do not assume role from tag name,
   color, or familiar diagram convention alone.
2. **Ownership and accommodation** — for each subject and label, ask which region
   it visibly belongs to and whether that region accommodates its actual contour
   with intentional optical clearance. Inspect clearance in every relevant
   direction and at the part's actual shape, not only an axis-aligned bounding
   box. Partial enclosure is acceptable when ownership remains unambiguous.
3. **Nested-boundary disambiguation** — when a subject has multiple nested or
   adjacent contours, inventory each contour separately and assign one visible
   role to it. Identify the single contour that owns the content and the single
   boundary at which each relation terminates or originates. Do not merge
   contours into a slash-separated combined boundary. Any contour between a
   relation and its actual attachment boundary is intermediate and must satisfy
   the boundary-transition and separation tests. If the pixels do not support a
   unique role or attachment boundary, ownership is visually ambiguous.
4. **Relationship tracing** — trace each apparent relationship from a
   distinguishable source, through a clear visual corridor, to a distinguishable
   target. Check continuity, direction at the destination, and whether the path
   borrows an unrelated boundary or decoration in a way that changes its reading.
5. **Layering legality** — inspect every intersection and occlusion. It is valid
   only when the intended foreground/background order remains clear and all
   affected roles stay recognizable. Readability of the covered content alone
   is not sufficient evidence that the layering works.
6. **Continuity conflicts** — trace every long or closed contour through each
   intersection. A continuous contour visually claims one structural role. If
   two independent roles both remain uninterrupted at the same crossing, the
   scene must provide an unmistakable reason for that crossing and a decisive
   foreground order. A closed contour surrounding a subject still establishes
   a perceived enclosure when it is decorative. A relationship crossing that
   contour with both strokes visibly intact is a broken boundary transition
   when it creates a merged junction or makes the enclosure double as an
   attachment path. Different colors alone do not resolve the continuity
   conflict; inspect negative-space separation and actual occlusion.
7. **Attachment-zone separation** — wherever a relation terminates at a subject
   or passes an intermediate enclosing contour, the path, endpoint, subject
   boundary, and any supporting contour must remain independently recognizable.
   A non-target intermediate contour must visibly yield across a corridor wider
   than the relation stroke or marker, leaving an optical separation channel.
   Merely painting the relation in front of an intact contour at one stroke-width
   crossing is not sufficient: it creates a fused junction even when colors
   differ and the relationship remains traceable. Inspect every incident
   relation on every side of the same subject.
8. **Glyph-field isolation** — inspect the field occupied by every text label or
   compact symbol plus its immediate optical margin. A structural or decorative
   contour entering that field must have a clear semantic reason and layering
   treatment. Faintness and continued readability do not by themselves make a
   stroke through a label field acceptable.
9. **Local competition** — inspect each perceptual neighborhood as a combined
   composition. Ask whether text, boundaries, relationship marks, data marks,
   and decoration simultaneously demand attention or collapse into a tangled
   contour. Individually valid parts can still produce a reportable combined
   failure.
10. **Stress-zone audit** — explicitly locate every smallest-clearance area and
   every junction where three or more visible roles meet. Enumerate the roles
   entering that neighborhood, follow each contour into and out of it, and check
   whether adjacent roles retain a visible separation channel. A junction fails
   when independent parts appear to share one contour, endpoint, or boundary and
   the viewer must rely on color or prior knowledge to separate them.
11. **Boundary-transition audit** — whenever one role reaches or crosses another
   role's boundary, determine which of four readings is intended: terminate at
   it, pass behind it, pass in front of it, or pass through an opening. The
   transition must visibly communicate that reading through separation,
   interruption, or foreground order. Merely overprinting two contours is not a
   designed transition.
12. **Minimum-clearance audit** — inspect the narrowest gap around every compact
   subject or label, including the background immediately behind glyphs. Compare
   opposing sides and same-role peers. Report a visibly pinched or one-sided gap
   when it makes ownership strained, merges roles, or makes one peer look
   accidentally misregistered. Do not require literal contact.
13. **Peer consistency** — compare all parts that appear to share a role. They
   should follow a compatible contract for clearance, alignment, attachment,
   endpoint treatment, and visual weight unless a difference carries meaning.
   Explicitly inspect the topmost, bottommost, leftmost, and rightmost peers and
   every relation incident on a suspect repeated group.
14. **Alternative-reading test** — name the intended reading and ask whether the
   same pixels support another comparably plausible reading of ownership,
   foreground order, or relationship. Report only when the competing reading is
   caused by visible geometry, not missing domain knowledge.
15. **Full-slide materiality** — return to the full-slide image and confirm the
   failure is perceptible in context. Crops locate and explain evidence; they
   must not manufacture a problem that disappears at presentation scale.

`stroke_text_candidates` and other spatial metadata are attention hints only.
Inspect the named region in the pixels. A coordinate intersection is not a FAIL,
and the absence of a deterministic warning is not a PASS.

## Reportability threshold
A defect is reportable only when it is clearly visible in the full-slide image
and causes at least one of these material perceptual failures:

1. a visible role cannot be distinguished from a neighboring role;
2. ownership or accommodation is visibly implausible or ambiguous;
3. a relationship cannot be followed without guessing, or its endpoint/direction
   communicates the wrong structure;
4. layering hides, merges, or falsely groups information-bearing parts;
5. local competition produces an unmistakably crowded, broken, or tangled area;
6. one member of a peer set visibly violates the set's perceptual contract; or
7. clipping, distortion, or misregistration alters the visible information.

The affected content need not be unreadable. A clearly strained boundary,
ambiguous attachment, merged contour, or excessive local competition is a craft
failure when a normal viewer can perceive it on the full slide. Conversely,
do not report a magnified micro-gap, coordinate-level difference, or merely
unfashionable choice whose intended reading remains clear and composed. Do not
use overall balance, readable words, or traceable topology as a waiver for an
otherwise conspicuous local knot, pinched clearance, or broken transition.

## Fail if
1. Two or more visible roles merge so that their separate jobs are difficult to
   parse.
2. Content visibly lacks sufficient room in its apparent owner, crosses a
   structural boundary, or appears to belong to the wrong region.
3. A relationship is detached, interrupted, misdirected, ambiguously attached,
   or routed through unrelated content in a misleading way.
4. An intersection or occlusion creates false grouping, false continuation, or
   an unclear foreground/background order.
5. Independent contours remain visibly continuous through the same junction and
   create a merged boundary, attachment, or label field with no clear reason.
6. A relationship passes a non-target enclosure or supporting contour through a
   fused, one-stroke-width crossing with no optical separation corridor.
7. Several otherwise legible parts create a full-slide-visible concentration of
   competing contours, marks, and labels.
8. Repeated peers use visibly inconsistent spacing, attachment, endpoints, or
   visual weight without semantic purpose.
9. Information-bearing content is clipped, distorted, duplicated, or visibly
   misregistered.

## Pass if
1. Every visible part has a distinguishable role and apparent owner.
2. Relationships can be followed from source to target without guessing.
3. Intersections and layering preserve a clear reading order.
4. Dense regions remain organized rather than locally competitive.
5. Peer differences look meaningful and the scene remains coherent at
   presentation scale.

## Do not flag
1. Aesthetic preference with no visible ambiguity, strain, or craft failure.
2. Intentional enclosure, interruption, overlap, or asymmetry whose visual role
   is clear and whose information remains composed.
3. A part extending outside an inferred region when it occupies appropriate open
   space and still has unambiguous ownership.
4. Minor anti-aliasing or sub-pixel differences visible only in enlarged crops.
5. Problems inside an embedded bitmap; this probe covers rendered SVG content.

## Calibration examples — non-exhaustive
These examples illustrate the mechanisms above. Do not search only for these
objects, require these exact arrangements, or infer a defect from the nouns.

- **Accommodation**: a label can fit its rectangular bounds yet visibly press
  against a curved node at the height of one line; a value badge can remain
  readable yet be pinched against a chart boundary; a footer can sit inside its
  band but lack a credible gap from the divider. All are the same ownership and
  minimum-clearance question.
- **Boundary transition**: a relation heading toward an inner subject can cross
  an unbroken decorative ring and merge with it; a guide can continue behind an
  annotation; a panel divider can pass through a foreground icon. All require a
  clear reading of termination, foreground, background, or intentional opening.
- **Local competition**: a focal subject can remain readable while its label,
  enclosing outlines, relationship shafts, endpoints, and a nearby scaffold
  converge into one conspicuous knot. Judge the combined neighborhood, not each
  part in isolation.
- **Peer contract**: the lowest annotation in a series can have visibly less
  boundary clearance than the top and middle peers, or one branch can attach at
  a different apparent boundary with no meaning. Inspect the complete peer set.

The corresponding arrangement can also be valid: a relationship may pass a
decorative boundary through a clearly visible opening; an annotation may extend
outside a data rectangle into open whitespace; dense parts may remain separated
by unmistakable foreground order. Decide from the rendered transition and
clearance, not the object category.

## Evidence requirements
Return at most one aggregated issue per slide. Describe every distinct confirmed
defect in that SVG region; do not stop after the first. For each defect state:

1. the intended roles and intended reading;
2. the exact visible parts and location involved;
3. the observed ownership, path, layering, competition, or peer-contract failure;
4. the competing or broken reading produced by the pixels;
5. why it remains material on the full slide; and
6. which peers and opposing extremes were inspected.

For a relationship defect, separately identify the apparent source, apparent
target, visible path, destination direction, and endpoint. Do not invent a
semantic relationship that the visible labels or structure do not support.

Use spatial metadata only as supporting measurement. Do not cite `svg_regions`
or a bounding-box intersection as proof of a visual defect.

## Severity
- critical: the visible structure is materially misleading or unusable
- major: an immediately visible failure impedes interpretation or looks clearly broken
- minor: the scene is understandable but has a specific, perceptible craft inconsistency

## Fix requirements
Describe the required perceptual outcome and protected invariants, not a literal
coordinate recipe or preferred SVG technique.

1. Name the roles that must become distinguishable and the intended ownership or
   relationship that must become unambiguous.
2. Preserve all visible text, data encoding, graph topology, reading order, and
   unrelated regions unless another issue explicitly authorizes a change.
3. Request the smallest local change that restores adequate accommodation, a
   clear relationship corridor, legal layering, lower local competition, and a
   consistent peer contract. Geometry, routing, layering, masking, or restrained
   styling are possible means, not a mandatory sequence.
4. For a persistent failure, require a meaningfully different visual strategy
   instead of another small offset in the same failed strategy.
5. Define success as a fresh rendered result in which the intended reading is
   the single clear reading at full-slide scale, the targeted local ambiguity is
   reduced, and protected information and non-target regions do not regress.

SVG defects are local repair targets; do not recommend regenerating the whole
slide when the visible failure can be corrected locally.

## Mandatory decision trace
Return a top-level `audit` object alongside `probe_id` and `issues`. This trace is
required even when `issues` is empty. It is compact execution evidence, not a
second issue list.

```json
{
  "audit": {
    "regions": [
      {
        "region": "visible location or role",
        "role_inventory": ["subject", "owner", "relation", "label", "decoration"],
        "nested_boundaries": [{"subject": "...", "contours": [{"description": "...", "role": "content_owner|attachment_boundary|support|decoration"}], "attachment_boundary": "one contour only", "ambiguous": false}],
        "narrowest_clearance": {"location": "...", "observation": "...", "material": false},
        "highest_role_convergence": {"location": "...", "roles": ["..."], "observation": "...", "material": false},
        "continuity_crossings": [{"location": "...", "transition": "terminate|foreground|background|opening|unclear", "material": false}],
        "attachment_zones": [{"location": "...", "target_boundary": "...", "intermediate_contours": ["..."], "separation_corridor": "clear|fused", "material": false}],
        "peer_extremes_checked": ["..."]
      }
    ],
    "full_slide_conclusion": "..."
  },
  "issues": []
}
```

Include one region entry for every inspected SVG region. Name the actual
narrowest-clearance area and highest-convergence area; do not write `none` or
`all clear` without identifying what was examined. For every subject with more
than one visible contour, fill `nested_boundaries`, name each contour separately,
and choose exactly one attachment boundary; a combined value such as
`inner/outer boundary` is invalid. Enumerate every attachment
zone where a relation reaches a subject or crosses an enclosing contour, not
only the most crowded example. Every candidate marked
`material: true` must appear in the aggregated issue. An empty `issues` array is
valid only when all named candidates were falsified at full-slide scale.
