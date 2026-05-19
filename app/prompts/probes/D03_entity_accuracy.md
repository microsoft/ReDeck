# D03: Entity Accuracy — entity_error

## Focus
Named entities and technical terms used correctly/consistently.

## Pass if
1. Model/product/method/organization names accurate
2. Terms used in proper sense
3. No confusion from near-synonyms
4. Terminology consistent

## Fail if
1. Wrong entity/method named
2. Terminology misuse changes meaning
3. Two distinct entities conflated
4. Simplified label creates ambiguity/error

## Do not flag
- Audience-friendly simplification remaining accurate/unambiguous

## Severity
- critical/major/minor

## Boundary — use another probe instead
- If entity is missing entirely → C04

## Evidence requirements
- Incorrect/ambiguous term
- Correct source wording
- Why difference substantive
