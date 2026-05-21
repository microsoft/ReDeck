# A07: Placeholder Slide — placeholder_slide

## Focus
Does every slide carry substantive content that justifies its place in the deck?

## Pass if
1. Every slide has meaningful content beyond its title
2. No slide exists solely as a topic label
3. Section-divider slides are limited to one per section and include framing text
4. Every slide justifies its share of the page budget

## Fail if
1. A slide has only a title with no body, evidence, or visual
2. Multiple structural placeholders appear throughout the deck
3. A slide is a near-duplicate of another slide
4. Page budget is wasted on purely cosmetic slides

## Do not flag
- Title slide 1 with paper metadata (authors, affiliations, date)
- A single section-divider slide that includes meaningful transition text
- A Talk Roadmap, Outline, or Agenda slide (standard practice for structured presentations)

## Severity
- critical when multiple slides are empty placeholders wasting significant budget
- major when a single slide is clearly a placeholder in a key position
- minor when a slide is thin but not entirely empty

## Boundary — use another probe instead
- If the slide has content but the title mismatches → A04 (title_content_mismatch)
- If the slide has content but it duplicates another slide's argument → A05 (misallocated_detail)

## Evidence requirements
- Cite the placeholder content (or lack thereof)
- State what should have been on the slide
- Note the impact on overall page budget
