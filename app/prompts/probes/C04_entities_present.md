# C04: Entities Present — missing_entity

## Focus
Important entities/terms/years/metrics/figures present.

## Pass if
1. Key actors/methods/products/datasets/years/metrics named where needed
2. Important quantitative anchors included
3. Omitted details genuinely non-essential

## Fail if
1. Key entity/number/time marker missing weakening comprehension
2. Comparison/result described without defining metric
3. Essential specificity removed making claims unsupported
4. Terminology ambiguous from omitted names

## Do not flag
- Omission of secondary numbers when main point remains accurate
- An entity, metric, year, or quantitative anchor that already appears on a
  dedicated slide in `deck_context`; do not require it to be duplicated on
  every slide about the same business theme
- Additional source metrics that would make the scoped slide more exhaustive
  but would not materially change its claim or audience comprehension

## Scope discipline
- Search `deck_context` before declaring an entity absent
- Distinguish "missing from this slide" from "missing from the deck". Report
  the former only when the current claim becomes ambiguous or misleading
  without the entity immediately beside it
- Do not crowd a focused summary slide with metrics already explained in a
  later or earlier detail slide

## Flag when
- Missing entity important for audience understanding (key metrics, model names, dataset names, quantitative results)

## Severity
- critical/major/minor

## Boundary — use another probe instead
- If entity is present but wrong → D03

## Evidence requirements
- Missing terms/figures from source
- Claims whose meaning depends on missing specifics
