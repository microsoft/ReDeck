"""Deterministic candidates for leaked implementation language in rendered text."""

import re

from .contracts import digest


EDITORIAL_PROBE_ID = "content.editorial_copy"
POLICY_VERSION = "editorial-copy-v3-reading-context"
LEAK_PATTERNS = (
    ("internal-source", r"\btyped\s+evidence\s+architecture\b|\bsource:\s*(?:supplied\s+)?paper\s+evidence\s+architecture\b",
     "If this is an attribution, replace it only with a verified supplied citation; otherwise omit the unsupported attribution."),
    ("internal-heading", r"\bsource[-\s]grounded\s+details\s+used\s+here\b",
     "Use an audience-facing heading such as Evidence or Context if the section warrants one; preserve the evidence itself."),
    ("internal-reservoir", r"\b(?:optional\s+)?source[-\s]detail\s+reservoir\b",
     "Remove the planning label, not the supporting facts or their qualifications."),
    ("internal-obligation", r"\bmust[_-]cover(?:[_-]subset)?\b",
     "Replace the implementation key with a subject-specific heading; preserve its substantive content."),
    ("internal-brief", r"\bbounded\s+creative\s+brief\b",
     "Do not present the generation brief as evidence or a source."),
    ("css-instruction", r"\bobject-fit\s*:\s*contain\b",
     "Keep CSS instructions in code rather than in audience-facing captions; preserve actual attribution."),
    ("internal-row-selection", r"\bclaim[-\s]bearing\s+rows\b|\bselection\s+follows\s+claim\s+overlap(?:\s+and\s+source[-\s]group\s+boundaries)?\b",
     "Use audience-facing evidence wording; preserve row-selection qualifications and do not delete surrounding facts."),
)


def editorial_probe(pages):
    if not pages or any("objects" not in page for page in pages):
        raise ValueError("Editorial copy probe requires rendered text snapshots")
    issues = []
    inputs = []
    for page in pages:
        objects = page["objects"]
        inputs.append({"slide_id": page["slide_id"], "objects": objects,
                       "html_sha256": page.get("html_sha256"), "png_sha256": page.get("png_sha256")})
        for item in objects:
            text = re.sub(r"\s+", " ", item.get("text_content", "")).strip()
            for kind, pattern, suggestion in LEAK_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if not match:
                    continue
                identity = {"slide_id": page["slide_id"], "object_id": item.get("object_id"), "kind": kind, "text": text}
                issues.append({
                    "issue_id": "editorial_" + digest(identity)[:16], "rubric_id": EDITORIAL_PROBE_ID,
                    "issue_type": "implementation_language", "sub_type": kind, "severity": "minor",
                    "affected_slides": [page["slide_id"]], "remediation": "content_revision",
                    "evidence": {"description": f"Rendered text contains a possible implementation label: {match.group(0)!r}.",
                                 "observed_text": text, "object_refs": [item["object_id"]] if item.get("object_id") else []},
                    "suggestion": suggestion,
                    "review_requirement": "Check whether the term is legitimate quoted subject matter before editing; this lexical signal does not authorize factual changes.",
                })
    return {"probe_id": EDITORIAL_PROBE_ID, "scope_slide_ids": [page["slide_id"] for page in pages],
            "requires_source": False, "requires_vision": False, "execution": "executed",
            "status": "failed" if issues else "passed", "issues": issues,
            "input_sha256": digest({"policy": POLICY_VERSION, "patterns": LEAK_PATTERNS, "pages": inputs}),
            "policy": POLICY_VERSION, "model_calls": 0}


def content_remediation(issues, coverage_complete, enabled=True, edit_state=None):
    state = edit_state or {}
    applied = bool(state.get("applied"))
    observations = [issue for issue in issues if issue.get("observation_status") == "unconfirmed"]
    pending = [issue for issue in issues if issue.get("observation_status") != "unconfirmed"]
    status = "applied" if applied else "pending" if pending else "observation_required" if observations else "not_needed"
    if not enabled:
        status = "not_run"
    elif state.get("enabled") is False:
        status = "disabled"
    elif state.get("source_error"):
        status = "blocked_source"
    elif state.get("rolled_back") or (state.get("attempted") and not applied):
        status = "deferred"
    return {
        "status": status,
        "automatic_editor_available": True, "applied": applied,
        "editing_enabled": enabled and state.get("enabled", True),
        "attempted": state.get("attempted", False),
        "pending_issue_count": len(pending), "pending_observation_count": len(observations), "evaluation_complete": coverage_complete,
        "reason": state.get("reason") or state.get("source_error") or "Source-bound content editing is available in the shared repair session; evaluation alone does not apply edits.",
        "next_action": "Repair supported findings against frozen sources and recheck both routes; unresolved or unsupported findings remain pending.",
    }
