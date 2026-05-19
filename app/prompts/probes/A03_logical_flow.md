# A03: Poor Flow — logical_flow

## Focus
Does the slide order create a coherent progression?

## Pass if
1. Adjacent slides are related chapters or have logical dependency
2. Section transitions are understandable without extra explanation
3. The ending follows naturally from the preceding content

## Fail if
1. A specific transition between two adjacent slides has no logical bridge

## Do not flag
- Intentional non-linear structure if the deck is still intelligible

## Severity
- critical when multiple transitions are broken and the deck feels random
- major when a key transition is missing and disrupts comprehension
- minor when a single transition is rough but recoverable

## Boundary — use another probe instead
- If the problem is that the opening lacks context → A02 (missing_context)
- If the problem is the overall thesis is unclear → A01 (weak_thesis)

## Actionability constraint
Only report when you can identify a SPECIFIC transition between two adjacent slides that breaks flow. Name both slides and explain the missing bridge.

## Evidence requirements
- Cite specific slide-to-slide transitions
- Describe the missing bridge content that would restore flow
