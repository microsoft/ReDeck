# B13: Spatial Coherence — alignment_inconsistency

## Focus
Evaluate alignment, spacing regularity, and spatial grouping — the three dimensions of spatial coherence on a slide.

## Core principle
The audience should never wonder "why is this element here?" — spatial placement should feel intentional and logical.

---

## Dimension 1: Alignment

### Pass if
1. Same-role elements share an alignment edge (e.g., all card titles left-aligned)
2. Hierarchical indentation is consistent

### Fail if
1. Near-miss alignment — elements almost aligned but visibly off
2. Inconsistent alignment strategy within a group (some left-aligned, some centered)
3. Title-body misalignment
4. Column bottom-edge mismatch

### Do not flag
1. Different logical levels using different alignment (title centered, body left-aligned)
2. Single element positioned at a corner
3. Deliberate indentation for hierarchy

---

## Dimension 2: Spacing Regularity

### Pass if
1. Repeating series have visually equal spacing between items
2. Symmetric side margins are consistent

### Fail if
1. Uneven spacing in a repeating series
2. Asymmetric margins without clear purpose
3. Crowding in one area next to whitespace in another
4. Column rhythm imbalance

### Do not flag
1. Different spacing between different sections (hierarchy signal)
2. Minor ±15% gap variation in repeating elements

---

## Dimension 3: Spatial Grouping

### Pass if
1. Related content is spatially clustered
2. Group boundaries are perceptible (via spacing, lines, or containers)

### Fail if
1. Orphaned element — visually disconnected from its logical group
2. False grouping — unrelated elements appear grouped by proximity
3. No perceptible grouping when natural groups exist in the content

### Do not flag
1. Single-column bullet list (inherently grouped)
2. Full-width table or chart

---

## Severity
- critical: multiple dimensions fail — slide looks chaotic
- major: one dimension clearly fails — noticeable spatial problem
- minor: subtle design-conscious catch in one dimension

## Boundary — use another probe instead
- Content squeezed into corner → B09
- Elements overlapping → B03
- Bullet list used where comparison table needed → B02
- Mixed fonts within text → B01

## Evidence requirements
Identify which dimension(s) fail, cite the specific elements and their positions, and describe the spatial problem (misalignment amount, spacing irregularity, grouping confusion).
