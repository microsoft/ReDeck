# B09: Density Imbalance — density_imbalance

## Focus
Evaluate whether content density is appropriate for the slide's purpose — not too crowded, not too sparse, and evenly distributed.

## MUST specify sub_type
Every B09 issue MUST include one of: `content_overflow` | `underutilized_space` | `uneven_distribution`

## Core principle
Density should match the slide's purpose — a data slide can be denser than a section divider, but no slide should feel chaotic or abandoned.

## Pass if
1. Density matches the slide's purpose and audience
2. White space aids reading and visual breathing room
3. Slide is not simultaneously crowded AND under-organized
4. Sparse slides are intentionally sparse (dividers, quotes, transitions)

## Fail if — content_overflow
1. Slide is packed so densely that hierarchy breaks down
2. Visually cramped with insufficient spacing between elements
3. Viewer would struggle to parse content at normal viewing distance

## Fail if — underutilized_space
1. Large empty areas alongside sparse content
2. Text is minimal, elements are small — slide looks unfinished
3. Slide could benefit from larger elements or more content

## Fail if — uneven_distribution
1. Content clustered in one region with large empty areas elsewhere
2. Whitespace appears accidental rather than intentional
3. Spatial arrangement shows no intentional pattern

## Do not flag
1. Sparse divider, quote, or transition slides
2. 40–80% coverage that is well-organized and well-distributed
3. Title or closing slides
4. Slides with metric + table/chart combo covering 65–80%
5. Chart + cards on different sides with minor corner dead zones (≤25%)
6. Slides where content is well-distributed with no large empty zones
7. Moderate white space between logical groups
8. Density variation across slides due to varying content amounts

## IMPORTANT
- Having a chart or table does NOT exempt a slide from whitespace checks
- If the slide already has B03 (overlap) or B04 (text overflow), do NOT also flag B09

## Severity
- critical: slide is completely chaotic or essentially empty when it shouldn't be
- major: clear density problem affecting comprehension
- minor: slight density issue noticeable but not harmful

## Boundary — use another probe instead
- Content squeezed into wrong layout → B02
- Overlap between elements → B03
- Text overflow/clipping → B04
- Text-visual balance → B06

## Evidence requirements
Specify the sub_type. Describe the content distribution, estimate coverage percentage, and explain why the density is inappropriate for the slide's purpose.
