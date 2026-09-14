#!/usr/bin/env python3
"""Repair v2 HTML slides without importing the legacy ReDeck repair stack."""

from __future__ import annotations

import argparse
import base64
import difflib
import json
import re
import sys
import io
import math
import time
from pathlib import Path

from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redeck_style.repair import (
    hard_issue_count,
    issue_counts,
    repair_system_prompt,
    repair_user_prompt,
    repair_feedback,
    visual_review_system_prompt,
    parse_visual_review,
    validate_repair,
    semantic_signature,
    typography_constraints,
    candidate_decision,
    needs_spatial,
    review_rank,
    typography_approved,
)
from redeck_style.typography import typography_audit
from scripts.codegen import extract_html, get_client, call_llm
from redeck_style.execution import measure
from redeck_style.evaluation.coordinator import (
    add_judge_arguments, judge_options,
)
from redeck_style.evaluation import probes
from scripts.repair_session import add_repair_arguments, run_repair_jobs


def render_and_measure(html_path: Path, png_path: Path) -> dict:
    from redeck_style.evaluation.snapshot import capture_page

    timings = {}
    with measure(timings, "render_seconds"):
        validity = capture_page(html_path, png_path)["validity"]
    Path(png_path).with_suffix(".timing.json").write_text(json.dumps(timings) + "\n")
    return validity


def call_repair(client, model: str, prompt: str, screenshot: Path) -> str:
    encoded = base64.b64encode(screenshot.read_bytes()).decode("ascii")
    content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
    ]
    raw, _, _, _ = call_llm(client, model, repair_system_prompt(), content,
                            log_prefix=screenshot.with_suffix(".spatial_proposal"))
    return extract_html(raw)


def review_crop_box(rect: dict, width: int, height: int):
    """Clamp a contextual crop to the canvas; off-canvas findings still stay in diagnostics."""
    try:
        x, y, w, h = (float(rect[key]) for key in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x, y, w, h)) or w <= 0 or h <= 0:
        return None
    box = (max(0, math.floor(x - 110)), max(0, math.floor(y - 70)),
           min(width, math.ceil(x + w + 110)), min(height, math.ceil(y + h + 70)))
    return box if box[2] > box[0] and box[3] > box[1] else None


def call_visual_review(client, model: str, original_png: Path, current_png: Path, validity: dict) -> dict:
    geometry = validity.get("text_geometry", []) + validity.get("graphic_geometry", [])
    identical = original_png.read_bytes() == current_png.read_bytes()
    content = [{"type": "text", "text": ("Original and CURRENT renders are identical; the single image shows both. Judge current only."
                                         if identical else "Original render, then CURRENT render. Judge current only.")}]
    seen_images = set()
    for path in (original_png, current_png):
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        if encoded in seen_images:
            continue
        seen_images.add(encoded)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}})
    # Diagnostic crops retain neighboring context. They are derived only from
    # the current slide, never BAMS or a desired-result image.
    targets = []
    for key in ("table_cell_overflow_details", "connector_occlusion_details", "connector_rule_collision_details", "text_collision_details", "graphic_text_collision_details", "graphic_text_clearance_details", "text_clearance_details", "text_association_details"):
        for issue in validity.get(key, []):
            target = next((issue[name] for name in ("text", "label", "first") if isinstance(issue.get(name), dict)), issue)
            if target.get("rect"):
                targets.append(target)
    targets.extend(item for item in geometry if item.get("font_px", 0) >= 48)
    seen = set()
    with Image.open(current_png) as frame:
        for target in targets:
            box = review_crop_box(target["rect"], frame.width, frame.height)
            if box is None or box in seen or len(seen) >= 4:
                continue
            seen.add(box)
            buf = io.BytesIO()
            frame.crop(box).resize(((box[2]-box[0])*2, (box[3]-box[1])*2)).save(buf, format="PNG")
            content.append({"type": "text", "text": f"CURRENT detail at {box}; target {target.get('selector')}. Includes surrounding context."})
            content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")}})
    content.append({"type": "text", "text": "Current text and graphic geometry:\n" + json.dumps(geometry, ensure_ascii=False)})
    reference_path = original_png.with_suffix(".state.json")
    if reference_path.exists():
        from redeck_style.evaluation.snapshot import file_hash

        reference = json.loads(reference_path.read_text())
        if reference.get("png_sha256") != file_hash(original_png):
            raise ValueError("Original typography reference does not match its image")
        original_validity = reference["validity"]
        content.append({"type": "text", "text": "Immutable ORIGINAL-role typography contract and candidate audit:\n" + json.dumps({
            "contract": typography_constraints(original_validity, validity),
            "audit": typography_audit(original_validity, validity)}, ensure_ascii=False)})
    try:
        raw, _, _, _ = call_llm(client, model, visual_review_system_prompt(), content, max_output_tokens=8192,
                                log_prefix=current_png.with_suffix(".visual_review"))
        return parse_visual_review(raw, {item["selector"] for item in geometry},
                                   require_scope=True, require_quality=True)
    except Exception as exc:
        # An unavailable reviewer is not a positive quality judgment.
        return {"verdict": "uncertain", "issues": [], "valid": False, "error": type(exc).__name__}


def computed_type_reductions(before: dict, after: dict) -> list[dict]:
    """Compatibility entry point returning actual safety violations, not all reductions."""
    return typography_audit(before, after)["violations"]


def issue_regressions(before: dict, after: dict) -> list[str]:
    """Do not trade a new issue category for fewer old findings."""
    keys = ("overflow_count", "text_clip_count", "text_collision_count", "graphic_text_collision_count",
            "table_cell_overflow_count",
            "connector_rule_collision_count",
            "connector_occlusion_count", "source_asset_issue_count",
            "graphic_text_clearance_count", "text_clearance_count", "text_association_count", "low_contrast_count", "gradient_violation_count")
    # Collision -> clearance is a meaningful partial improvement, not a new
    # category. Count the two stages of the same spatial defect together.
    groups = [("graphic_text_collision_count", "graphic_text_clearance_count"),
              ("text_collision_count", "text_clearance_count", "text_association_count")]
    grouped = {key for group in groups for key in group}
    groups.extend((key,) for key in keys if key not in grouped)
    return ["/".join(group) for group in groups
            if sum(after.get(key, 0) for key in group) > sum(before.get(key, 0) for key in group)]


def rejection_memory(trace: list[dict]) -> str:
    failures = {}
    for item in trace:
        if item.get("advanced_working_draft"):
            continue
        reasons = list(item.get("guard_reasons", [])) + list(item.get("review_reasons", []))
        if item.get("reason"):
            reasons.append(item["reason"])
        for reason in reasons:
            entries = []
            if str(reason).startswith("computed type compressed: "):
                try:
                    violations = json.loads(reason.split(": ", 1)[1])
                    entries = [{key: value for key, value in violation.items() if key in {
                        "selector", "original_selector", "role", "minimum_effective_px", "reason",
                        "before_px", "after_px", "before_effective_px", "after_effective_px"}}
                        for violation in violations if isinstance(violation, dict)]
                except (ValueError, TypeError):
                    entries = []
            for prefix in ("Content findings remain: ", "New content findings affecting CURRENT page or unknown scope: "):
                if not str(reason).startswith(prefix):
                    continue
                try:
                    findings = json.loads(reason[len(prefix):])
                except (ValueError, TypeError):
                    break
                if not isinstance(findings, list):
                    break
                for finding in findings:
                    if not isinstance(finding, dict):
                        continue
                    evidence = finding.get("evidence") or {}
                    fix = finding.get("fix_detail") or {}
                    entries.append({"probe": finding.get("probe_id", finding.get("rubric_id")),
                                    "issue_type": finding.get("issue_type"), "affected_slides": finding.get("affected_slides"),
                                    "observation": evidence.get("description", evidence.get("observed_text", "")) if isinstance(evidence, dict) else str(evidence),
                                    "why": finding.get("why_this_fails", ""),
                                    "correction_hypothesis": fix.get("correct_content", "") if isinstance(fix, dict) else str(fix)})
                break
            for entry in entries or [{"reason": str(reason)[:500]}]:
                failures[json.dumps(entry, ensure_ascii=False, sort_keys=True)] = item["attempt"]
    return "Cumulative rejected-proposal constraints (not the CURRENT draft); do not repeat these failures:\n" + json.dumps(
        [{"last_attempt": attempt, **json.loads(entry)} for entry, attempt in list(failures.items())[-12:]], ensure_ascii=False)


def _diagnostic_feedback(before_count: int, current: dict, guard_reasons=()) -> str:
    current_count = hard_issue_count(current)
    parts = [
        f"Immutable ORIGINAL had {before_count} hard issues; CURRENT has {current_count}.",
    ]
    if guard_reasons:
        parts.append("Rejected candidate invariant failures (not CURRENT findings): " + "; ".join(guard_reasons))
    return "\n".join(parts)


def visual_change_audit(before_path: Path, after_path: Path, threshold: int = 12) -> dict:
    """Measure change extent; this is a review aid, never a beauty score."""
    before = Image.open(before_path).convert("RGB")
    after = Image.open(after_path).convert("RGB")
    difference = ImageChops.difference(before, after)
    bbox = difference.getbbox()
    changed = difference.convert("L").point(lambda value: 255 if value > threshold else 0)
    changed_pixels = changed.histogram()[255]
    canvas_pixels = before.width * before.height
    bbox_ratio = 0.0
    if bbox:
        bbox_ratio = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / canvas_pixels
    return {
        "changed_pixel_ratio": round(changed_pixels / canvas_pixels, 4),
        "changed_bbox_ratio": round(bbox_ratio, 4),
        "changed_bbox": list(bbox) if bbox else None,
    }


def source_change_audit(before: str, after: str) -> dict:
    """Expose edit scope so a full-page rewrite cannot masquerade as Repair."""
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines)
    deleted = inserted = 0
    changed_regions = 0
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        changed_regions += 1
        deleted += left_end - left_start
        inserted += right_end - right_start
    denominator = max(1, len(before_lines) + len(after_lines))
    return {
        "original_lines": len(before_lines),
        "candidate_lines": len(after_lines),
        "deleted_lines": deleted,
        "inserted_lines": inserted,
        "changed_regions": changed_regions,
        "changed_line_ratio": round((deleted + inserted) / denominator, 3),
    }


def prepare_repair(source, output_dir):
    original = source.read_text()
    t0_html = output_dir / "t0_slide_code" / source.name
    if t0_html.exists():
        raise FileExistsError(f"Run already contains {source.name}; use a fresh output directory")
    t0_html.parent.mkdir(parents=True, exist_ok=True)
    t0_html.write_text(original)
    t0_png = output_dir / "t0_png" / f"{source.stem}.png"
    return {"original": original, "validity": render_and_measure(t0_html, t0_png)}


def spatial_probe_result(png, original_png, validity, review, slide_id, model):
    state = png.with_suffix(".state.json")
    if state.exists():
        page = {**json.loads(state.read_text()), "slide_id": slide_id, "original_png": str(original_png)}
        return probes.spatial_result(page, review, model)
    return {"validity": validity, "review": review, "probes": probes.spatial_records(validity, review, slide_id)}


def repair_file(client, model: str, source: Path, output_dir: Path, attempts: int, review_feedback: str = "",
                judge_config=None, prepared=None, initial_spatial=None) -> dict:
    if judge_config is not None:
        jobs = [{"source": str(source), "output": str(output_dir)}]
        return run_repair_jobs(jobs, output_dir, model, attempts, judge_config,
                               review_feedback=review_feedback, client_factory=lambda: client)[0]
    return repair_spatial(client, model, source, output_dir, attempts, review_feedback, prepared, initial_spatial)


def repair_spatial(client, model, source, output_dir, attempts, review_feedback="", prepared=None, initial_spatial=None):
    return repair_slide(client, model, source, output_dir, attempts, review_feedback, prepared, initial_spatial)


def next_repair_action(current, controller, content_task, spatial_enabled):
    spatial = spatial_enabled and needs_spatial(current)
    content = bool(content_task and controller.get("pending_issues", content_task["issues"]) and not current["content_verified"]
                   and not controller.get("content_blocked"))
    if spatial and content:
        if controller.get("last_action") in {"content", "joint"} and not controller.get("last_advanced"):
            return "spatial"
        return "joint"
    return "content" if content else "spatial" if spatial else None


def refresh_repair_controller(controller, page, spatial, content_verified):
    selected = controller["written"]
    if Path(page["source"]).read_text() != selected["html"]:
        raise ValueError("Final review does not match the selected repair state")
    current = {**selected, "png": Path(page["png"]), "content_verified": content_verified}
    if spatial:
        current.update(validity=spatial["validity"], review=spatial["review"], evaluation=spatial)
    controller["current"] = current
    controller["best"] = (controller["layout_checkpoint"] if current["content_changed"]
                          and (not content_verified or (spatial and needs_spatial(current))) else current)


def repair_slide(client, model, source, output_dir, attempts, review_feedback="", prepared=None, initial_spatial=None,
                 content_task=None, candidate_evaluator=None, controller=None, step_limit=None, current_evaluator=None):
    from redeck_style.content_repair import actionable_issues, content_coverage_gate, content_finding_key, content_gate, new_content_findings, rendered_edit_matches, scoped_content_findings
    from redeck_style.evaluation.snapshot import load_snapshot
    from scripts.content_repair import ContentRepairDeferred, propose

    if attempts < 0:
        raise ValueError("Repair attempt budget must be nonnegative")
    controller = {} if controller is None else controller

    prepared = prepared or prepare_repair(source, output_dir)
    original = prepared["original"]
    if source.read_text() != original:
        raise ValueError("Source changed after T0 was frozen")
    source_key = (str(source.resolve()), str(output_dir.resolve()), probes.digest(original))
    if controller and controller["source_key"] != source_key:
        raise ValueError("Cannot reuse a repair controller for another page or output")
    stem = source.stem
    match = re.fullmatch(r"slide_(\d+)", stem)
    slide_id = prepared.get("slide_id", int(match.group(1)) if match else 0)
    t0_png = output_dir / "t0_png" / f"{stem}.png"
    t1_png = output_dir / "t1_png" / f"{stem}.png"
    candidates_dir = output_dir / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    before = prepared["validity"]
    before_count = hard_issue_count(before)
    initial_review = controller.get("initial_review") or (initial_spatial["review"] if initial_spatial else call_visual_review(client, model, t0_png, t0_png, before))
    spatial_enabled = initial_review["verdict"] != "not_run"
    initial_spatial = initial_spatial or spatial_probe_result(t0_png, t0_png, before, initial_review, slide_id, model)
    (output_dir / f"{stem}_initial_review.json").write_text(json.dumps(initial_review, indent=2) + "\n")
    if not controller:
        initial_state = {"html": original, "validity": before, "png": t0_png, "review": initial_review, "attempt": 0,
                         "evaluation": initial_spatial, "semantic_base": original, "content_verified": False,
                         "content_changed": False}
        controller.update(current=initial_state, best=initial_state, layout_checkpoint=initial_state,
                          source_key=source_key,
                          initial_review=initial_review, total=attempts, used=0, trace=[], feedback="",
                          actions={"spatial": 0, "content": 0, "joint": 0})
    if controller["total"] != attempts:
        raise ValueError("Cannot reset the shared repair budget on reentry")
    task_key = tuple(sorted(issue["issue_id"] for issue in content_task["issues"])) if content_task else ()
    controller["issue_ids"] = sorted(set(controller.get("issue_ids", [])) | set(task_key))
    if task_key != controller.get("task_key"):
        if not controller.get("rolled_back"):
            controller.pop("content_blocked", None)
        controller["task_key"] = task_key
    controller["pending_issues"] = content_task["issues"] if content_task else []
    current, best, layout_checkpoint = (controller[key] for key in ("current", "best", "layout_checkpoint"))
    feedback, trace = controller["feedback"], controller["trace"]
    remaining = attempts - controller["used"]
    allowance = remaining if step_limit is None else min(remaining, step_limit)

    if allowance:
        for attempt in range(controller["used"] + 1, controller["used"] + allowance + 1):
            contract = None
            timings = {}
            phase = next_repair_action(current, controller, content_task, spatial_enabled)
            if phase is None and review_feedback and spatial_enabled and not controller["used"]:
                phase = "spatial"
            if phase is None:
                break
            controller["used"] = attempt
            controller["actions"][phase] += 1
            editing_content = phase in {"content", "joint"}
            controller.update(last_action=phase, last_advanced=False)
            candidate_path = candidates_dir / f"{stem}_attempt_{attempt:02d}.html"
            if candidate_path.exists():
                raise FileExistsError("Cannot overwrite a repair candidate version")
            candidate_png = candidates_dir / f"{stem}_attempt_{attempt:02d}.png"
            accumulated_feedback = repair_feedback(before, current, phase, review_feedback, feedback, rejection_memory(trace))
            proposal_started = time.monotonic()
            try:
                if editing_content:
                    if candidate_evaluator is None:
                        raise ValueError("Content edits require independent unified probe acceptance")
                    contract = propose(client, model, current["html"], current["png"], current["validity"],
                                       controller["pending_issues"], content_task["catalog"],
                                       accumulated_feedback,
                                       candidate_path.with_suffix(""), spatial_enabled)
                    proposed = contract["html"]
                    candidate_path.with_suffix(".edits.json").write_text(json.dumps({
                        "proposal": contract["proposal"], "source_hashes": content_task["catalog"].context["source_hashes"],
                        "calls": contract["calls"]}, ensure_ascii=False, indent=2) + "\n")
                else:
                    prompt = repair_user_prompt(current["html"], current["validity"], accumulated_feedback)
                    candidate_path.with_suffix(".request.json").write_text(json.dumps({
                        "model": model, "system": repair_system_prompt(), "prompt": prompt,
                        "parent_attempt": current["attempt"], "screenshot": str(current["png"])}, ensure_ascii=False, indent=2) + "\n")
                    proposed = call_repair(client, model, prompt, current["png"])
            except Exception as error:
                feedback = f"Proposal rejected without changing CURRENT: {type(error).__name__}: {error}"
                if isinstance(error, ContentRepairDeferred):
                    controller["content_blocked"] = str(error)
                trace.append({"attempt": attempt, "accepted": False, "phase": phase, "reason": feedback,
                              "timings": {"proposal_seconds": time.monotonic() - proposal_started}})
                print(f"  {stem} {phase} {attempt}/{attempts}: {feedback}", flush=True)
                continue
            timings["proposal_seconds"] = time.monotonic() - proposal_started
            if "<html" not in proposed.lower():
                trace.append({"attempt": attempt, "phase": phase, "accepted": False, "reason": "no complete HTML", "timings": timings})
                feedback = "The response did not contain a complete HTML document."
                continue
            semantic_base = contract["semantic_base"] if contract else current["semantic_base"]
            guard = validate_repair(semantic_base, proposed)
            candidate_path.write_text(proposed)
            if not guard.accepted:
                trace.append({
                    "attempt": attempt,
                    "phase": phase,
                    "parent_attempt": current["attempt"],
                    "accepted": False,
                    "guard_reasons": guard.reasons,
                    "timings": timings,
                    "font_scale": guard.audit,
                    "source_change": source_change_audit(original, proposed),
                })
                feedback = "The last proposal was discarded; the supplied HTML/render remain CURRENT.\n" + _diagnostic_feedback(before_count, current["validity"], guard.reasons)
                continue
            try:
                with measure(timings, "render_seconds"):
                    validity = render_and_measure(candidate_path, candidate_png)
            except Exception as error:
                feedback = f"Candidate rendering failed; not accepted: {type(error).__name__}: {error}"
                trace.append({"attempt": attempt, "phase": phase, "accepted": False, "reason": feedback, "timings": timings})
                continue
            count = hard_issue_count(validity)
            visual_change = visual_change_audit(t0_png, candidate_png)
            # Large pixel changes are not necessarily wrong (chart reflow can
            # affect a broad region), but they are not safe to auto-accept as
            # local Repair. Keep them for explicit visual review.
            review_reasons = []
            scope_required = bool(visual_change["changed_pixel_ratio"] > 0.20 or current.get("scope_required"))
            type_audit = typography_audit(before, validity)
            typography_required = bool(type_audit["review_required"] or current.get("typography_required"))
            reductions = type_audit["violations"]
            if reductions:
                review_reasons.append("computed type compressed: " + json.dumps(reductions))
            regressions = issue_regressions(current["validity"], validity)
            protected_regressions = [key for key in ("source_asset_issue_count", "low_contrast_count", "gradient_violation_count")
                                     if validity.get(key, 0) > current["validity"].get(key, 0)]
            exploring_layout = bool(not editing_content and spatial_enabled
                                    and ((current["content_changed"] and current["html"] != best["html"]) or scope_required or typography_required)
                                    and count <= max(before_count, hard_issue_count(current["validity"])))
            if regressions and ((not editing_content and not exploring_layout) or not spatial_enabled or protected_regressions):
                review_reasons.append("new or increased issue categories: " + ", ".join(regressions))
            content_verified = current["content_verified"]
            content_changed = semantic_signature(semantic_base) != semantic_signature(original)
            content_report = None
            content_reasons = []
            rendered_matches = True
            if contract:
                previous_state = json.loads(current["png"].with_suffix(".state.json").read_text())
                candidate_state = load_snapshot(candidate_path, candidate_png)
                if not rendered_edit_matches(previous_state, candidate_state, contract):
                    rendered_matches = False
                    review_reasons.append("Rendered text does not match the authorized content edits")
            elif current["png"].with_suffix(".state.json").exists() and candidate_png.with_suffix(".state.json").exists():
                previous_state = json.loads(current["png"].with_suffix(".state.json").read_text())
                candidate_state = load_snapshot(candidate_path, candidate_png)
                if not rendered_edit_matches(previous_state, candidate_state, {"removed_tokens": {}, "added_tokens": {}}):
                    rendered_matches = False
                    review_reasons.append("Layout edit changed rendered text visibility")
            if (editing_content or content_changed) and not review_reasons:
                try:
                    if candidate_evaluator is None or content_task is None:
                        raise ValueError("Content-bearing drafts require independent unified evaluation")
                    content_task["catalog"].verify()
                    with measure(timings, "probe_seconds"):
                        content_report = candidate_evaluator(candidate_path, candidate_png, attempt)
                    content_task["catalog"].verify()
                    content_verified, reason = content_gate(content_report, slide_id)
                    if not content_verified:
                        content_reasons.append(reason)
                    if new_content_findings(content_task["baseline"], content_report, slide_id):
                        content_verified = False
                        content_reasons.append("New content findings affecting CURRENT page or unknown scope: " +
                                              json.dumps(scoped_content_findings(content_report, slide_id), ensure_ascii=False))
                    review = content_report["routes"]["spatial"].get("pages", {}).get(str(slide_id), {}).get("review", initial_review)
                except Exception as error:
                    review_reasons.append(f"Unified candidate evaluation failed: {type(error).__name__}: {error}")
                    review = {"verdict": "uncertain", "issues": [], "valid": False}
            elif not review_reasons:
                with measure(timings, "probe_seconds"):
                    review = call_visual_review(client, model, t0_png, candidate_png, validity) if spatial_enabled else initial_review
            else:
                review = {"verdict": "uncertain", "issues": [], "valid": False, "error": "deterministic guard rejected candidate"}
            scope_preserved = review.get("scope", {}).get("verdict") == "preserved"
            if scope_required and (not spatial_enabled or not review.get("valid") or not scope_preserved):
                review_reasons.append("Expanded repair scope requires an explicit preserved design-continuity review")
            elif review.get("scope", {}).get("verdict") == "changed":
                review_reasons.append("Visual review found changed design continuity")
            if typography_required and (not spatial_enabled or not review.get("valid")
                    or review.get("typography", {}).get("verdict") not in {"readable", "needs_repair"}
                    or review.get("composition", {}).get("verdict") not in {"coherent", "needs_repair"}):
                review_reasons.append("Typography changes require explicit readable-role and composition review")
            candidate_path.with_suffix(".review.json").write_text(json.dumps(review, indent=2) + "\n")
            evaluation = spatial_probe_result(candidate_png, t0_png, validity, review, slide_id, model)
            candidate = {"html": proposed, "validity": validity, "png": candidate_png, "review": review, "attempt": attempt,
                         "evaluation": evaluation, "semantic_base": semantic_base, "content_verified": content_verified,
                         "content_changed": content_changed,
                         "scope_required": scope_required,
                         "typography_required": typography_required,
                         "content_report": content_report["report_path"] if content_report else current.get("content_report")}
            # Safe equal-count moves may become the next working draft. They
            # are NOT successful repairs. Keep HTML/PNG/diagnostics/review from
            # this same draft together, so retry feedback never targets another.
            pending_issues = actionable_issues(content_report["routes"]["content"].get("issues", []), slide_id) if content_report else []
            replan_content = bool(not editing_content and current["content_changed"] and content_report and pending_issues
                                  and content_coverage_gate(content_report, slide_id)[0])
            decision = candidate_decision(current, best, candidate, editing_content=editing_content,
                exploring_layout=exploring_layout, spatial_enabled=spatial_enabled, review_reasons=review_reasons,
                content_reasons=content_reasons, replan_content=replan_content)
            advance, publishable, accepted = (decision[key] for key in ("advance", "eligible", "selected"))
            trace.append({
                "attempt": attempt,
                "parent_attempt": current["attempt"],
                "timings": timings,
                "accepted": accepted,
                "advanced_working_draft": advance,
                "hard_issues": count,
                "validity": validity,
                "font_scale": guard.audit,
                "typography_audit": type_audit,
                "visual_change": visual_change,
                "source_change": source_change_audit(original, proposed),
                "review_reasons": review_reasons + content_reasons,
                "visual_review": review,
                "probes": evaluation["probes"],
                "phase": phase,
                "provisional": bool(advance and not publishable),
                "content_verified": content_verified,
                "pending_content_issue_ids": [issue["issue_id"] for issue in pending_issues],
                "exploring_layout": bool(advance and exploring_layout and not publishable),
                "gates": {"safety_passed": not guard.reasons and not reductions and not protected_regressions and rendered_matches,
                          "scope_required": scope_required, "scope_review": review.get("scope"),
                          "typography_required": typography_required, "typography_review": review.get("typography"),
                          "composition_review": review.get("composition"),
                          "working_draft": bool(advance), "publishable": bool(advance and publishable)},
                "content_candidate_report": content_report["report_path"] if content_report else None,
            })
            print(f"  {stem} {phase} {attempt}/{attempts}: {count} raw findings; visual={review['verdict']}; advance={advance}; selected={accepted}", flush=True)
            if accepted:
                best = candidate
                if not candidate["content_changed"]:
                    layout_checkpoint = candidate
            if advance:
                current = candidate
                controller["last_advanced"] = True
                feedback = _diagnostic_feedback(before_count, validity)
                if content_report:
                    controller["pending_issues"] = pending_issues
                    controller["issue_ids"] = sorted(set(controller["issue_ids"]) | {issue["issue_id"] for issue in pending_issues})
                    feedback += "\nCurrent content probe feedback: " + json.dumps(content_reasons, ensure_ascii=False)
            else:
                feedback = ("Last proposal discarded; current HTML/render were NOT changed. Rejection:\n" +
                            json.dumps({"reasons": review_reasons + content_reasons, "proposal_review": review}, ensure_ascii=False))
                known_findings = {content_finding_key(issue) for issue in controller.get("pending_issues", [])}
                checked = controller.setdefault("rechecked_current_attempts", [])
                if (editing_content and current_evaluator and content_report and attempt < attempts
                        and any(content_finding_key(issue) not in known_findings for issue in pending_issues)
                        and content_coverage_gate(content_report, slide_id)[0]
                        and current["attempt"] not in checked):
                    checked.append(current["attempt"])
                    try:
                        with measure(timings, "current_recheck_seconds"):
                            current_report = current_evaluator(current, attempt)
                        content_task["catalog"].verify()
                        if not content_coverage_gate(current_report, slide_id)[0]:
                            raise ValueError("CURRENT recheck has incomplete probe coverage")
                        refreshed = actionable_issues(current_report["routes"]["content"].get("issues", []), slide_id)
                        controller["pending_issues"] = refreshed
                        controller["issue_ids"] = sorted(set(controller["issue_ids"]) | {issue["issue_id"] for issue in refreshed})
                        current = {**current, "content_verified": content_gate(current_report, slide_id)[0],
                                   "content_report": current_report["report_path"]}
                        spatial = current_report["routes"]["spatial"].get("pages", {}).get(str(slide_id))
                        if spatial:
                            current.update(validity=spatial["validity"], review=spatial["review"], evaluation=spatial)
                        trace[-1]["current_recheck"] = {"report": current_report["report_path"],
                            "current_attempt": current["attempt"], "issue_ids": [issue["issue_id"] for issue in refreshed]}
                        feedback += "\nIndependently rechecked CURRENT findings (not the discarded candidate): " + json.dumps(refreshed, ensure_ascii=False)
                    except Exception as error:
                        trace[-1]["current_recheck"] = {"error": f"{type(error).__name__}: {error}"}
            if (not content_task or not content_task["issues"] or best["content_verified"]) and (not spatial_enabled or not needs_spatial(best)):
                break

    controller.update(current=current, best=best, layout_checkpoint=layout_checkpoint, feedback=feedback)
    destination = output_dir / "slide_code" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(best["html"])
    controller["written"] = best
    final_validity = render_and_measure(destination, t1_png)
    final_count = hard_issue_count(final_validity)
    ready = not needs_spatial({**best, "validity": final_validity})
    source_review_required = bool(final_validity.get("source_asset_issue_count", 0))
    status = "ready_for_human_review" if ready else "needs_repair"
    if source_review_required:
        status = "needs_source_review"
    if not spatial_enabled:
        status = "needs_evaluation"
    result = {
        "slide": source.name,
        "source": str(source),
        "model": model,
        "review_feedback": review_feedback,
        "initial_hard_issues": before_count,
        "final_hard_issues": final_count,
        "initial_issue_counts": issue_counts(before),
        "final_issue_counts": issue_counts(final_validity),
        "status": status,
        "source_review_required": source_review_required,
        "selected_attempt": best["attempt"],
        "initial_visual_review": initial_review,
        "final_visual_review": best["review"],
        "changed": best["html"] != original,
        "guard": validate_repair(best["semantic_base"], best["html"]).__dict__,
        "visual_change": visual_change_audit(t0_png, t1_png),
        "source_change": source_change_audit(original, best["html"]),
        "initial_validity": before,
        "final_validity": final_validity,
        "attempts": list(trace),
    }
    result["spatial_status"] = status
    checkpoint_path = output_dir / "layout_checkpoint" / f"{stem}_attempt_{layout_checkpoint['attempt']:02d}.html"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    if checkpoint_path.exists():
        if checkpoint_path.read_text() != layout_checkpoint["html"]:
            raise ValueError("Immutable layout checkpoint changed")
    else:
        checkpoint_path.write_text(layout_checkpoint["html"])
    result["layout_checkpoint"] = {"source": str(checkpoint_path), "sha256": probes.file_hash(checkpoint_path),
                                   "attempt": layout_checkpoint["attempt"], "review": layout_checkpoint["review"],
                                   "evaluation": layout_checkpoint["evaluation"]}
    result["attempt_budget"] = {"total": attempts, "used": controller["used"], "remaining": attempts - controller["used"],
                                "actions": dict(controller["actions"])}
    result["selected_spatial_probes"] = best["evaluation"]
    result["selected_content_report"] = best.get("content_report")
    result["content_review"] = {"status": "not_run", "reason": "spatial primitive without judge_config"}
    result["content_edit"] = {"available": bool(content_task and content_task["issues"]), "applied": best["content_changed"] and best["content_verified"],
                              "attempted": any(item.get("phase") in {"content", "joint"} for item in trace),
                              "blocked_reason": controller.get("content_blocked", ""),
                              "rolled_back": bool(controller.get("rolled_back") and not best["content_changed"]),
                              "issue_ids": list(controller["issue_ids"])}
    return result


def format_issue_transition(row):
    before = row["initial_issue_counts"]
    after = row["final_issue_counts"]
    return (f"blockers {before['repair_blocking']} -> {after['repair_blocking']}; "
            f"style advisories {before['style_advisory']} -> {after['style_advisory']}; "
            f"raw findings {before['raw_total']} -> {after['raw_total']}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_judge_arguments(parser)
    probes.add_probe_arguments(parser)
    add_repair_arguments(parser)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--dir")
    parser.add_argument("--output-dir", "--out", "-o", dest="output_dir", required=True)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--api", choices=("local", "trapi", "anthropic"), default="local")
    parser.add_argument("--attempts", type=int, default=6, help="Total candidate budget per page, shared by joint/content/layout edits and final-review reentry.")
    parser.add_argument("--review-feedback", default="", help="Visual review constraints to retain in every repair attempt")
    args = parser.parse_args(argv)

    if not 1 <= args.attempts <= 6:
        parser.error("--attempts must be between 1 and 6")

    paths = [Path(value) for value in args.files]
    if args.dir:
        paths.extend(sorted(Path(args.dir).glob("*.html")))
    paths = list(dict.fromkeys(path.resolve() for path in paths if path.is_file()))
    if not paths:
        parser.error("provide HTML files or --dir")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    jobs = [{"source": str(path), "output": str(output_dir)} for path in paths]
    report = run_repair_jobs(jobs, output_dir, args.model, max(1, args.attempts), judge_options(args),
                             review_feedback=args.review_feedback)
    for row in report:
        print(
            f"  {format_issue_transition(row)}; "
            f"changed={row['changed']}; {row['status']}",
            flush=True,
        )
    (output_dir / "repair_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Final evaluation:", {row["slide"]: row["status"] for row in report}, flush=True)
    if any(record["status"] == "error" for row in report for record in row["probe_evaluation"]["probes"]):
        raise SystemExit("Probe evaluation failed; inspect probe_evaluation reports")


if __name__ == "__main__":
    main()
