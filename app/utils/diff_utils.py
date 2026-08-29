"""Diff utilities for comparing states across turns."""

from typing import Any

from .issue_identity import issues_share_target


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
    """Compare issue lists with one-to-one semantic target matching."""
    resolved = []
    persisting = []
    new = []

    unmatched_new = set(range(len(new_issues)))
    for old_index, old_model in enumerate(old_issues):
        old_payload = old_issues[old_index]
        already_resolved = (
            old_payload.get("resolved_at_turn") is not None
            or old_payload.get("status") == "resolved"
        )
        if already_resolved:
            continue

        exact = next(
            (index for index in unmatched_new
             if new_issues[index].get("issue_id") == old_model.get("issue_id")),
            None,
        )
        semantic = next(
            (index for index in unmatched_new
             if issues_share_target(old_model, new_issues[index])),
            None,
        )
        match = exact if exact is not None else semantic
        if match is None:
            resolved.append(old_payload)
            continue

        unmatched_new.remove(match)
        new_payload = new_issues[match]
        if (
            new_payload.get("status") == "resolved"
            or new_payload.get("resolved_at_turn") is not None
        ):
            resolved.append(old_payload)
        else:
            persisting.append(old_payload)

    for index in sorted(unmatched_new):
        payload = new_issues[index]
        if payload.get("status") not in {"resolved", "wont_fix", "deferred"}:
            new.append(payload)

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
