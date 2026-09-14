"""One source-review contract; no second visual judge or repair orchestrator."""

import json
import hashlib
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

from redeck_style.paths import resolve_probe_root, resolve_cases_root
from .snapshot import SNAPSHOT_SCHEMA, file_hash, load_snapshot
from .contracts import summarize_records
from .editorial import EDITORIAL_PROBE_ID, content_remediation, editorial_probe


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROBES = tuple([f"C{index:02d}" for index in range(1, 6)]
                       + [f"D{index:02d}" for index in range(1, 7)]
                       + [f"E{index:02d}" for index in range(1, 5)])


def add_judge_arguments(parser):
    parser.add_argument("--judge-mode", choices=("content", "off"), default="content",
                        help="C/D/E and local editorial-copy checks by default; off is unevaluated. Repair editing is controlled separately.")
    parser.add_argument("--judge-model", default="gpt-5.5")
    parser.add_argument("--content-workers", type=int, default=3, help="Bounded concurrent content probes; 1 is serial.")
    parser.add_argument("--request-limit", type=int, default=4, help="Shared in-flight model request limit per repair session.")
    parser.add_argument("--probe-cache", choices=("on", "off"), default="on")
    parser.add_argument("--probe-root", "--legacy-root", dest="probe_root", type=Path, default=None,
                        help="Optional trusted probe checkout; bundled probes are the default.")
    parser.add_argument("--judge-python", type=Path, default=None)
    parser.add_argument("--source-run", type=Path, default=None,
                        help="Generation run containing source context, for imported Repair HTML.")


def judge_options(args):
    options = {"mode": args.judge_mode, "model": args.judge_model,
            "probe_root": args.probe_root, "python": args.judge_python,
            "source_run": args.source_run, "api": getattr(args, "api", "local"),
            "content_workers": getattr(args, "content_workers", 3), "request_limit": getattr(args, "request_limit", 4),
            "cache_enabled": getattr(args, "probe_cache", "on") == "on"}
    if hasattr(args, "probe_routes"):
        options.update(routes=args.probe_routes, execution=args.probe_execution)
    if hasattr(args, "content_repair"):
        options["content_repair"] = args.content_repair
    return options


def find_source_run(source):
    for parent in Path(source).resolve().parents:
        if (parent / "run_manifest.json").exists():
            return parent
    raise ValueError("No generation run context; supply --source-run")


def manifest_path(value, run_path):
    path = Path(value)
    if path.is_absolute():
        return path
    local = run_path / path
    packaged = ROOT / path
    return local if local.exists() or not packaged.exists() else packaged


def source_context(run_path, probe_root):
    run_path = Path(run_path).resolve()
    manifest = json.loads((run_path / "run_manifest.json").read_text())
    context_path = run_path / "judge_context.json"
    if context_path.exists():
        context = json.loads(context_path.read_text())
        blueprint = context["blueprint"]
        source_dir = manifest_path(context["source_dir"], run_path)
        if source_hashes(source_dir) != context["source_hashes"]:
            raise ValueError("Source changed since generation")
    else:
        blueprint_path = manifest_path(manifest["blueprint"], run_path)
        blueprint = json.loads(blueprint_path.read_text())
        source_dir = manifest_path(manifest.get("source_dir", resolve_cases_root() / manifest["case"] / "source_pack"), run_path)
    if not (source_dir / "paper_full.md").is_file():
        raise ValueError("Source paper_full.md is unavailable")
    return {"case_id": manifest["case"], "blueprint": blueprint,
            "source_dir": str(source_dir.resolve()), "source_hashes": source_hashes(source_dir),
            "context_origin": "generation-snapshot" if context_path.exists() else "legacy-manifest-adapter"}


def source_hashes(source_dir):
    source_dir = Path(source_dir)
    files = [source_dir / "paper_full.md"]
    for directory in ("figures", "tables"):
        files.extend(path for path in (source_dir / directory).glob("*") if path.is_file())
    return {str(path.relative_to(source_dir)): file_hash(path) for path in sorted(files)}


def save_source_context(out_dir, source_dir, blueprint):
    payload = {"source_dir": str(Path(source_dir).resolve()), "blueprint": blueprint,
               "source_hashes": source_hashes(source_dir)}
    (Path(out_dir) / "judge_context.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def summarize_review(records, requested_probes):
    incomplete = [record for record in records if record["status"] not in {"passed", "failed"}]
    recorded_ids = [record["probe_id"] for record in records]
    complete = (set(requested_probes) == set(DEFAULT_PROBES) and not incomplete
                and len(recorded_ids) == len(set(recorded_ids))
                and set(recorded_ids) == set(requested_probes))
    return summarize_records(records, complete)


def combine_status(spatial_status, content_review):
    if spatial_status == "needs_source_review":
        return spatial_status
    if any(issue.get("observation_status") != "unconfirmed" for issue in content_review.get("issues", [])):
        return "needs_content_revision"
    if content_review.get("issues"):
        return "needs_evaluation"
    if content_review.get("status") != "passed" or not content_review.get("coverage_complete"):
        return "needs_evaluation"
    return spatial_status


def review_pages(pages, output_dir, options=None, baseline=None):
    options = options or {}
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    requested = tuple(options.get("probes") or DEFAULT_PROBES)
    if len(set(requested)) != len(requested) or set(requested) - set(DEFAULT_PROBES):
        raise ValueError("Unknown or duplicate content probe IDs")
    report = {"schema_version": "1.0", "model": options.get("model", "gpt-5.5"),
              "requested_probes": list(requested), "requested_local_probes": [EDITORIAL_PROBE_ID],
              "scope_slide_ids": [page["slide_id"] for page in pages]}
    snapshots = []
    local_record = {"probe_id": EDITORIAL_PROBE_ID, "scope_slide_ids": report["scope_slide_ids"],
                    "requires_source": False, "requires_vision": False, "status": "not_run", "execution": "not_run",
                    "reason": "explicit judge-mode=off", "issues": []}
    try:
        if options.get("mode", "content") == "off":
            report.update(summarize_review([
                {"probe_id": probe, "status": "not_run", "reason": "explicit judge-mode=off", "issues": []}
                for probe in requested], requested))
        else:
            probe_root = resolve_probe_root(options.get("probe_root"))
            default_python = sys.executable
            python = Path(options.get("python") or os.environ.get("REDECK_JUDGE_PYTHON", default_python))
            for page in pages:
                if (page.get("schema_version") == SNAPSHOT_SCHEMA and "objects" in page
                        and page.get("html_sha256") == file_hash(page["source"])
                        and page.get("png_sha256") == file_hash(page["png"])):
                    snapshot = page
                else:
                    snapshot = load_snapshot(page["source"], page["png"],
                                             fallback_png=output_dir / "snapshots" / f"slide_{page['slide_id']:02d}.png")
                snapshots.append({**snapshot, "slide_id": page["slide_id"]})
            local_record = editorial_probe(snapshots)
            source_run = options.get("source_run") or find_source_run(pages[0]["source"])
            context = source_context(source_run, probe_root)
            request = {**report, **context, "pages": snapshots, "probe_root": str(probe_root),
                       "api": options.get("api", "local"), "baseline": baseline,
                       "content_workers": options.get("content_workers", 3),
                       "request_limit": options.get("request_limit", 4),
                       "request_limit_dir": str(options.get("request_limit_dir") or output_dir / "request_slots"),
                       "cache_enabled": options.get("cache_enabled", True),
                       "output_dir": str(output_dir)}
            request_path = output_dir / "request.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n")
            command = [str(python), str(ROOT / "scripts/content_probe_worker.py"), str(request_path)]
            with (output_dir / "worker.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=options.get("timeout", 1800))
            result = json.loads((output_dir / "result.json").read_text())
            report.update(result)
            report.update(summarize_review(result["probes"], requested))
    except Exception as error:
        if local_record["status"] == "not_run":
            local_record.update(status="error", execution="not_run", reason=f"{type(error).__name__}: {error}")
        report.update(summarize_review([
            {"probe_id": probe, "status": "error", "reason": f"{type(error).__name__}: {error}", "issues": []}
            for probe in requested], requested))
    report.update(summarize_records([*report["probes"], local_record],
                                   report["coverage_complete"] and local_record["status"] in {"passed", "failed"}))
    report["remediation"] = content_remediation(report["issues"], report["coverage_complete"], options.get("mode", "content") != "off")
    report["report_path"] = str(output_dir / "report.json")
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def review_run(run_path, output_dir, options=None):
    run_path = Path(run_path).resolve()
    options = {**(options or {}), "source_run": run_path}
    selected = options.get("slides")
    pages = []
    for source in sorted((run_path / "slide_code").glob("slide_*.html")):
        match = re.fullmatch(r"slide_(\d+)", source.stem)
        if match and (not selected or int(match.group(1)) in selected):
            existing_png = run_path / "slide_png" / f"{source.stem}.png"
            png = Path(output_dir).resolve() / "snapshots" / f"{source.stem}.png"
            state_path = existing_png.with_suffix(".state.json")
            if state_path.exists() and existing_png.exists():
                state = json.loads(state_path.read_text())
                if (state.get("schema_version") == SNAPSHOT_SCHEMA and state.get("html_sha256") == file_hash(source)
                        and state.get("png_sha256") == file_hash(existing_png)):
                    png = existing_png
            pages.append({"slide_id": int(match.group(1)), "source": str(source),
                          "png": str(png)})
    if not pages:
        raise ValueError("No matching HTML pages to review")
    if selected and {page["slide_id"] for page in pages} != set(selected):
        raise ValueError("Some requested slide IDs have no generated HTML")
    return review_pages(pages, output_dir, options)


def review_repair_batch(jobs, output_dir, options):
    warnings.warn("review_repair_batch is a legacy content-only adapter; use run_repair_jobs for unified evaluation",
                  DeprecationWarning, stacklevel=2)
    if options.get("mode", "content") == "off":
        report_dir = Path(output_dir) / "content_review" / "disabled"
        report_path = report_dir / "report.json"
        content = (json.loads(report_path.read_text()) if report_path.exists()
                   else review_pages([], report_dir, options))
        for job in jobs:
            row = job["row"]
            row["spatial_status"] = row.get("spatial_status", row["status"])
            row["status"] = combine_status(row["spatial_status"], content)
            row["content_review"] = {"status": "not_run", "report": content["report_path"]}
        summaries = [{"status": "not_run", "errors": 0, "report": content["report_path"]}]
        (Path(output_dir) / "evaluation.json").write_text(json.dumps(summaries, indent=2) + "\n")
        return summaries
    groups = {}
    for job in jobs:
        try:
            source_run = options.get("source_run") or find_source_run(job["source"])
        except ValueError:
            source_run = Path(job["source"]).parent
        groups.setdefault(str(Path(source_run).resolve()), []).append(job)
    summaries = []
    for source_run, group in sorted(groups.items()):
        group_id = hashlib.sha256(source_run.encode()).hexdigest()[:16]
        group_output = Path(output_dir) / "content_review" / group_id
        initial = None
        for stage in ("t0", "t1"):
            pages = []
            for job in group:
                source = Path(job["source"])
                match = re.fullmatch(r"slide_(\d+)", source.stem)
                if not match:
                    raise ValueError("Content review requires original slide_NN filenames")
                destination = Path(job["output"])
                html_dir = "t0_slide_code" if stage == "t0" else "slide_code"
                pages.append({"slide_id": int(match.group(1)),
                              "source": str(destination / html_dir / source.name),
                              "png": str(destination / f"{stage}_png" / f"{source.stem}.png")})
            report_dir = group_output / stage
            report_path = report_dir / "report.json"
            if report_path.exists():
                request_path = report_dir / "request.json"
                if request_path.exists():
                    request = json.loads(request_path.read_text())
                    for filename, expected in request["source_hashes"].items():
                        if file_hash(Path(request["source_dir"]) / filename) != expected:
                            raise ValueError("Frozen review source changed; use a new run")
                    for page in request["pages"]:
                        if file_hash(page["source"]) != page["html_sha256"] or file_hash(page["png"]) != page["png_sha256"]:
                            raise ValueError("Frozen review page changed; use a new run")
                content = json.loads(report_path.read_text())
                if content["scope_slide_ids"] != [page["slide_id"] for page in pages]:
                    raise ValueError("Cannot change the frozen content-review scope")
            else:
                content = review_pages(pages, report_dir, {**options, "source_run": source_run}, baseline=initial)
            if stage == "t0":
                initial = content
        for job in group:
            slide_id = int(re.fullmatch(r"slide_(\d+)", Path(job["source"]).stem).group(1))
            scoped = {**content, "issues": [issue for issue in content["issues"] if slide_id in issue.get("affected_slides", [])]}
            if not scoped["issues"] and scoped["coverage_complete"]:
                scoped["status"] = "passed"
            row = job["row"]
            row["spatial_status"] = row.get("spatial_status", row["status"])
            row["status"] = combine_status(row["spatial_status"], scoped)
            row["content_review"] = {"initial_report": initial["report_path"], "final_report": content["report_path"],
                                     "status": scoped["status"], "coverage_complete": scoped["coverage_complete"],
                                     "issues": scoped["issues"]}
        summaries.append({"source_run": source_run, "scope_slide_ids": content["scope_slide_ids"],
                          "status": content["status"], "report": content["report_path"],
                          "errors": sum(record["status"] == "error" for record in content["probes"])})
    (Path(output_dir) / "evaluation.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n")
    return summaries
