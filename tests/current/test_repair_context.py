import json

import pytest
from PIL import Image

from redeck_style.content_repair import SourceCatalog, content_gate, new_content_findings, scoped_content_findings
from redeck_style.evaluation.coordinator import DEFAULT_PROBES
from redeck_style.repair import repair_feedback, repair_system_prompt, repair_user_prompt
from redeck_style.typography import typography_policy_prompt
from scripts import content_repair, repair
from test_content_repair import HTML, PASS, context, issue, proposal


def current_state():
    return {"attempt": 2, "review": PASS, "validity": {"text_geometry": [
        {"selector": "h2", "font_px": 28, "typography": {"role": "sidebar_heading"}}]}}


def original_validity():
    return {"text_geometry": [
        {"selector": "h2", "font_px": 58, "typography": {"role": "sidebar_heading"}}]}


def test_rejection_memory_preserves_content_constraints_without_duplicate_metadata():
    finding = {"issue_id": "rejected_not_authorized", "unused_metadata": "padding" * 200,
               "rubric_id": "C04", "issue_type": "missing_entity", "affected_slides": [2],
               "evidence": {"description": "The earlier candidate omitted whose responsibility was discussed."},
               "why_this_fails": "The claim requires identification of the responsible actors.",
               "fix_detail": {"correct_content": "Preserve responsibility of the State and the able-bodied collective."}}
    serialized = json.dumps([finding])
    trace = [{"attempt": 1, "review_reasons": ["Content findings remain: " + serialized,
              "New content findings affecting CURRENT page or unknown scope: " + serialized]}]
    memory = repair.rejection_memory(trace)
    records = json.loads(memory.split("\n", 1)[1])
    assert len(records) == 1
    assert records[0]["correction_hypothesis"] == finding["fix_detail"]["correct_content"]
    assert "State" in memory and "unused_metadata" not in memory and "rejected_not_authorized" not in memory


@pytest.mark.parametrize("reason", ["Content findings remain: invalid JSON", "Content findings remain: {}"])
def test_rejection_memory_keeps_unstructured_errors_without_crashing(reason):
    memory = repair.rejection_memory([{"attempt": 2, "review_reasons": [reason]}])
    assert json.loads(memory.split("\n", 1)[1]) == [{"last_attempt": 2, "reason": reason}]


@pytest.mark.parametrize("action", ["spatial", "content", "joint"])
def test_policy_occurs_once_and_context_preserves_original_roles(action):
    current = current_state()
    current["validity"]["text_geometry"][0]["typography"]["role"] = "note"
    feedback = repair_feedback(original_validity(), current, action,
                               transition_feedback=repair._diagnostic_feedback(3, current["validity"]))
    system = repair_system_prompt() if action == "spatial" else content_repair.SYSTEM
    policy = typography_policy_prompt()
    assert system.count(policy) == 1 and policy not in feedback
    assert f'"action": "{action}"' in feedback and '"attempt": 2' in feedback
    assert '"role": "sidebar_heading"' in feedback
    assert '"minimum_effective_px": 24' in feedback
    assert '"original_px": 58' in feedback and '"current_px"' not in feedback
    assert current["validity"]["text_geometry"][0]["font_px"] == 28
    assert "Return a corrected complete HTML document" not in feedback
    assert "Preserve the original visible text" not in feedback


def test_current_diagnostics_are_not_rejected_candidate_diagnostics():
    current = current_state()
    rejection = "Layout edit changed rendered text visibility"
    transition = repair._diagnostic_feedback(3, current["validity"], [rejection])
    feedback = repair_feedback(original_validity(), current, "spatial", "Keep the source footer readable",
                               transition, repair.rejection_memory([{"attempt": 1, "guard_reasons": [rejection]}]))
    prompt = repair_user_prompt(HTML, current["validity"], feedback)
    assert "Deterministic CURRENT diagnostics" in prompt
    assert "CURRENT visual review" in feedback
    assert "ORIGINAL had 3 hard issues; CURRENT has 0" in feedback
    assert "Rejected candidate invariant failures (not CURRENT findings)" in feedback
    assert "Rejected proposal history; not CURRENT findings" in feedback
    assert "Previous candidate feedback" not in prompt
    assert "Keep the source footer readable" in prompt
    assert prompt.split("Current complete HTML:\n", 1)[1].strip() == HTML


def test_spatial_prompt_preserves_authorized_current_copy_and_type_priority():
    system = repair_system_prompt()
    user = repair_user_prompt(HTML, {})
    assert "authorized source-backed corrections" in system
    assert "do not restore ORIGINAL wording" in system
    assert "For oversized secondary headings first try font-size" in system
    assert "resize the coupled tracks/regions" not in user
    assert "Inspect the whole screenshot" in system


def test_content_request_does_not_inherit_html_protocol(tmp_path, context, monkeypatch):
    image = tmp_path / "current.png"
    Image.new("RGB", (32, 18), "white").save(image)
    feedback = repair_feedback(original_validity(), current_state(), "joint",
                               transition_feedback=repair._diagnostic_feedback(3, {}))

    def model(client, model, system, content):
        payload = json.loads(content[0]["text"])
        assert "Return exactly one JSON object" in system
        assert payload["current_html"] == HTML
        assert "Return a corrected complete HTML document" not in payload["feedback"]
        assert (system + payload["feedback"]).count(typography_policy_prompt()) == 1
        return json.dumps(proposal()), 10, 10, .1

    monkeypatch.setattr(content_repair, "call_llm", model)
    result = content_repair.propose(None, "fixture", HTML, image, {}, [issue()], SourceCatalog(context),
                                    feedback, tmp_path / "attempt", True)
    request = json.loads((tmp_path / "attempt_tool_01.request.json").read_text())
    assert request["system"] == content_repair.SYSTEM
    assert len(result["calls"]) == 1 and "48%" in result["html"]


@pytest.mark.parametrize("affected,blocked", [([1], True), ([2], False), ([1, 2], True), ([], True), (None, True)])
def test_candidate_and_final_content_gates_share_scope(affected, blocked):
    records = [{"probe_id": probe_id, "scope_slide_ids": [1, 2], "status": "passed", "issues": []}
               for probe_id in (*DEFAULT_PROBES, "content.editorial_copy")]
    baseline = {"routes": {"content": {"issues": [], "probes": records}}}
    finding = {**issue(), "affected_slides": affected}
    candidate = {"routes": {"content": {"issues": [finding], "probes": records}}}
    assert bool(scoped_content_findings(candidate, 1)) is blocked
    assert new_content_findings(baseline, candidate, 1) is blocked
    assert content_gate(candidate, 1)[0] is not blocked
    assert new_content_findings(baseline, candidate)
    assert candidate["routes"]["content"]["issues"] == [finding]
    assert not new_content_findings(candidate, candidate, 1)


def test_missing_finding_scope_stays_conservative():
    finding = issue()
    del finding["affected_slides"]
    baseline = {"routes": {"content": {"issues": []}}}
    candidate = {"routes": {"content": {"issues": [finding]}}}
    assert new_content_findings(baseline, candidate, 1)
    assert new_content_findings(baseline, candidate, 2)
