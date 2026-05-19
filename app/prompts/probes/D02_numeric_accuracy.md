# D02: Numeric Accuracy — numeric_error

## Focus
All numbers/percentages/years/deltas/results correct.

## Pass if
1. Quoted figures match source
2. Derived numbers computed correctly
3. Units/denominators/directions preserved
4. Rounding doesn't change interpretation

## Fail if
1. Number copied incorrectly
2. Percentage/delta/trend miscomputed
3. Units/dates/denominators missing/wrong changing interpretation
4. Rounding distorts result

## Do not flag
- Harmless rounding preserving same decision-relevant meaning
- Approximate values preserving order of magnitude and trend (e.g., ~90% when source says 89.7%)

## Severity
- critical/major/minor

## Boundary — use another probe instead
- If number is fabricated/invented → E02

## Evidence requirements
- Exact numeric value in deck
- Correct source value
- Why difference matters
