"""Stable semantic identity helpers for evaluator issues.

Issue array positions and free-form repair prose are not identities.  These
helpers prefer structured object references and target locations, while still
providing a conservative evidence fallback for older evaluator responses.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping

from ..schemas.issue import Issue


_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
_EPHEMERAL_OBJECT_REF_RE = re.compile(
    r"^(?:blk|block|el|element|obj|object|shape)[_:\-\s]*\d+$",
    re.IGNORECASE,
)
_STOPWORDS = {
    "a", "an", "and", "at", "by", "for", "from", "in", "inside",
    "into", "near", "of", "on", "onto", "or", "the", "to", "with",
    "within", "slide", "diagram", "chart", "figure", "svg", "area",
    "region", "section", "panel", "main", "central", "center", "middle",
}


def _normalized_tokens(values: Iterable[str]) -> tuple[str, ...]:
    tokens: set[str] = set()
    for value in values:
        normalized = unicodedata.normalize("NFKC", value or "").casefold()
        for token in _TOKEN_RE.findall(normalized):
            if len(token) > 2 and token.endswith("s") and not token.endswith("ss"):
                token = token[:-1]
            if token and token not in _STOPWORDS:
                tokens.add(token)
    return tuple(sorted(tokens))


def _normalized_object_refs(values: Iterable[str]) -> tuple[str, ...]:
    """Normalize stable refs without token-collapsing numbered DOM IDs."""
    refs: set[str] = set()
    for value in values:
        normalized = unicodedata.normalize("NFKC", value or "").casefold().strip()
        normalized = re.sub(r"\s+", " ", normalized)
        if not normalized or _EPHEMERAL_OBJECT_REF_RE.fullmatch(normalized):
            continue
        refs.add(normalized)
    return tuple(sorted(refs))


def issue_target_descriptor(issue: Issue | Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe semantic repair-target descriptor."""
    if isinstance(issue, Mapping):
        evidence = issue.get("evidence") or {}
        fix_detail = issue.get("fix_detail") or {}
        if not isinstance(evidence, Mapping):
            evidence = {"description": str(evidence)}
        if not isinstance(fix_detail, Mapping):
            fix_detail = {}
        issue_id = str(issue.get("issue_id", ""))
        issue_type = str(issue.get("issue_type", ""))
        sub_type = str(issue.get("sub_type", "") or "")
        slides = issue.get("affected_slides", []) or []
        object_refs = evidence.get("object_refs", []) or []
        location = str(fix_detail.get("target_location", "") or "")
        description = str(evidence.get("description", "") or "")
    else:
        issue_id = issue.issue_id
        issue_type = issue.issue_type
        sub_type = issue.sub_type or ""
        slides = issue.affected_slides
        object_refs = issue.evidence.object_refs if issue.evidence else []
        location = issue.fix_detail.target_location if issue.fix_detail else ""
        description = issue.evidence.description if issue.evidence else ""

    refs = _normalized_object_refs(str(ref) for ref in object_refs)
    location_tokens = _normalized_tokens([location])
    evidence_tokens = _normalized_tokens([description]) if not (refs or location_tokens) else ()
    return {
        "issue_id": issue_id,
        "issue_type": issue_type,
        "sub_type": sub_type,
        "slides": sorted(set(slides)),
        "object_refs": list(refs),
        "location_tokens": list(location_tokens),
        "evidence_tokens": list(evidence_tokens),
    }


def _token_similarity(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    jaccard = intersection / len(a | b)
    containment = intersection / min(len(a), len(b))
    # Target descriptions often add a direction or primitive name on a later
    # pass. Strong containment is therefore as meaningful as full Jaccard.
    return max(jaccard, containment * 0.9)


def target_descriptors_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Return whether two descriptors refer to the same repair target."""
    if left.get("issue_type") != right.get("issue_type"):
        return False
    if (left.get("sub_type") or "") != (right.get("sub_type") or ""):
        return False
    if set(left.get("slides", [])) != set(right.get("slides", [])):
        return False

    left_refs = left.get("object_refs", [])
    right_refs = right.get("object_refs", [])
    if left_refs and right_refs and set(left_refs) & set(right_refs):
        return True

    left_location = left.get("location_tokens", [])
    right_location = right.get("location_tokens", [])
    if left_location and right_location:
        overlap = set(left_location) & set(right_location)
        return bool(overlap) and _token_similarity(left_location, right_location) >= 0.54

    left_evidence = left.get("evidence_tokens", [])
    right_evidence = right.get("evidence_tokens", [])
    if left_evidence and right_evidence:
        overlap = set(left_evidence) & set(right_evidence)
        return len(overlap) >= 2 and _token_similarity(left_evidence, right_evidence) >= 0.50

    # Legacy issues without any target signal can only be linked by their
    # carried ID. Do not collapse every same-type issue on a slide.
    return bool(left.get("issue_id")) and left.get("issue_id") == right.get("issue_id")


def issues_share_target(
    left: Issue | Mapping[str, Any],
    right: Issue | Mapping[str, Any],
) -> bool:
    return target_descriptors_match(
        issue_target_descriptor(left), issue_target_descriptor(right),
    )


def stable_issue_id(issue: Issue, prefix: str | None = None) -> str:
    """Build an order-independent ID from the issue's semantic target."""
    descriptor = issue_target_descriptor(issue)
    descriptor.pop("issue_id", None)
    payload = json.dumps(descriptor, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    raw_prefix = prefix or issue.rubric_id or issue.issue_type or "issue"
    clean_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_prefix).strip("_") or "issue"
    slide_part = "_".join(str(slide) for slide in descriptor["slides"]) or "deck"
    return f"{clean_prefix}_slide{slide_part}_{digest}"
