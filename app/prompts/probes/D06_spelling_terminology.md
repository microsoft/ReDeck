# D06: Spelling, Grammar & Language Consistency — spelling_error, grammar_error, language_inconsistency

## Focus
Are text elements free of spelling errors, grammatical mistakes, and unintended language mixing?

## Pass if — Spelling
1. Technical terms and proper nouns are spelled correctly
2. No garbled PDF-extraction artifacts remain
3. No prominent typos on visible slide content
4. Acronyms are used consistently throughout the deck

## Pass if — Grammar
1. Sentences are grammatically correct
2. Bullet lists use parallel construction
3. No fragments that impair comprehension

## Pass if — Language Consistency
1. A single language is used consistently throughout
2. No unintended mixing of languages
3. No untranslated labels, axes, or legends

## Fail if
1. A technical term or proper noun is misspelled
2. Garbled PDF artifacts appear on a slide
3. A prominent typo is visible to the audience
4. Acronym usage is inconsistent (e.g., alternating between spelled-out and abbreviated forms without pattern)
5. A sentence is ungrammatical in a way that impairs comprehension
6. Bullet items break parallel construction
7. Languages are mixed unintentionally within the deck
8. Labels or legends are left untranslated

## Do not flag
- Minor capitalization variation (e.g., "multi-head" vs "Multi-Head")
- Acceptable abbreviations and standard acronyms
- Bullet-point shorthand that omits articles (a, the)
- Technical jargon appropriate to the field
- Standard technical terms (e.g., English ML terms) appearing in non-English decks

## Severity
- critical when garbled artifacts or errors make content unintelligible
- major when a prominent term is misspelled or grammar impairs comprehension
- minor for isolated typos or slight inconsistencies

## Boundary — use another probe instead
- If the issue is inconsistent visual formatting (fonts, alignment) → B-series probes
- If the issue is factual inaccuracy in terminology → C-series probes

## Evidence requirements
- Cite the exact text containing the error
- Provide the corrected form
- Note the slide number where the error appears
