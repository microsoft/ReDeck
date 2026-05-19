# B04: Text Overflow — text_overflow

## Focus
Evaluate whether all text is fully visible with no clipping, truncation, or overflow beyond containers.

## Core principle
Every character of text content must be visible to the audience — hidden text is lost communication.

## Pass if
1. All text is visible within its containers
2. Line spacing allows comfortable reading

## Fail if
1. Text is cut off, clipped, or extends beyond its container
2. Text is so dense that lines merge together

## Do not flag
1. Slight text proximity to edges when the text is fully visible

## Severity
- critical: text is literally hidden — content is lost and cannot be read
- major: text visibly extends outside its container or is truncated
- minor: text is cramped but fully visible

## Common patterns to check
1. Figure captions cut off at bottom
2. Equation closing parenthesis missing (clipped)
3. Chart legend truncated
4. Table rows disappearing below container
5. Image title clipped at edges
6. Equation clipped at container edge

## Special detection
- Duplicate element: same caption appearing twice on a slide → B04 major

## Boundary — use another probe instead
- Content inside container cards/panels → B15
- Density/crowding issues → B09

## Evidence requirements
Identify the specific text that is cut off, the container it belongs to, and how much content is lost. Quote the visible portion and indicate what is missing if determinable.
