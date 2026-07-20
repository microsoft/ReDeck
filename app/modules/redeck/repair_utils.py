"""Shared helpers for slide repair modules.

Extracted from the legacy multi_action.py to support agent_repair.py.
"""

import json
import re
import logging

from ...schemas.issue_types import CONTENT_ACCURACY_TYPES as CONTENT_ACCURACY_ISSUE_TYPES

_logger = logging.getLogger(__name__)


def _extract_json(response: str) -> dict | None:
    """Extract JSON from LLM response (code blocks or direct)."""
    # Try code fences
    json_blocks = re.findall(
        r'```(?:json)?\s*\n(.*?)```', response, re.DOTALL,
    )
    for block in json_blocks:
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            pass

    # Try direct JSON
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass

    # Try line-by-line: handles multi-JSON-object responses where each
    # line is a separate valid JSON object (plan + apply_edits + verify).
    # This must come BEFORE brace matching because CSS content inside
    # JSON string values contains { } that confuse naive depth counting.
    for line in response.strip().split('\n'):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                data = json.loads(line)
                if isinstance(data, dict) and "tool" in data:
                    return data
            except json.JSONDecodeError:
                pass

    # Try extracting { ... } with brace matching (fallback for responses
    # with JSON embedded in prose text)
    depth = 0
    start = None
    for i, ch in enumerate(response):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(response[start:i + 1])
                except json.JSONDecodeError:
                    start = None

    return None


def _has_extra_json(response: str) -> bool:
    """Check whether the response contains more than one top-level JSON object.

    Returns True if multiple JSON objects are detected, meaning the LLM
    tried to output multiple tool calls in a single message.
    """
    # Fast path: line-by-line check (handles the common multi-line pattern)
    json_count = 0
    for line in response.strip().split('\n'):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                json.loads(line)
                json_count += 1
                if json_count >= 2:
                    return True
            except json.JSONDecodeError:
                pass
    # Fallback: brace matching for JSON embedded in prose
    count = 0
    depth = 0
    start = None
    for i, ch in enumerate(response):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    json.loads(response[start:i + 1])
                    count += 1
                    if count >= 2:
                        return True
                except json.JSONDecodeError:
                    pass
                start = None
    return False


def _extract_all_json(response: str) -> list[dict]:
    """Extract ALL valid top-level JSON objects from response.

    Returns a list of parsed dicts, each with a "tool" field.
    Used for sequential execution of multi-JSON tool calls.
    """
    results = []
    # Fast path: line-by-line extraction (common multi-line pattern)
    for line in response.strip().split('\n'):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                data = json.loads(line)
                if isinstance(data, dict) and "tool" in data:
                    results.append(data)
            except json.JSONDecodeError:
                pass
    if results:
        return results
    # Fallback: brace matching for JSON embedded in prose
    depth = 0
    start = None
    for i, ch in enumerate(response):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    data = json.loads(response[start:i + 1])
                    if isinstance(data, dict) and "tool" in data:
                        results.append(data)
                except json.JSONDecodeError:
                    pass
                start = None
    return results


def _apply_edits(code: str, edits: list[dict]) -> str:
    """Apply search/replace edits sequentially.

    Replaces ALL occurrences of each search string (not just the first).
    Returns the modified code.
    """
    modified = code
    for edit in edits:
        search = edit.get("search", "")
        replace = edit.get("replace", "")
        insert_after = edit.get("insert_after", "")

        if insert_after and not search:
            # Insertion mode
            idx = modified.find(insert_after)
            if idx >= 0:
                line_end = modified.find("\n", idx + len(insert_after))
                if line_end >= 0:
                    modified = (
                        modified[:line_end]
                        + "\n" + replace
                        + modified[line_end:]
                    )
        elif search:
            # Replacement mode — replace ALL occurrences
            if search in modified:
                modified = modified.replace(search, replace)

    return modified


def _parse_viz_data(response: str) -> dict | None:
    """Parse viz_data JSON from response."""
    data = _extract_json(response)
    if not data:
        return None
    if (isinstance(data.get("categories"), list)
            and isinstance(data.get("series"), list)
            and len(data["categories"]) > 0
            and len(data["series"]) > 0):
        return data
    return None
