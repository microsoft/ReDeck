"""One repair session: evaluate shared snapshots, dispatch safe edits, reevaluate."""

import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from redeck_style.paths import resolve_probe_root, resolve_cases_root

from redeck_style.evaluation import probes
from redeck_style.evaluation.coordinator import find_source_run, source_context
from redeck_style.evaluation.snapshot import file_hash, load_snapshot
from redeck_style.content_repair import POLICY_VERSION, SourceCatalog, actionable_issues, content_gate, new_content_findings
from redeck_style.repair import REPAIR_POLICY
from redeck_style.execution import request_scope


def add_repair_arguments(parser):
    parser.add_argument("--content-repair", choices=("auto", "off"), default="auto",
                        help="Repair supported source-bound content findings in the shared loop; off keeps content detection only.")


def verify_report(report):
    probes.verify_snapshots(report["snapshots"])
    request_path = Path(report["report_path"]).parent / "content/request.json"
    if request_path.exists():
        request = json.loads(request_path.read_text())
        context = source_context(report["source_run"], Path(request["probe_root"]))
        if any(context[key] != request[key] for key in ("source_dir", "source_hashes", "blueprint")):
            raise ValueError("Frozen probe source context changed")


def freeze_review_pages(pages, directory):
    frozen_pages = []
    for page in pages:
        snapshot = load_snapshot(page["source"], page["png"])
        source = directory / f"slide_{page['slide_id']:02d}.html"
        if source.exists():
            raise FileExistsError("Cannot overwrite a reviewed page version")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(Path(page["source"]).read_text())
        png = source.with_suffix(".png")
        shutil.copyfile(page["png"], png)
        snapshot = {**snapshot, "source": str(source.resolve()), "png": str(png.resolve())}
        png.with_suffix(".state.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
        frozen_pages.append({**page, "source": str(source), "png": str(png)})
    return frozen_pages


def run_repair_jobs(jobs, output_dir, model, attempts, options, workers=1, review_feedback="", client_factory=None):
    from scripts import repair

    config = probes.probe_config(options)
    content_mode = options.get("content_repair", "auto")
    if content_mode not in {"auto", "off"}:
        raise ValueError("Unknown content repair mode")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    options = {**options, "request_limit_dir": str(options.get("request_limit_dir") or output_dir / "request_slots")}
    if type(options.get("request_limit", 4)) is not int or options.get("request_limit", 4) < 1:
        raise ValueError("request_limit must be a positive integer")
    if type(options.get("content_workers", 3)) is not int or not 1 <= options.get("content_workers", 3) <= 16:
        raise ValueError("content_workers must be an integer from 1 to 16")
    client_factory = client_factory or (lambda: repair.get_client(options.get("api", "local")))
    destinations = [(str(Path(job["output"]).resolve()), Path(job["source"]).name) for job in jobs]
    if len(set(destinations)) != len(destinations):
        raise ValueError("Repair jobs would overwrite the same output HTML")
    policy_files = [Path(__file__), Path(__file__).with_name("repair.py"), Path(__file__).with_name("content_repair.py"),
                    Path(__file__).resolve().parents[1] / "redeck_style/content_repair.py",
                    Path(__file__).resolve().parents[1] / "redeck_style/repair.py",
                    Path(__file__).resolve().parents[1] / "redeck_style/typography.py"]
    policy_files.extend(Path(__file__).with_name(name) for name in ("codegen.py", "content_probe_worker.py", "evaluate_scene_similarity.py"))
    policy_files.extend(Path(__file__).resolve().parents[1] / "redeck_style" / name for name in (
        "execution.py", "paths.py", "domain/editorial.py", "evaluation/editorial.py",
        "evaluation/contracts.py", "evaluation/probes.py", "evaluation/coordinator.py",
        "evaluation/snapshot.py", "evaluation/reading.py"))
    if attempts < 0:
        raise ValueError("Repair attempt budget must be nonnegative")
    session = {"repair_policy": POLICY_VERSION, "candidate_policy": REPAIR_POLICY,
               "policy_hashes": {path.name + str(index): file_hash(path) for index, path in enumerate(policy_files)},
               "model": model, "attempts": attempts, "options": options, "review_feedback": review_feedback,
               "jobs": [{**job, "source_sha256": file_hash(job["source"])} for job in jobs]}
    session = json.loads(json.dumps(session, default=str))
    manifest_path = output_dir / "probe_session.json"
    result_path = output_dir / "probe_session_result.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text()) != session:
            raise ValueError("Cannot change frozen probe session inputs/configuration")
        if not result_path.exists():
            raise ValueError("Incomplete frozen probe session; retain it and use a fresh output directory")
        saved = json.loads(result_path.read_text())
        for filename, expected in saved.get("output_hashes", {}).items():
            if file_hash(filename) != expected:
                raise ValueError("Selected repair output changed")
        for report_path in saved["reports"]:
            verify_report(json.loads(Path(report_path).read_text()))
        return saved["rows"]
    for job in jobs:
        if (Path(job["output"]) / "t0_slide_code" / Path(job["source"]).name).exists():
            raise FileExistsError("Repair T0 already exists; use a fresh output directory")
    groups = {}
    for index, job in enumerate(jobs):
        source = Path(job["source"]).resolve()
        try:
            source_run = options.get("source_run") or find_source_run(source)
        except ValueError:
            source_run = source.parent
        match = re.fullmatch(r"slide_(\d+)", source.stem)
        if not match and "content" in config["routes"]:
            raise ValueError("Content probes require original slide_NN filenames")
        slide_id = int(match.group(1)) if match else -(index + 1)
        groups.setdefault(str(Path(source_run).resolve()), []).append({**job, "slide_id": slide_id, "index": index})
    if any(len({job["slide_id"] for job in group}) != len(group) for group in groups.values()):
        raise ValueError("A source-run scope cannot contain duplicate slide IDs")
    manifest_path.write_text(json.dumps(session, ensure_ascii=False, indent=2) + "\n")
    rows = [None] * len(jobs)
    reports = []

    def reviewer(page):
        with request_scope(options["request_limit_dir"], options.get("request_limit", 4)):
            return repair.call_visual_review(client_factory(), model, Path(page["original_png"]), Path(page["png"]), page["validity"])

    for source_run, group in groups.items():
        group_options = {**options, "source_run": source_run}
        group_output = output_dir / "probe_evaluation" / probes.digest(source_run)[:16]
        pages = []
        for job in group:
            source, destination = Path(job["source"]), Path(job["output"])
            job["prepared"] = {**repair.prepare_repair(source, destination), "slide_id": job["slide_id"]}
            pages.append({"slide_id": job["slide_id"], "source": str(destination / "t0_slide_code" / source.name),
                          "png": str(destination / "t0_png" / f"{source.stem}.png")})
        print(f"Probes T0: {len(pages)} slides; routes={config['routes']}; {config['execution']}", flush=True)
        generation_report = Path(source_run) / "content_review/report.json"
        generation_baseline = {"routes": {"content": json.loads(generation_report.read_text())}} if generation_report.exists() else None
        initial = probes.evaluate_pages(pages, group_output / "t0", group_options, reviewer, model, generation_baseline)
        reports.append(initial["report_path"])
        content_issues = initial["routes"]["content"].get("issues", [])
        catalog = None
        content_enabled = "content" in config["routes"] and content_mode == "auto"
        source_error = ""
        controllers = {job["slide_id"]: {} for job in group}

        def ensure_catalog(evaluation):
            nonlocal catalog, source_error
            findings = evaluation["routes"]["content"].get("issues", [])
            if catalog or source_error or not content_enabled or not any(actionable_issues(findings, job["slide_id"]) for job in group):
                return
            try:
                probe_root = resolve_probe_root(options.get("probe_root"))
                catalog = SourceCatalog(source_context(source_run, probe_root))
            except Exception as error:
                source_error = f"Content repair requires frozen source evidence: {type(error).__name__}: {error}"

        ensure_catalog(initial)
        if content_issues:
            print(f"Content: {len(content_issues)} finding(s); repair={content_mode}; source={'ready' if catalog else 'unavailable/not required'}", flush=True)

        def repair_one(job, evaluation=initial, evaluation_pages=pages, publish_only=False):
            started = time.time()
            controller = controllers[job["slide_id"]]
            initial_spatial = initial["routes"]["spatial"].get("pages", {}).get(str(job["slide_id"]))
            if "spatial" not in config["routes"]:
                initial_spatial = {"review": {"verdict": "not_run", "issues": [], "valid": False}, "probes": []}
            elif initial_spatial is None:
                initial_spatial = {"review": {"verdict": "uncertain", "issues": [], "valid": False}, "probes": []}
            findings = evaluation["routes"]["content"].get("issues", [])
            issues = actionable_issues(findings, job["slide_id"])
            task = {"issues": issues, "catalog": catalog, "baseline": evaluation} if content_enabled and catalog else None
            cache_report = evaluation

            def evaluate_candidate(candidate_html, candidate_png, attempt, label="candidate"):
                nonlocal cache_report
                verify_report(initial)
                verify_report(evaluation)
                verify_report(cache_report)
                candidate_pages = [{**page, "original_png": page.get("original_png", page["png"]),
                                    **({"source": str(candidate_html), "png": str(candidate_png)}
                                       if page["slide_id"] == job["slide_id"] else {})} for page in evaluation_pages]
                report = probes.evaluate_pages(candidate_pages,
                    group_output / f"slide_{job['slide_id']:02d}_{label}_{attempt:02d}", group_options, reviewer, model, cache_report)
                reports.append(report["report_path"])
                verify_report(initial)
                verify_report(report)
                cache_report = report
                return report

            def evaluate_current(state, attempt):
                snapshot = json.loads(Path(state["png"]).with_suffix(".state.json").read_text())
                source = Path(snapshot["source"])
                if source.read_text() != state["html"]:
                    raise ValueError("CURRENT recheck source does not match the working state")
                return evaluate_candidate(source, state["png"], attempt, "current")

            with request_scope(options["request_limit_dir"], options.get("request_limit", 4)):
                row = repair.repair_slide(client_factory() if "spatial" in config["routes"] or task else None, model,
                                     Path(job["source"]), Path(job["output"]), attempts, review_feedback,
                                     prepared=job["prepared"], initial_spatial=initial_spatial,
                                     content_task=task, candidate_evaluator=evaluate_candidate if task else None,
                                     controller=controller, step_limit=0 if publish_only else None,
                                     current_evaluator=evaluate_current if task else None)
            row["content_edit"].update(enabled=content_enabled, source_error=source_error,
                                       pending_unsupported_ids=[issue.get("issue_id") for issue in findings
                                           if job["slide_id"] in issue.get("affected_slides", []) and issue not in issues])
            controller["elapsed_seconds"] = controller.get("elapsed_seconds", 0) + time.time() - started
            controller["invocations"] = controller.get("invocations", 0) + 1
            row["elapsed_seconds"] = round(controller["elapsed_seconds"], 1)
            row["finalization"] = list(controller.get("finalization", []))
            partial = group_output / "spatial_results" / f"slide_{job['slide_id']:02d}_pass_{controller['invocations']:02d}.json"
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
            return row

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            group_rows = list(pool.map(repair_one, group))
        final_pages = [{"slide_id": job["slide_id"],
                        "source": str(Path(job["output"]) / "slide_code" / Path(job["source"]).name),
                        "png": str(Path(job["output"]) / "t1_png" / f"{Path(job['source']).stem}.png"),
                        "original_png": page["png"]} for job, page in zip(group, pages)]
        baseline = {"routes": {**initial["routes"], "spatial": {
            "api": options.get("api", "local"),
            "pages": {str(job["slide_id"]): row["selected_spatial_probes"] for job, row in zip(group, group_rows)}}}}
        selected_content = next((row["selected_content_report"] for row in reversed(group_rows)
                                 if row["content_edit"]["applied"] and row.get("selected_content_report")), None)
        if selected_content:
            candidate_report = json.loads(Path(selected_content).read_text())
            verify_report(candidate_report)
            baseline["routes"]["content"] = candidate_report["routes"]["content"]
        verify_report(initial)
        print(f"Probes T1: {len(pages)} slides; reuse only matching inputs", flush=True)
        final_round = 0
        while True:
            review_pages = freeze_review_pages(final_pages, group_output / "joint_candidate" / f"round_{final_round:02d}")
            report_dir = "t1" if final_round == 0 else f"t1_round_{final_round:02d}"
            final = probes.evaluate_pages(review_pages, group_output / report_dir, group_options, reviewer, model, baseline)
            reports.append(final["report_path"])
            verify_report(final)
            ensure_catalog(final)
            findings = final["routes"]["content"].get("issues", [])
            unsafe_pages = set()
            pending = []
            for index, (job, row, page) in enumerate(zip(group, group_rows, review_pages)):
                controller = controllers[job["slide_id"]]
                spatial = final["routes"]["spatial"].get("pages", {}).get(str(job["slide_id"]))
                content_ok = content_gate(final, job["slide_id"])[0] if "content" in config["routes"] else False
                spatial_ok = "spatial" not in config["routes"] or bool(spatial and spatial["review"].get("valid") and not repair.needs_spatial(spatial))
                if row["content_edit"]["applied"] and (not (content_ok and spatial_ok) or new_content_findings(initial, final, job["slide_id"])):
                    unsafe_pages.add(index)
                repair.refresh_repair_controller(controller, page, spatial, content_ok)
                content_pending = content_enabled and catalog and actionable_issues(findings, job["slide_id"])
                if controller["used"] < attempts and (not spatial_ok or content_pending):
                    pending.append(index)
            used_before = sum(controller["used"] for controller in controllers.values())

            def resume(index):
                job = group[index]
                controller = controllers[job["slide_id"]]
                controller.setdefault("finalization", []).append({"round": final_round, "action": "reenter",
                    "used_before": controller["used"], "report": final["report_path"]})
                row = repair_one(job, final, review_pages)
                if group_rows[index]["content_edit"]["applied"] and not row["content_edit"]["applied"]:
                    controller["rolled_back"] = True
                    controller["finalization"].append({"round": final_round, "action": "fallback", "report": final["report_path"]})
                    row["content_edit"]["rolled_back"] = True
                    row["finalization"] = list(controller["finalization"])
                return index, row

            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                for index, row in pool.map(resume, pending):
                    group_rows[index] = row
            progressed = sum(controller["used"] for controller in controllers.values()) > used_before
            changed_selection = any(Path(page["source"]).read_text() != Path(frozen["source"]).read_text()
                                    for page, frozen in zip(final_pages, review_pages))
            if progressed or changed_selection:
                baseline = final
                final_round += 1
                continue
            if unsafe_pages:
                for index, (job, row) in enumerate(zip(group, group_rows)):
                    if index not in unsafe_pages or not row["content_edit"]["applied"]:
                        continue
                    checkpoint = row["layout_checkpoint"]
                    if file_hash(checkpoint["source"]) != checkpoint["sha256"]:
                        raise ValueError("Accepted layout checkpoint changed")
                    fallback = Path(checkpoint["source"]).read_text()
                    if not repair.validate_repair(job["prepared"]["original"], fallback).accepted:
                        raise ValueError("Layout checkpoint does not preserve original content")
                    controller = controllers[job["slide_id"]]
                    controller.update(current=controller["layout_checkpoint"], best=controller["layout_checkpoint"], rolled_back=True,
                                      content_blocked="Joint evaluation rejected content edits; preserve layout and continue spatial work only")
                    controller.setdefault("finalization", []).append({"round": final_round, "action": "rollback", "report": final["report_path"]})
                    group_rows[index] = repair_one(job, final, review_pages, publish_only=True)
                baseline = final
                final_round += 1
                continue
            break
        verify_report(final)
        if catalog:
            catalog.verify()
        for job, row in zip(group, group_rows):
            final_spatial = final["routes"]["spatial"].get("pages", {}).get(str(job["slide_id"]))
            if final_spatial:
                row["final_visual_review"] = final_spatial["review"]
                row["final_validity"] = final_spatial["validity"]
                row["final_hard_issues"] = repair.hard_issue_count(final_spatial["validity"])
                row["selected_spatial_probes"] = final_spatial
            probes.apply_evaluation(row, job["slide_id"], initial, final)
            rows[job["index"]] = row
    output_hashes = {str(path.resolve()): file_hash(path) for job in jobs for path in (
        Path(job["output"]) / "slide_code" / Path(job["source"]).name,
        Path(job["output"]) / "t1_png" / (Path(job["source"]).stem + ".png"))}
    output_hashes.update({str(Path(row["layout_checkpoint"]["source"]).resolve()): row["layout_checkpoint"]["sha256"] for row in rows})
    result_path.write_text(json.dumps({"rows": rows, "reports": reports, "output_hashes": output_hashes}, ensure_ascii=False, indent=2) + "\n")
    return rows
