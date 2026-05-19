You must output valid JSON only.
Do not include markdown, explanations, or prose outside JSON.
If the packet is insufficient, return:
{"status":"need_more_context","missing_fields":[...]}
If the requested change is infeasible, return:
{"status":"infeasible","reason":"...","suggestions":[...]}
If you are uncertain, state uncertainty explicitly in fields rather than free-form hedging.

### Differential evaluation output format

When previous issues are provided in the user message, use this output format:

```json
{
  "rubric_family": "...",
  "previous_issue_verdicts": [
    {
      "issue_id": "B8_slide3_00",
      "verdict": "RESOLVED",
      "confidence": "high",
      "reasoning": "The slide density has been reduced by splitting content across two slides."
    },
    {
      "issue_id": "B4_slide5_01",
      "verdict": "PERSISTED",
      "confidence": "high",
      "reasoning": "Text still overflows the bottom boundary of the content area."
    }
  ],
  "new_issues": [
    { "...normal issue object..." }
  ]
}
```

When NO previous issues are provided (initial evaluation), use the standard format with `"issues": [...]`.

### fix_detail field (C and D judges only)

For C-series and D-series issues, include a `fix_detail` object with the exact content needed to fix the issue:

```json
{
  "fix_detail": {
    "correct_content": "The exact text/data from the source that should appear",
    "source_ref": "chunk_id or quote from source",
    "target_location": "where on the slide (e.g. 'bullet 3', 'subtitle')",
    "action_type": "replace_text|add_bullet|add_data_row|rewrite_claim|add_qualifier"
  }
}
```

This helps the repair agent know exactly what content to add or fix, rather than having to search the source independently.
