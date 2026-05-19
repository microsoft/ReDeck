"""Diff utilities for comparing states across turns."""

from typing import Any


def _issue_signature(issue: dict) -> tuple[str, frozenset[int]]:
    """Compute a stable signature for an issue: (issue_type, affected_slides).

    This avoids false "resolved + new" when the judge re-generates the same
    problem under a different issue_id (e.g. B9_slide2_01 → B9_slide2_00).
    """
    return (
        issue.get("issue_type", ""),
        frozenset(issue.get("affected_slides", [])),
    )


def diff_issue_lists(
    old_issues: list[dict],
    new_issues: list[dict],
) -> dict[str, list[dict]]:
    """Compare two issue lists and return categorized diffs.

    Matching uses (issue_type, affected_slides) signatures instead of
    issue_id strings.  This prevents phantom "resolved + new" churn when
    the judge assigns a different ID to the same underlying problem.

    An old issue is considered **resolved** only if no new issue shares
    the same (issue_type, slides) signature AND the old issue is marked
    with status == "resolved" or resolved_at_turn != None.

    Falls back to ID-based matching for issues whose signature appears
    multiple times (ambiguous).
    """
    # Build signature maps
    old_by_sig: dict[tuple, list[dict]] = {}
    for i in old_issues:
        sig = _issue_signature(i)
        old_by_sig.setdefault(sig, []).append(i)

    new_by_sig: dict[tuple, list[dict]] = {}
    for i in new_issues:
        sig = _issue_signature(i)
        new_by_sig.setdefault(sig, []).append(i)

    # Also keep ID-based sets for fallback
    old_ids = {i["issue_id"] for i in old_issues}
    new_ids = {i["issue_id"] for i in new_issues}

    resolved = []
    persisting = []
    new = []

    # Categorize old issues
    # Skip issues that were already resolved in a PRIOR turn – they are
    # not "newly resolved" in this diff and should not inflate the count.
    # Issues resolved in the CURRENT turn (present in new_issues with
    # status="resolved") ARE newly resolved and must be counted.
    new_by_id = {i["issue_id"]: i for i in new_issues}
    for i in old_issues:
        # Check if this issue appears in new_issues as resolved (current-turn resolution)
        new_version = new_by_id.get(i["issue_id"])
        current_turn_resolved = (
            new_version is not None
            and (new_version.get("status") == "resolved" or new_version.get("resolved_at_turn") is not None)
        )
        if current_turn_resolved:
            resolved.append(i)
            continue

        already_resolved = (
            i.get("resolved_at_turn") is not None
            or i.get("status") == "resolved"
        )
        if already_resolved:
            # Carry-over from prior turn: don't count as resolved *again*.
            continue

        sig = _issue_signature(i)
        if sig in new_by_sig:
            # Same type + slides exists in new → persisting (regardless of ID)
            persisting.append(i)
        elif i["issue_id"] not in new_ids:
            # No signature match AND no ID match → truly resolved
            resolved.append(i)
        else:
            persisting.append(i)

    # Categorize new issues
    matched_old_sigs = {_issue_signature(i) for i in old_issues}
    for i in new_issues:
        sig = _issue_signature(i)
        if sig not in matched_old_sigs and i["issue_id"] not in old_ids:
            new.append(i)
        # If sig matches an old issue, it's a continuation (not truly new)

    return {
        "resolved": resolved,
        "persisting": persisting,
        "new": new,
    }


def count_by_severity(issues: list[dict]) -> dict[str, int]:
    """Count issues by severity level."""
    counts: dict[str, int] = {"critical": 0, "major": 0, "minor": 0}
    for issue in issues:
        sev = issue.get("severity", "minor")
        counts[sev] = counts.get(sev, 0) + 1
    return counts
