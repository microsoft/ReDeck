# A04: Title–Content Mismatch — title_content_alignment

## Focus
Do slide titles accurately summarize the content and takeaway of each slide?

## Pass if
1. Titles describe the real subject of the slide
2. Takeaway titles are supported by the evidence on the slide
3. Generic placeholder titles are limited to a small number of slides

## Fail if
1. A title promises one topic but the body presents another
2. A title states a conclusion not supported by the slide's evidence
3. Multiple slides use generic labels where specific titles are needed
4. Titles systematically mislead the reader about slide content

## Do not flag
- Short titles, as long as they are accurate

## Severity
- critical when titles actively mislead across multiple slides
- major when a key slide's title contradicts its content
- minor when a title is vague but not misleading

## Boundary — use another probe instead
- If the issue is that content importance is misallocated → A05 (misallocated_detail)
- If the slide is a pure placeholder with no body → A07 (placeholder_slide)

## Evidence requirements
- Cite mismatched title/body pairs
- Cite unsupported takeaway titles with the evidence actually present
