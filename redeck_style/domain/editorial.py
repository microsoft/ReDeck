"""Audience-facing wording policy, separate from factual source evidence."""

SYNTHETIC_SOURCE_FORMS = (
    "Source: typed evidence architecture",
    "Source: Slide {slide_id} typed evidence architecture",
    "Source: supplied paper evidence architecture and excerpts for slide {slide_id}",
    "Source: paper evidence architecture and excerpts for slide {slide_id}",
)


ART_DIRECTION = """ART DIRECTION:
Build one continuous editorial composition, not a diagram of the brief or a collection of UI modules.
Optional source details are a reservoir, not mandatory copy; functional negative space is part of the hierarchy.
Use proximity, alignment and meaningful linework before containers. Keep at least one substantial evidence sequence directly on the canvas.
The kernel's optional data-ink operations serve a named datum or relationship; there is no minimum number.
When `required` is true in the visual-encoding plan, realize its primary mark or an allowed alternative using native SVG/HTML/CSS.
For a source-figure mark, embed the supplied image unchanged instead of redrawing its contents.
Use supplied exact values and relations; the visual should replace redundant prose, not duplicate it.
Treat the kernel title size as a hard ceiling for the main heading; body copy should normally be 15–18px and explanatory annotations at least 12px.
If space is insufficient, simplify grouping or omit optional detail; do not shrink the whole composition.
For grouping, one dominant filled evidence field is the normal maximum, containing a short claim or metric—never a paragraph-length thesis.
Keep the page canvas flat; local tint belongs to evidence. Vary silhouettes across the group while retaining one design language."""


EDITORIAL_COPY_POLICY = """VISIBLE COPY BOUNDARY:
Planning keys, prompt headings, CSS instructions and audit metadata are instructions to the implementer, not slide copy.
Never display pipeline labels such as 'typed evidence architecture', 'SOURCE-GROUNDED DETAILS USED HERE',
'optional source-detail reservoir', 'must_cover_subset', 'bounded creative brief', or 'object-fit: contain'.
Use a concise audience-facing label such as 'Evidence', 'Context' or 'Limitations' only when the content warrants it.
A source footer may name only bibliographic facts or figure/table identifiers explicitly supplied in the evidence.
The blueprint, typed architecture, assigned asset, local file path and CSS preservation method are not publications or citations.
If no usable attribution is supplied, omit an unsupported footer rather than inventing a source or saying no source exists.
Do not remove substantive qualifications, alter numeric facts or hide text to comply. If the subject itself discusses
these technical terms, retain the necessary quoted material and its supplied attribution.
Before returning, read the visible headings, annotations and footer as audience copy, not as implementation notes."""
