## Output Format

Return valid JSON only. No markdown, explanations, or prose outside JSON.

```json
{
  "probe_id": "<probe_id>",
  "issues": [
    {
      "rubric_id": "<rubric_id>",
      "issue_type": "<issue_type>",
      "severity": "critical|major|minor",
      "confidence": "high|medium|low",
      "affected_slides": [int],
      "evidence": "concrete observed evidence from rendered slide or source comparison",
      "why_this_fails": "specific failure mechanism — what goes wrong and why it matters",
      "fixability": "easy_local_patch|medium|hard",
      "planned_fix": "actionable fix instruction (see Fix Plan Quality Gate)",
      "fix_detail": {
        "correct_content": "exact fix content or target state",
        "source_ref": "source reference if applicable",
        "target_location": "which element on the slide to change",
        "action_type": "replace_text|restructure_layout|resize_element|remove_element|add_bullet|rewrite_claim"
      },
      "recommended_action": "KEEP|PATCH|REGEN",
      "action_rationale": "why this action type is appropriate"
    }
  ]
}
```

**Rules:**
- ONE issue PER slide. If slides 2, 4, 7 each have the same problem, output 3 separate issues.
- `fix_detail.target_location` is REQUIRED for every issue. Identify the stable
  semantic target using visible labels, object roles, or source/target labels;
  do not identify it only as an array position such as "the first issue".
- If no issues found, return: `{"probe_id": "<id>", "issues": []}`
- If the probe rubric requires an additional top-level audit or decision-trace
  field, include it alongside `probe_id` and `issues`; it does not replace the
  standard issue array.
- Only report issues matching THIS probe's rubric_id and issue_type.
- `sub_type` field is REQUIRED for B09 density_imbalance: `"sparse_content"|"cramped_content"|"element_undersized"|"column_height_mismatch"`. Omit for other issue types. Use `column_height_mismatch` for peer visual-weight contract failures, not only literal bottom-edge mismatch.

## Differential Evaluation (repair turns)

When the input includes a "Previous Issues" section, you are in differential mode:
1. For each previous issue of YOUR type: determine RESOLVED / PERSISTED / WORSENED
2. Report only genuinely NEW issues not described in previous issues
3. Do NOT re-report a persisting issue as new — that would be double-counting

Output format in differential mode:
```json
{
  "probe_id": "<id>",
  "previous_issue_verdicts": [
    {"issue_id": "...", "verdict": "RESOLVED|PERSISTED|WORSENED", "confidence": "high|medium|low", "reasoning": "...", "updated_planned_fix": "required for PERSISTED/WORSENED", "updated_correct_content": "refresh exact correction text when the semantic correction changes; otherwise omit"}
  ],
  "new_issues": [...]
}
```
