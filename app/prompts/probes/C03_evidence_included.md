# C03: Evidence Included — missing_evidence

## Focus
Critical evidence/examples/results/caveats included to support key messages.

## Pass if
1. Major claims accompanied by enough evidence
2. Critical examples/data/results present
3. Relevant caveats appear when omission would mislead
4. Evidence not replaced by pure assertion

## Fail if
1. Important claims without necessary evidence
2. Required result/example/limitation absent weakening deck
3. Outcomes without interpretation context
4. Presentation depends on evidence audience never sees

## Do not flag
- Omission of minor supporting detail not materially changing understanding
- Evidence, examples, definitions, or caveats already presented on another
  clearly related slide in `deck_context`; a deck does not need to repeat the
  same support on every slide that mentions the topic
- A source fact merely because it is relevant to the slide topic. Report only
  when the slide's actual claim depends on that fact and the deck lacks it
- A missing local footnote when an earlier qualification slide already makes
  the limitation clear and the current slide is not materially misleading

## Scope discipline
- Check the full `deck_context` before declaring evidence missing
- Ask whether adding the proposed text would change a normal audience member's
  understanding or decision. If it would only make the slide more exhaustive,
  return PASS
- Prefer one dedicated evidence slide over duplicating evidence across several
  already readable slides

## Before reporting
- Verify content exists in source materials

## Severity
- critical/major/minor

## Boundary — use another probe instead
- If evidence is present but misrepresented → D-series probes

## Evidence requirements
- Claim-to-evidence pairs
- Source pack evidence that should have appeared
