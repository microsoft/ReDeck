# B15: Container Contract Breach — container_contract_breach

## Focus
Evaluate whether content fits within its container boundaries — cards, panels, table cells, and other bounded regions.

## Core principle
Containers create a visual contract — content should respect their boundaries, and containers should be appropriately sized for their content.

## Pass if
1. Text fits within cards, panels, and table cells
2. Containers are appropriately sized for their content

## Fail if
1. Content extends beyond container borders
2. Container is vastly oversized for its content (feels empty)
3. Table cell content overflows or is truncated

## Severity
- critical: overflow makes content unreadable
- major: clear visual break between content and container
- minor: slight mismatch between content and container size

## Boundary — use another probe instead
- Text clipped at slide edges (no container) → B04
- Elements overlapping → B03

## Evidence requirements
Identify the container (card, panel, table cell), describe the breach (overflow, truncation, or oversizing), and note the impact on readability.
