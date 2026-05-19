# B11: Text Clarity — typography_error

## Focus
Evaluate whether all text is clear, with no missing, garbled, or incorrectly rendered characters.

## Core principle
Every character must render correctly — encoding failures and rendering artifacts destroy credibility.

## Pass if
1. All characters are valid and correctly rendered
2. No words are broken mid-word inappropriately
3. Special characters (math symbols, accents, etc.) render correctly
4. No PDF extraction artifacts visible

## Fail if
1. Garbled or corrupted characters visible
2. Words broken mid-word (not at syllable boundaries)
3. Special characters appear as empty boxes or placeholder glyphs
4. Encoding artifacts visible (mojibake, escape sequences)
5. Rendering artifacts: misplaced elements, CSS collapse, HTML tags visible in output
6. Container rendering defects: missing borders, overlapping labels, half-clipped characters, off-center elements

## Do not flag
1. Footnote or source attribution at small size if the content is not essential

## Font size check
- min_font_pt < 10pt → B11 major

## Severity
- critical: primary text garbled or unreadable
- major: multiple rendering errors or font size below 10pt
- minor: isolated character rendering issue in secondary text

## Boundary — use another probe instead
- Formatting inconsistency within text blocks → B12
- Text contrast issues → B05

## Evidence requirements
Quote the affected text, describe the rendering error (garbled characters, broken words, artifacts), and note the element type (title, body, label, etc.).
