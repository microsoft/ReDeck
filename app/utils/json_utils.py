"""JSON parsing utilities shared across the codebase."""

import re


def strip_code_fences(text: str) -> str:
    """Extract JSON content from markdown code fences.

    Handles these cases correctly:
    - Text before the code fence (e.g. "Here is the result:\\n```json\\n...")
    - Multiple code blocks (extracts the first one)
    - No code fences (returns text as-is)
    - Fences with or without language tag (```json, ```, etc.)

    Returns the extracted content or the original text if no fences found.
    """
    text = text.strip()

    # Try to extract content between first pair of code fences
    match = re.search(r'```(?:json|JSON)?\s*\n(.*?)```', text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # No fences found — return as-is
    return text
