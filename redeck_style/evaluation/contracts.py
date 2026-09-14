"""Validate probe output before legacy parsers can turn errors into empty passes."""

import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def summarize_records(records, coverage_complete):
    issues = [issue for record in records for issue in record.get("issues", [])]
    advisory_records = [record for record in records if record.get("route") == "spatial"
                        and record.get("probe_id") == "spatial.gradient_violation"]
    advisories = [issue for record in advisory_records for issue in record.get("issues", [])]
    actionable = [issue for record in records if record not in advisory_records for issue in record.get("issues", [])]
    confirmed = any(issue.get("observation_status") != "unconfirmed" for issue in actionable)
    return {"status": "failed" if confirmed else "incomplete" if actionable else "passed" if coverage_complete else "incomplete",
            "coverage_complete": coverage_complete, "issues": issues, "probes": records,
            "advisories": advisories}


def validate_probe_output(raw, probe_id, slide_ids):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    data = json.loads(cleaned)
    if not isinstance(data, dict) or data.get("probe_id") != probe_id or not isinstance(data.get("issues"), list):
        raise ValueError("Probe response must declare matching probe_id and an issues array")
    for issue in data["issues"]:
        if not isinstance(issue, dict):
            raise ValueError("Probe issue must be an object")
        affected = issue.get("affected_slides")
        if not isinstance(affected, list) or not affected or any(type(value) is not int or value not in slide_ids for value in affected):
            raise ValueError("Probe issue refers to missing or out-of-scope slides")
        if issue.get("severity") not in {"minor", "major", "critical"}:
            raise ValueError("Probe issue has no valid severity")
        evidence = issue.get("evidence")
        description = evidence.get("description") if isinstance(evidence, dict) else evidence
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Probe issue must include observed evidence")
    unresolved = data.get("unresolved_observations", [])
    if not isinstance(unresolved, list):
        raise ValueError("unresolved_observations must be an array")
    for observation in unresolved:
        if (not isinstance(observation, dict) or type(observation.get("slide_id")) is not int
                or observation["slide_id"] not in slide_ids or not isinstance(observation.get("reason"), str)
                or not observation["reason"].strip()):
            raise ValueError("Unresolved observation requires an in-scope slide and reason")
    return data


def observation_ids(pages):
    references = {}
    for page in pages:
        reading = page.get("reading_view", {})
        items = page["objects"] + reading.get("blocks", []) + reading.get("images", [])
        items += [mark for chart in reading.get("charts", []) for mark in chart["marks"]]
        items += [cell for table in reading.get("tables", []) for row in table["rows"] for cell in row]
        references[page["slide_id"]] = {item["object_id"] for item in items if item.get("object_id")}
    return references


def validate_observation_refs(data, pages):
    references = observation_ids(pages)
    for issue in data["issues"]:
        evidence = issue.get("evidence")
        if not isinstance(evidence, dict) or not evidence.get("object_refs"):
            raise ValueError("Definitive issue evidence must be an object with description and nonempty object_refs; put uncertain observations in unresolved_observations")
        refs = evidence.get("object_refs", []) if isinstance(evidence, dict) else []
        allowed = set().union(*(references[slide_id] for slide_id in issue["affected_slides"]))
        if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in allowed for ref in refs):
            raise ValueError("Evidence object_refs must identify actual in-scope reading or spatial objects")
    for observation in data.get("unresolved_observations", []):
        refs = observation.get("object_refs", [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in references[observation["slide_id"]] for ref in refs):
            raise ValueError("Unresolved observation has unknown object_refs")


def ground_findings(issues, pages):
    references = observation_ids(pages)
    findings = []
    for issue in issues:
        evidence = issue.get("evidence") or {}
        refs = evidence.get("object_refs", []) if isinstance(evidence, dict) else []
        allowed = set().union(*(references.get(slide_id, set()) for slide_id in issue.get("affected_slides", [])))
        grounded = bool(refs) and all(ref in allowed for ref in refs)
        findings.append({**issue, "observation_status": "anchored" if grounded else "unconfirmed"})
    return findings


GROUP_CONTENT_PROBES = frozenset({"C01", "C03", "C04", "C05", "D06"})


def probe_input_hash(probe_id, pages, context_hash, requires_vision=False):
    inputs = []
    for page in pages:
        entry = {"slide_id": page["slide_id"], "title": page["title"],
                 "text": [item["text_content"] for item in page["objects"]],
                 "media": [item["image_path"] for item in page["objects"] if item["has_image"]],
                 "reading_view": page.get("reading_view")}
        if probe_id == "D04" or requires_vision:
            entry.update(html_sha256=page["html_sha256"], png_sha256=page["png_sha256"])
        inputs.append(entry)
    return digest({"probe_id": probe_id, "pages": inputs, "context": context_hash,
                   "requires_vision": requires_vision, "dependency_policy": "reading-evidence-or-pixels-v3"})
