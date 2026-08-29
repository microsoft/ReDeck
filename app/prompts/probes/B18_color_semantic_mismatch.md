# B18: Color Semantic Mismatch - color_semantic_mismatch

## Focus
Evaluate whether color choices or color mappings imply meanings that conflict
with the content, hierarchy, or comparison being shown.

## Core principle
Color is a semantic channel. Hue, saturation, warmth/coolness, and accent weight
can imply state, importance, risk, success, category, ordering, or emphasis. A
color mismatch occurs when that implied meaning is wrong or inconsistent.

## Evaluation calibration
Judge color only when it attaches to a semantic role, category, state, order, or
emphasis. Use evidence such as repeated labels, legends, category names, state
words, result polarity, accent strength, and whether the same role keeps the
same color mapping.

## Pass if
1. Colors used for semantic roles, categories, states, or emphasis are consistent
   within the slide and across nearby related slides when the same meaning recurs.
2. Neutral peer items use color treatment with comparable hue role, saturation,
   and accent weight unless labels define a semantic difference.
3. Value-laden colors, such as danger/success/warning/accent colors, are used
   only when the content supports that meaning.
4. Ordered or divergent palettes match the direction and meaning of the data.

## Fail if
1. The same semantic role changes hue or accent treatment within a slide or
   related slide sequence, making categories, states, or importance ambiguous.
2. The same color is used for different meanings in the same slide or nearby
   related slides, causing the viewer to infer a false relationship.
3. Neutral peer items use value-laden colors, such as success, danger, warning,
   or strong accent colors, implying good/bad/risk/priority where the content is
   merely parallel.
4. A strong accent falsely highlights a neutral, tentative, non-conclusive, or
   low-priority number or claim as if it were the main result.
5. Same-type containers, cards, process steps, or result blocks use inconsistent
   hero colors that imply different state, importance, or category without a
   content reason.
6. A categorical, ordered, or divergent palette maps colors to categories or
   values in a way that reverses, confuses, or obscures the intended meaning.
7. Cross-slide color semantics change for a recurring category, method,
   condition, or state while labels/legends do not define a new mapping, causing
   the recurring item to appear to mean something different.

## Do not flag
1. Brand or theme colors applied uniformly without implying different states or
   category meanings.
2. Red/green, warm/cool, sequential, or divergent palettes used when the content
   genuinely represents bad/good, loss/gain, low/high, before/after, or opposing
   states.
3. Decorative color variation that does not attach to a semantic role, category,
   state, or emphasis hierarchy.
4. Low contrast or unreadable text caused by color choice; use B05.
5. General cross-slide style drift where color is one part of broader visual
   inconsistency; use B01.

## Severity
- critical: color semantics reverse or materially falsify the meaning of a key
  result, state, category, or comparison.
- major: color mapping or emphasis misleads the viewer about importance,
  category, state, or value judgment.
- minor: color semantics are inconsistent or noisy but the content meaning is
  still recoverable.

## Boundary - use another probe instead
- Overall cross-slide visual consistency or theme drift -> B01
- Foreground/background readability or contrast -> B05
- Wrong chart encoding or palette form for data relationship -> B07
- Unsupported or incorrect claim/value regardless of color -> D-series

## Evidence requirements
Identify the colored elements, the colors or palette roles, the content meaning
they represent, the misleading implied meaning, and the intended semantic color
mapping. The planned fix must specify whether to normalize hues, swap semantic
colors, neutralize peers, reduce accent strength, or define a consistent palette
mapping.
