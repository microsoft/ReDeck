"""Snapshot-bound spatial and content probes with one configurable scheduler."""

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import coordinator
from .contracts import digest, summarize_records
from .snapshot import file_hash, load_snapshot
from .editorial import EDITORIAL_PROBE_ID, content_remediation


ROUTES = ("spatial", "content")
SPATIAL_CHECKS = {
    "overflow": "overflow_roles",
    "text_clip": "clipped_roles",
    "table_cell_overflow": "table_cell_overflow_details",
    "text_collision": "text_collision_details",
    "graphic_text_collision": "graphic_text_collision_details",
    "connector_rule_collision": "connector_rule_collision_details",
    "connector_occlusion": "connector_occlusion_details",
    "graphic_text_clearance": "graphic_text_clearance_details",
    "text_clearance": "text_clearance_details",
    "text_association": "text_association_details",
    "low_contrast": "low_contrast_details",
    "gradient_violation": "gradient_roles",
    "source_asset_issue": "source_asset_issue_details",
}
SPATIAL_PROBES = tuple(f"spatial.{name}" for name in SPATIAL_CHECKS) + ("spatial.visual",)


def add_probe_arguments(parser):
    parser.add_argument("--probe-routes", nargs="+", choices=ROUTES, default=None,
                        help="Enabled evaluation routes (default: spatial content). Disabled routes remain not_run.")
    parser.add_argument("--probe-execution", choices=("parallel", "serial"), default="parallel",
                        help="Schedule enabled probe routes concurrently or serially on the same snapshot.")


def probe_config(options):
    routes = options.get("routes")
    if routes is None:
        routes = ["spatial"] if options.get("mode") == "off" else list(ROUTES)
    if not routes or len(routes) != len(set(routes)) or set(routes) - set(ROUTES):
        raise ValueError("Probe routes must be unique spatial/content routes")
    if options.get("mode") == "off" and "content" in routes:
        raise ValueError("judge-mode=off conflicts with the content probe route")
    execution = options.get("execution", "parallel")
    if execution not in {"parallel", "serial"}:
        raise ValueError("Unknown probe execution mode")
    return {"routes": [route for route in ROUTES if route in routes], "execution": execution}


def normalize_record(record, route):
    result = copy.deepcopy(record)
    result["route"] = route
    result.setdefault("execution", "not_run" if result["status"] in {"not_run", "skipped"} else "executed")
    issues = []
    for original in result.get("issues", []):
        issue = {**original, "probe_id": result["probe_id"], "route": route}
        issue.setdefault("affected_slides", result.get("scope_slide_ids", []))
        issue.setdefault("severity", "major")
        issue.setdefault("evidence", {"description": issue.get("description", issue.get("issue_type", "Probe finding"))})
        issue["remediation"] = ("content_revision" if route == "content" else
                                "source_review" if result["probe_id"] == "spatial.source_asset_issue" else
                                "style_review" if result["probe_id"] == "spatial.gradient_violation" else "spatial_repair")
        if route == "content" and issue.get("observation_status") == "unconfirmed":
            issue["remediation"] = "content_observation"
        issues.append(issue)
    result["issues"] = issues
    return result


def spatial_records(validity, review, slide_id):
    records = []
    for name, details_key in SPATIAL_CHECKS.items():
        count = validity.get(f"{name}_count", 0)
        issues = []
        if count:
            issues.append({"issue_type": name, "count": count, "affected_slides": [slide_id],
                           "evidence": {"description": f"{count} measured {name} finding(s)",
                                        "details": validity.get(details_key, [])},
                           "remediation": "source_review" if name == "source_asset_issue" else "spatial_repair"})
        records.append(normalize_record({"probe_id": f"spatial.{name}", "scope_slide_ids": [slide_id],
                                         "requires_source": False, "requires_vision": False,
                                         "status": "failed" if issues else "passed", "issues": issues}, "spatial"))
    valid = (review.get("valid", False) and review.get("verdict") in {"pass", "revise"}
             and bool(review.get("issues")) == (review.get("verdict") == "revise"))
    records.append(normalize_record({"probe_id": "spatial.visual", "scope_slide_ids": [slide_id],
                                     "requires_source": False, "requires_vision": True,
                                     "status": ("failed" if review.get("issues") else "passed") if valid else "error",
                                     "reason": review.get("error", "") if valid else review.get("error", "Uncertain visual review"),
                                     "issues": review.get("issues", [])}, "spatial"))
    return records


def spatial_input_hash(page, model):
    original = Path(page.get("original_png", page["png"]))
    root = Path(__file__).resolve().parents[1]
    policy = [file_hash(path) for path in (Path(__file__), root / "repair.py", root / "typography.py", root / "execution.py",
                                         root.parent / "scripts/repair.py", root.parent / "scripts/codegen.py")]
    return digest({"html": page["html_sha256"], "png": page["png_sha256"],
                   "validity": page["validity"], "original_png": file_hash(original),
                   "model": model, "policy": policy})


def spatial_result(page, review, model):
    result = {"validity": page["validity"], "review": review,
              "probes": spatial_records(page["validity"], review, page["slide_id"]),
              "input_sha256": spatial_input_hash(page, model)}
    for record in result["probes"]:
        record["input_sha256"] = result["input_sha256"]
    return result


def summarize(records):
    complete = bool(records) and all(record["status"] in {"passed", "failed"} for record in records)
    return summarize_records(records, complete)


def spatial_route(pages, reviewer, model, baseline=None):
    previous = (baseline or {}).get("pages", {})
    results = {}
    for page in pages:
        cached = previous.get(str(page["slide_id"]))
        if (cached and cached.get("input_sha256") == spatial_input_hash(page, model)
                and all(record["status"] in {"passed", "failed"} for record in cached["probes"])):
            result = copy.deepcopy(cached)
            for record in result["probes"]:
                record.update(execution="reused", reused_from=(baseline or {}).get("report_path", "selected spatial draft"))
        else:
            try:
                review = reviewer(page)
            except Exception as error:
                review = {"verdict": "uncertain", "valid": False, "issues": [],
                          "error": f"{type(error).__name__}: {error}"}
            result = spatial_result(page, review, model)
        results[str(page["slide_id"])] = result
    return {**summarize([record for result in results.values() for record in result["probes"]]), "pages": results}


def route_failure(route, pages, status, reason):
    scopes = [[page["slide_id"]] for page in pages] if route == "spatial" else [[page["slide_id"] for page in pages]]
    identifiers = SPATIAL_PROBES if route == "spatial" else (*coordinator.DEFAULT_PROBES, EDITORIAL_PROBE_ID)
    return summarize([normalize_record({"probe_id": probe_id, "scope_slide_ids": scope,
                                        "status": status, "reason": reason, "issues": []}, route)
                      for scope in scopes for probe_id in identifiers])


def snapshot_inputs(pages):
    return [{key: page[key] for key in ("slide_id", "source", "png", "html_sha256", "png_sha256",
                                       "original_png", "original_png_sha256")} for page in pages]


def verify_snapshots(pages):
    for page in pages:
        if file_hash(page["source"]) != page["html_sha256"] or file_hash(page["png"]) != page["png_sha256"]:
            raise ValueError("Probe snapshot changed during evaluation; use a fresh run")
        if page.get("original_png_sha256") and file_hash(page["original_png"]) != page["original_png_sha256"]:
            raise ValueError("Original reference snapshot changed during evaluation")


def evaluate_pages(pages, output_dir, options, reviewer, spatial_model, baseline=None):
    started = time.monotonic()
    config = probe_config(options)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    snapshots = []
    for page in pages:
        snapshot = load_snapshot(page["source"], page["png"],
                                 fallback_png=output_dir / "snapshots" / f"slide_{page['slide_id']:02d}.png")
        original_png = page.get("original_png", snapshot["png"])
        snapshots.append({**snapshot, "slide_id": page["slide_id"],
                          "original_png": original_png, "original_png_sha256": file_hash(original_png)})
    if not snapshots or len({page["slide_id"] for page in snapshots}) != len(snapshots):
        raise ValueError("Probe evaluation requires nonempty, unique slide IDs")
    verify_snapshots(snapshots)
    snapshot_seconds = time.monotonic() - started
    route_seconds = {}
    previous = (baseline or {}).get("routes", {}) if options.get("cache_enabled", True) else {}

    def run_route(route):
        route_started = time.monotonic()
        if route not in config["routes"]:
            return route_failure(route, snapshots, "not_run", "Probe route explicitly disabled")
        try:
            if route == "spatial":
                cached = previous.get(route)
                if cached and cached.get("api", "local") != options.get("api", "local"):
                    cached = None
                return {**spatial_route(copy.deepcopy(snapshots), reviewer, spatial_model, cached),
                        "api": options.get("api", "local")}
            content = coordinator.review_pages(copy.deepcopy(snapshots), output_dir / "content", options,
                                               baseline=previous.get(route))
            records = [normalize_record(record, route) for record in content["probes"]]
            return {**content, **summarize(records), "coverage_complete": content["coverage_complete"]}
        except Exception as error:
            return route_failure(route, snapshots, "error", f"{type(error).__name__}: {error}")
        finally:
            route_seconds[route] = time.monotonic() - route_started

    if config["execution"] == "parallel":
        with ThreadPoolExecutor(max_workers=len(ROUTES)) as pool:
            futures = {route: pool.submit(run_route, route) for route in ROUTES}
            routes = {route: future.result() for route, future in futures.items()}
    else:
        routes = {route: run_route(route) for route in ROUTES}
    try:
        verify_snapshots(snapshots)
    except Exception as error:
        routes = {route: route_failure(route, snapshots, "error", str(error)) for route in ROUTES}
    report = {"schema_version": "2.0", "configuration": config, "source_run": str(options.get("source_run", "")),
              "scope_slide_ids": [page["slide_id"] for page in snapshots],
              "snapshots": snapshot_inputs(snapshots), "routes": routes,
              **summarize([record for route in routes.values() for record in route["probes"]])}
    report["coverage_complete"] = all(route["coverage_complete"] for route in routes.values())
    if not report["coverage_complete"] and report["status"] == "passed":
        report["status"] = "incomplete"
    report["report_path"] = str((output_dir / "report.json").resolve())
    report["timings"] = {"snapshot_seconds": snapshot_seconds, "route_seconds": route_seconds,
                         "total_seconds": time.monotonic() - started}
    Path(report["report_path"]).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def apply_evaluation(row, slide_id, initial, final):
    issues = [issue for issue in final["issues"] if slide_id in issue["affected_slides"]]
    scoped = [record for record in final["probes"] if slide_id in record["scope_slide_ids"]]
    complete = final["coverage_complete"] and all(record["status"] in {"passed", "failed"} for record in scoped)
    spatial_issues = [issue for issue in issues if issue["route"] == "spatial"]
    spatial_records_scoped = [record for record in scoped if record["route"] == "spatial"]
    if any(issue["remediation"] == "source_review" for issue in spatial_issues):
        spatial = "needs_source_review"
    elif not spatial_records_scoped or any(record["status"] not in {"passed", "failed"} for record in spatial_records_scoped):
        spatial = "needs_evaluation"
    else:
        spatial = "needs_repair" if any(issue["remediation"] == "spatial_repair" for issue in spatial_issues) else "ready_for_human_review"
    row["spatial_status"] = spatial
    from redeck_style.repair import issue_counts
    for phase, evaluation in (("initial", initial), ("final", final)):
        page = evaluation["routes"]["spatial"].get("pages", {}).get(str(slide_id))
        if page:
            row[f"{phase}_issue_counts"] = issue_counts(page["validity"])
    handlers = {issue["remediation"] for issue in issues}
    if "source_review" in handlers or spatial == "needs_source_review":
        status = "needs_source_review"
    elif "content_revision" in handlers:
        status = "needs_content_revision"
    elif not complete:
        status = "needs_evaluation"
    elif "spatial_repair" in handlers:
        status = "needs_repair"
    else:
        status = spatial
    content = final["routes"]["content"]
    content_issues = [issue for issue in issues if issue["route"] == "content"]
    row.update(status=status,
               content_review={"status": ("not_run" if "content" not in final["configuration"]["routes"] else
                                          "failed" if any(issue.get("observation_status") != "unconfirmed" for issue in content_issues)
                                          else "incomplete" if content_issues else "passed" if content["coverage_complete"] else "incomplete"),
                               "coverage_complete": content["coverage_complete"], "issues": content_issues,
                               "remediation": content_remediation(content_issues, content["coverage_complete"],
                                                                  "content" in final["configuration"]["routes"], row.get("content_edit")),
                               "initial_report": initial["report_path"], "final_report": final["report_path"]},
               probe_evaluation={"initial_report": initial["report_path"], "final_report": final["report_path"],
                                 "coverage_complete": complete, "issues": issues, "probes": scoped})
