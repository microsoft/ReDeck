# B06: Text-Visual Imbalance - text_visual_imbalance

## Focus
Evaluate whether the slide chooses an appropriate communication mode: prose,
structured text, visual explanation, source figure, table, chart, diagram, or a
deliberate combination.

## Core principle
The slide should not force text to do a visual job, or force an unexplained
visual to do a narrative job. Text and visuals should each have a clear role in
the message.

## Evaluation calibration
Judge the communication role, not decoration quality. Use evidence such as the
slide title/claim, available source figures or tables, named relationships in
the text, whether a visual has labels/caption/takeaway, and whether a large
visual region changes what the viewer can understand.

## Pass if
1. A visual-heavy slide includes caption, annotation, labels, or takeaway text
   that connects the visual to the slide claim.
2. A text-heavy slide uses structure, hierarchy, grouping, or simple visual
   organization when that is enough for the content.
3. Available source figures, tables, charts, or diagrams are used when the slide
   title/claim depends on their evidence or structure.
4. Decorative or atmospheric visuals are smaller, lighter, more peripheral, or
   otherwise lower in hierarchy than the actual content.

## Fail if
1. The slide is essentially a single image, screenshot, or figure without
   caption, annotation, title linkage, or takeaway text that states why the
   visual supports the claim.
2. Dense prose or bullets are used for content that naturally requires visual
   structure, such as process steps, model architecture, causal flow, grouped
   factors, or spatial relationships.
3. Relevant source figures, tables, charts, or diagrams are available and central
   to the slide's stated point, but the slide replaces them with less effective
   prose.
4. Decorative imagery, background photography, or large icons occupy one of the
   main content regions while adding no label, evidence, relationship, or
   explanatory role, causing meaningful text or data to be reduced.
5. A slide uses a visual as the main communication mode, but missing labels,
   callouts, legend, or explanatory text prevent the visual from being read as
   evidence for the title/claim.
6. The slide uses prose as the main communication mode even though the same
   visible content already contains named categories, relationships, stages, or
   evidence that should be organized visually for scanning.

## Do not flag
1. Academic, policy, legal, or conceptual slides where structured prose is the
   appropriate communication mode and no central visual is available.
2. Text with clear visual organization, such as tables, metric cards, callout
   groups, timelines, or labeled panels.
3. A slide only because it has many words; use B16 for generic unstructured text
   walls and B09 for density/crowding.
4. A slide only because it uses a raw academic figure; use B17 when the figure
   itself needs slide adaptation.
5. A quantitative results slide that needs a chart or table; use B10.
6. A visual form that exists but uses the wrong chart/diagram type; use B07.

## Severity
- critical: the chosen communication mode prevents the main point from being
  understood.
- major: the slide needs a specific missing text or visual role for
  comprehension or source-grounded explanation.
- minor: one text/visual role is under-specified, but the slide remains readable
  and interpretable.

## Boundary - use another probe instead
- Numeric/result-heavy text should be visualized -> B10
- Generic unstructured text wall -> B16
- Raw paper figure needs adaptation -> B17
- Wrong chart, diagram, or table form -> B07
- Density, crowding, sparse canvas, or peer visual weight -> B09
- Irrelevant visual that is simply off-topic -> B08

## Evidence requirements
Describe the current communication mode, the content type, any available source
visuals that should have been used, and the specific missing role of text or
visual explanation. The planned fix must say what visual/text role to add,
remove, or restructure.
