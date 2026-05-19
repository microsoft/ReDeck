## Global Judgment Rules

### Pass threshold
Mark an item as pass only when:
1. the item's required condition is materially satisfied across the deck or across all relevant slides
2. no material counterexample was found
3. any local weakness is too small to change audience understanding, usability, or credibility

### Fail threshold
Mark an item as fail when any of the following is true:
1. there is at least one material counterexample on a relevant slide
2. the issue changes meaning, usability, readability, or audience trust in a meaningful way
3. the deck misses a requirement that the item is explicitly meant to protect

Do not require multiple broken slides before failing. A single serious violation is enough.

### Severity assignment
- critical: hard constraint break, serious factual distortion, severe unreadability, or a defect that makes the deck misleading or unusable
- major: clear quality failure that materially weakens deck integrity, decision utility, or audience comprehension
- minor: local weakness that is real and should be logged, but has limited deck-level impact

### Evidence rules
Every judgment must cite:
1. affected slide numbers
2. concrete observed evidence from the artifact
3. source evidence when the item depends on source grounding
4. why the evidence is sufficient for this specific rubric item

Avoid generic statements without a concrete mechanism. Always specify exactly what is wrong and where.

### Differential evaluation (repair turns)

When the user message includes a "Previous Issues" section, you are in **differential evaluation mode**. You have two responsibilities:

1. **Triage each previous issue**: For every listed previous issue, determine if it is RESOLVED (problem no longer exists), PERSISTED (still present), or WORSENED (got worse). Return these in `previous_issue_verdicts`.

2. **Report genuinely new issues only**: Only report issues in `new_issues` that are truly NEW problems not described in the previous issues list. Do NOT re-report a persisting issue as a new issue — that would be double-counting.

**Key rules for differential mode:**
- If a previous issue described "density_imbalance on slide 3" and slide 3 still looks dense, verdict = PERSISTED. Do NOT also create a new density_imbalance issue for slide 3.
- If you find a problem that is essentially the same as a previous issue but described differently (e.g., same slide, same area, similar complaint), verdict = PERSISTED for the old issue. Do NOT create a new issue.
- Only create a new issue if the problem genuinely did not exist before the repair.

### Issue Independence Principle
Each previous issue must be judged on its OWN original terms:
- If issue X (text too dense) is resolved but a new problem Y (text too sparse) appeared as a side effect, verdict for X = RESOLVED. Report Y as a new issue.
- Do NOT keep X open because Y appeared. They are different problems requiring different fixes.
- The question for each issue is: "Does the SPECIFIC problem described in this issue still exist?" — not "Is the slide perfect now?"

### PERSISTED Issues Must Be Updated
When an issue verdict is PERSISTED or WORSENED, you MUST provide:
- `updated_description`: Describe the problem AS IT EXISTS NOW based on the current screenshot, not the old description
- `updated_planned_fix`: Write a NEW fix plan appropriate for the current state of the slide
This prevents stale descriptions from earlier turns driving increasingly aggressive repairs that destroy content.

### Embedded Image Exemption
Issues that exist INSIDE an embedded PNG, screenshot, or figure image (e.g., blurry text inside a screenshot, overlapping numbers in a chart image, low resolution within a pasted figure) are NOT valid issues. The system cannot modify the internal content of embedded images. Only report issues with the PLACEMENT, SIZE, or VISIBILITY of the image element itself, not its internal content. This includes matplotlib-generated chart images — overlapping data labels or truncated text inside a chart PNG are rendering artifacts, not slide issues.
