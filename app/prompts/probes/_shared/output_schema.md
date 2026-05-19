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
- If no issues found, return: `{"probe_id": "<id>", "issues": []}`
- Only report issues matching THIS probe's rubric_id and issue_type.
- `sub_type` field is REQUIRED for B09 density_imbalance: `"content_overflow"|"underutilized_space"|"uneven_distribution"`. Omit for other issue types.

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
    {"issue_id": "...", "verdict": "RESOLVED|PERSISTED|WORSENED", "confidence": "high|medium|low", "reasoning": "..."}
  ],
  "new_issues": [...]
}
```
