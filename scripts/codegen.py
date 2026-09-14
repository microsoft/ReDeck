#!/usr/bin/env python3
"""ReDeck slide codegen — unified pipeline.

One prompt, one pipeline, all models. No per-model adaptation.

Design principles:
  1. One bounded creative brief per page — no parallel StyleSpec/Scene blocks
  2. Code-first — typed executable vocab instead of image references
  3. The planner controls intent and constraints; the model owns final geometry
  4. Per-slide evidence — only must_cover + assigned figure, not full paper
  5. Parallel realization after deterministic sequential planning

Usage:
    python3 scripts/codegen.py --help
    python3 scripts/codegen.py --case content_repair_smoke --model gpt-5.5 \\
        --blueprint examples/validation/content_repair_smoke/blueprint.json
"""

import argparse, json, os, re, shutil, subprocess, sys, time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redeck_style.paths import resolve_probe_root, resolve_cases_root
from redeck_style.domain.constraints import MIN_BODY_PX, MIN_LABEL_PX, MIN_TEXT_CONTRAST
from redeck_style.domain.editorial import ART_DIRECTION, EDITORIAL_COPY_POLICY
from redeck_style.domain.asset_presentation import ASSET_MODES
from redeck_style.execution import request_slot
from redeck_style.validation.source_assets import audit_source_assets
from redeck_style.evaluation.coordinator import (
    add_judge_arguments, combine_status, judge_options, review_run, save_source_context,
)

# ── System prompt: code-first, model-agnostic ──

SYSTEM_PROMPT = """You are the art director and HTML implementer for 1280×720 presentation slides. The user may request one slide or a small coordinated group.
Use static HTML/CSS and inline SVG only. Page JavaScript and HTTP(S) resource requests are disabled during rendering. Use installed font stacks and the supplied source assets; do not depend on remote fonts, libraries, images, or scripts.

## Critical Rules
1. Design the entire page holistically. The design kernel is material and rhythm, not a checklist of components. Choose the final geometry and rewrite selectors freely.
2. Use the supplied palette semantically. Every visible color (text, fill, stroke, border, shadow, gradient) must use the supplied CSS variables or color-mix derived from them; never hard-code hex, rgb, named black, or named white. The palette is available capacity, not a requirement to use every hue. Start with neutral ink and primary accent; secondary/tertiary distinguish explicitly named data series or categories, not arbitrary boxes or mark shapes. Keep the same series color across bars, dots, lines and slides. Reserve signal for a meaningful exception. Source figure colors and legends remain unchanged; surrounding annotations should not introduce a competing palette. Text on the canvas must use `var(--ink-canvas)`, text on contrast surfaces `var(--ink-contrast)`, and text on primary accent fills `var(--ink-accent)`.
3. Establish hierarchy and a deliberate reading path while preserving enough supporting evidence for an expert audience. Avoid both sparse poster layouts and indiscriminate text walls.
4. Do not default to a header plus two columns, a uniform card grid, dashboard tiles, or one bordered panel per bullet.
5. Treat executable code as a design kernel. It may be transformed, merged, or partially used; do not render each snippet as a separate visible object.
6. If a figure path is given, integrate the uncropped figure as primary evidence with `object-fit:contain`; do not put it in a generic thumbnail card.
7. Mark every non-informational accent with `class="deco" aria-hidden="true"` and `pointer-events:none`. Omit decoration without a concrete framing or grouping role. Do not use colored text shadows, offset badge shadows, fake measuring ticks, disconnected connector stubs, or diamond markers on every list item. Identity should come from type, composition and evidence encoding, not additional ornaments.
8. TEXT FIT: reserve non-overlapping boxes for title, thesis/claim, author/metadata, main visual, and source before styling them. Budget each box height from line-height × likely wrapped lines. Never use `white-space:nowrap` on a title longer than 60 characters. A wrapping heading and its microcopy must occupy separate vertical rows. Keep the source line below all body content.
9. SVG `<text>` does not wrap. Keep labels short; split longer labels into explicit `<tspan>` lines inside the viewBox.
10. Do not invent publication years, venues, affiliations, metrics, or citations.
11. Before returning HTML, inspect the complete scene. No text may overlap, clip, or extend outside the canvas.
12. FIT ARITHMETIC: every absolute box must satisfy left + width <= 1280 and top + height <= 720; percentage boxes must stay inside 100%. Never conceal text with overflow or max-height.
13. READABILITY: body copy must be at least $MIN_BODY_PXpx, explanatory labels at least $MIN_LABEL_PXpx, and sources at least 8px. Treat the supplied `--kernel-title-size` as a hard maximum for the main heading. Shorten wording and strengthen hierarchy instead of shrinking everything.
14. CONTRAST: explicitly set semantic text colors. Ordinary text must retain at least $MIN_TEXT_CONTRAST:1 contrast against its immediate surface.
15. INFORMATION DENSITY: preserve the evidence's explanatory depth, but express each fact once. A content slide should read as a layered argument rather than a sparse slogan or miniature report. Let charts, diagrams, and direct labels replace prose or tables that communicate the same evidence. Density is relational, not a quota of cards or decorative objects.
16. VISUAL NATURALNESS: make visual form follow the subject and the typed evidence relations. Never turn abstract control words into literal circles, steps, rails, or giant blocks merely to demonstrate compliance.
17. EDITORIAL FLOW: prefer one continuous composition with interlocking text, data, and diagram zones. Use proximity, alignment, shared baselines, and scale before boxes. Keep at least one substantial evidence sequence unboxed. A box or filled panel must encode a real semantic boundary; it is not a default wrapper.
18. CONTENT SHARE: follow the program's content_budget for information density, independently of theme and style. The balanced default is about 50–72% of the usable canvas for evidence-bearing content, with 18–32% functional negative space on non-title slides; an explicit evidence-rich budget may allocate more area to distinct supported evidence. These are composition guides, not fill quotas. Empty space must clarify hierarchy; do not spend it on an isolated heading, empty colored field, or ornamental shape. Never manufacture overlaps or hidden text to create repair work.
19. HEADING GEOMETRY: treat a wrapping heading and its subtitle as normal document flow inside one measured header region, or calculate separate non-overlapping rows from the actual line count. Never position a subtitle at a fixed `top` that assumes the heading stays on one line. On content slides the complete heading region should normally consume no more than 22% of canvas height. Long headings over 68 characters should usually be 36–44px, not poster-sized.
20. SOURCE FIGURE GEOMETRY: reset `figure { margin: 0 }`. Give the figure wrapper and `<img>` an explicit identical box derived from the supplied intrinsic aspect ratio, and verify top + height stays above the source line. `object-fit:contain` is not permission to crop the wrapper at the canvas edge.
21. SURFACE DISCIPLINE: the canvas is flat `var(--surface-canvas)`. Do not add decorative full-slide gradients, radial glows, diagonal gradient wedges, clipped waves, or arbitrary translucent overlays. A local tinted surface is allowed only when it groups related evidence; use a flat color or color-mix and keep its boundary aligned to that content.
22. SURFACE BUDGET: unless the program explicitly requires otherwise, use at most one dominant filled evidence field, and put only a short claim or metric inside it—never a paragraph-length thesis. Do not give every sibling fact its own background, border, shadow, or rounded rectangle. Build secondary grouping with whitespace, alignment, type, and rules.
23. TEXT COLLISIONS: a title may be visually large, but its rendered lines must never cross the subtitle, thesis, figure, or another heading. Keep long titles in normal flow and reserve the full measured height plus at least 12px clear space before the next text block.

## HTML Skeleton
```
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=1280, height=720, initial-scale=1">
<title>TITLE</title>
<style>
:root{--surface-canvas:X;--surface-contrast:X;--surface-muted:X;--accent-primary:X;--accent-secondary:X;--accent-tertiary:X;--accent-signal:X;--ink-canvas:X;--ink-contrast:X;--ink-accent:X}
html,body{margin:0;padding:0;width:1280px;height:720px;overflow:hidden;font-family:'Segoe UI',Arial,sans-serif}
</style></head><body>
<div style="position:relative;width:1280px;height:720px;overflow:hidden;background:var(--surface-canvas)">
  <!-- Compose a coherent page from the brief and executable vocab. -->
</div></body></html>
```

## Design Input
The user payload contains exactly one validated bounded creative brief, a typed evidence architecture, and an executable editorial kernel. Together they are the only visual authority. Do not invent a second house style or copy a complete source page.

## Output
Return only complete `<!doctype html>.....</html>` documents. For a group, preserve request order and put `<!-- SLIDE_SEPARATOR -->` between documents. No explanation or markdown fences.""".replace(
    "$MIN_BODY_PX", str(MIN_BODY_PX)
).replace("$MIN_LABEL_PX", str(MIN_LABEL_PX)).replace("$MIN_TEXT_CONTRAST", f"{MIN_TEXT_CONTRAST:g}") + "\n\n" + ART_DIRECTION + "\n\n" + EDITORIAL_COPY_POLICY


# ── API helpers ──

API_CONFIGS = {
    "local":     {"base_url": "http://localhost:8811/v1", "key": "dummy"},
    "anthropic": {"base_url": "http://127.0.0.1:46525/v1", "key_env": "ANTHROPIC_API_KEY"},
    "trapi":     {},
}


def get_client(api="local"):
    import openai
    cfg = API_CONFIGS.get(api, API_CONFIGS["local"])
    base_url = cfg.get("base_url")
    api_key = cfg.get("key", "dummy")

    if api == "local":
        base_url = os.environ.get("OPENAI_BASE_URL", base_url)
        api_key = os.environ.get("OPENAI_API_KEY", api_key)
        if api_key == "dummy" and urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Set OPENAI_API_KEY for a non-loopback endpoint")

    if cfg.get("key_env"):
        api_key = os.environ.get(cfg["key_env"], api_key)

    if api == "trapi":
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if not base_url:
            raise ValueError("Set OPENAI_BASE_URL to your authorized endpoint for --api trapi")
        from azure.identity import (
            AzureCliCredential,
            ChainedTokenCredential,
            ManagedIdentityCredential,
        )

        credential = ChainedTokenCredential(
            AzureCliCredential(),
            ManagedIdentityCredential(),
        )
        # The OpenAI SDK version in this environment serializes callable API
        # keys instead of invoking them. Keep the credential on the client and
        # refresh its token immediately before each request instead.
        api_key = credential.get_token("api://trapi/.default").token

    client = openai.OpenAI(base_url=base_url, api_key=api_key)
    if api == "trapi":
        client._trapi_credential = credential
    return client


def refresh_trapi_token(client):
    credential = getattr(client, "_trapi_credential", None)
    if credential is not None:
        client.api_key = credential.get_token("api://trapi/.default").token


def _responses_http(client, model, system, user, max_output_tokens=16384, timeout=600):
    content = [{"type": "input_text", "text": user}] if isinstance(user, str) else [
        {"type": "input_text", "text": item["text"]} if item["type"] == "text" else
        {"type": "input_image", "image_url": item["image_url"]["url"]} for item in user]
    body = {
        "model": model,
        "instructions": system,
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": max_output_tokens,
    }
    url = str(client.base_url).rstrip("/") + "/responses"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {client.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        error.status_code = error.code
        raise RuntimeError(f"Responses API {error.code}: {detail}") from error
    text = payload.get("output_text", "")
    if not text:
        text = "".join(
            block.get("text", "")
            for item in payload.get("output", []) if item.get("type") == "message"
            for block in item.get("content", []) if block.get("type") == "output_text"
        )
    usage = payload.get("usage") or {}
    return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def call_llm(client, model, system, user, *, max_output_tokens=16384, timeout=600, retries=4, log_prefix=None):
    started = time.monotonic()
    if retries < 0 or timeout <= 0 or max_output_tokens <= 0:
        raise ValueError("Invalid model request limits")
    needs_mct = any(token in model.lower() for token in ('gpt-5', 'o3', 'o4'))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    uses_responses = model.lower().startswith(("grok-", "mai-"))

    def request(use_mct):
        kwargs = {"model": model, "messages": messages}
        if use_mct:
            kwargs["extra_body"] = {"max_completion_tokens": max_output_tokens}
        else:
            kwargs["max_tokens"] = max_output_tokens
        transport = client.with_options(max_retries=0, timeout=timeout) if hasattr(client, "with_options") else client
        return transport.chat.completions.create(**kwargs)

    parameter_mode = needs_mct
    usage = {"model": model, "status": "error", "attempts": [], "input_tokens": 0, "output_tokens": 0}
    saved_prefix = None
    if log_prefix is not None:
        for sequence in range(1, 10001):
            saved_prefix = Path(f"{log_prefix}_call_{sequence:04d}")
            saved_prefix.parent.mkdir(parents=True, exist_ok=True)
            try:
                with Path(f"{saved_prefix}.request.json").open("x") as stream:
                    json.dump({"model": model, "system": system, "content": user,
                               "max_output_tokens": max_output_tokens, "timeout": timeout, "retries": retries}, stream, ensure_ascii=False)
                break
            except FileExistsError:
                continue
        else:
            raise FileExistsError("Model request log namespace exhausted")
    try:
        for attempt in range(retries + 1):
            call = {"attempt": attempt + 1}
            call_started = time.monotonic()
            usage["attempts"].append(call)
            try:
                with request_slot(timeout) as waited:
                    call["queue_seconds"] = waited
                    refresh_trapi_token(client)
                    if uses_responses:
                        text, input_tokens, output_tokens = _responses_http(client, model, system, user, max_output_tokens, timeout)
                    else:
                        response = request(parameter_mode)
                        text = response.choices[0].message.content or ""
                        response_usage = getattr(response, "usage", None)
                        input_tokens = getattr(response_usage, "prompt_tokens", 0) or 0
                        output_tokens = getattr(response_usage, "completion_tokens", 0) or 0
                        usage["finish_reason"] = getattr(response.choices[0], "finish_reason", None)
                        details = getattr(response_usage, "completion_tokens_details", None)
                        usage["reasoning_tokens"] = getattr(details, "reasoning_tokens", None)
                call["status"] = "completed"
                usage.update(status="completed", input_tokens=input_tokens, output_tokens=output_tokens)
                if saved_prefix:
                    Path(f"{saved_prefix}.response.txt").write_text(text)
                return text, input_tokens, output_tokens, time.monotonic() - started
            except Exception as error:
                cause = error.__cause__ or error
                status = getattr(cause, "status_code", None) or getattr(cause, "code", None)
                call.update(status="error", error=type(error).__name__, http_status=status)
                parameter_error = status == 400 and any(token in str(error).lower()
                    for token in ("max_tokens", "max_completion_tokens", "unsupported parameter"))
                if parameter_error and attempt == 0 and attempt < retries:
                    parameter_mode = not parameter_mode
                    continue
                retryable = status in {408, 409, 429, 500, 502, 503, 504} or type(error).__name__ in {
                    "APIConnectionError", "APITimeoutError", "TimeoutError", "ConnectionError"} or (
                    status is None and isinstance(cause, (urllib.error.URLError, TimeoutError, ConnectionError)))
                if not retryable or attempt == retries:
                    raise
                headers = getattr(getattr(cause, "response", None), "headers", {}) or getattr(cause, "headers", {}) or {}
                delay = min(16, 2 ** attempt)
                retry_after = headers.get("retry-after")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except (ValueError, TypeError):
                        from email.utils import parsedate_to_datetime

                        try:
                            delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                        except (ValueError, TypeError, OverflowError):
                            pass
                if delay > timeout:
                    raise
                call["retry_delay_seconds"] = delay
                time.sleep(delay)
            finally:
                call["elapsed_seconds"] = time.monotonic() - call_started
    finally:
        usage["elapsed_seconds"] = time.monotonic() - started
        if client is not None:
            client._redeck_last_call_usage = usage
        if saved_prefix:
            Path(f"{saved_prefix}.usage.json").write_text(json.dumps(usage, indent=2) + "\n")


def extract_html(text):
    m = re.search(r'```html\s*\n(.*?)```', text, re.DOTALL)
    if m: return m.group(1).strip()
    m = re.search(r'(<!doctype html.*?</html>)', text, re.DOTALL | re.IGNORECASE)
    if m: return m.group(1).strip()
    if '<html' in text.lower():
        m = re.search(r'(<html.*?</html>)', text, re.DOTALL | re.IGNORECASE)
        if m: return m.group(1).strip()
    return text


def extract_html_documents(text, expected_count):
    """Extract an ordered batch of standalone slides from one response."""
    parts = re.split(r'<!--\s*SLIDE_SEPARATOR\s*-->', text, flags=re.IGNORECASE)
    documents = [extract_html(part.strip()) for part in parts if "<html" in part.lower()]
    documents = [document for document in documents if "<html" in document.lower()]
    if len(documents) != expected_count:
        documents = re.findall(
            r'<!doctype html.*?</html>', text, flags=re.DOTALL | re.IGNORECASE
        )
    return documents[:expected_count]


def build_group_prompt(program_pipeline, slides, source_excerpt="", visual_feedback=None):
    summaries = [
        {
            "slide_id": slide["slide_id"],
            "role": slide.get("role", "context"),
        }
        for slide in slides
    ]
    parts = [
        f"## DECK GROUP — GENERATE {len(slides)} SLIDES",
        "Design this group as a sequence: keep one visual identity but make each page's concrete topology, focal scale, and silhouette visibly distinct.",
        "Do not repeat the same title placement, panel scaffold, background texture, or figure/table treatment on adjacent pages.",
        f"```json\n{json.dumps(summaries, ensure_ascii=False, indent=2)}\n```",
    ]
    for slide in slides:
        parts.extend([
            f"\n## BEGIN SLIDE {slide['slide_id']}",
            program_pipeline.prompt_for(slide, source_excerpt, include_editorial_policy=False),
            f"## END SLIDE {slide['slide_id']}",
        ])
    parts.extend([
        "Return the complete standalone HTML documents in the same order.",
        "Place `<!-- SLIDE_SEPARATOR -->` on its own line between documents. Return no prose or markdown fences.",
    ])
    visual_feedback = visual_feedback or {}
    group_feedback = [
        f"Slide {slide['slide_id']}: {visual_feedback[str(slide['slide_id'])]}"
        for slide in slides if str(slide["slide_id"]) in visual_feedback
    ]
    if group_feedback:
        parts.extend([
            "## VISUAL REPAIR FEEDBACK — higher priority than automated metrics",
            *group_feedback,
        ])
    return "\n".join(parts)


# ── Evidence & prompt building ──

def load_case(case_dir):
    paper = (case_dir / "source_pack" / "paper_full.md").read_text(errors='replace') if (case_dir / "source_pack" / "paper_full.md").exists() else ""
    # The renderer performs deterministic slide-level retrieval over the full
    # document; the complete paper is never dumped into a model prompt.
    paper_summary = paper

    assets = {}
    for directory, id_field in (("figures", "figure_id"), ("tables", "table_id")):
        asset_dir = case_dir / "source_pack" / directory
        if not asset_dir.exists():
            continue
        for metadata_path in sorted(asset_dir.glob("*.json")):
            meta = json.loads(metadata_path.read_text())
            asset_id = meta.get(id_field, metadata_path.stem)
            image_path = next(
                (
                    metadata_path.with_suffix(suffix)
                    for suffix in (".png", ".jpg", ".jpeg", ".webp")
                    if metadata_path.with_suffix(suffix).exists()
                ),
                None,
            )
            assets[asset_id] = {
                "caption": meta.get("caption", ""),
                "path": str(image_path) if image_path else "",
                "kind": directory.rstrip("s"),
                "width": int(meta.get("width") or 0),
                "height": int(meta.get("height") or 0),
                # Table data is semantic evidence, not a visual reference.  It
                # lets the runtime preserve the source's real information
                # density while still rebuilding the table as native HTML.
                "rows": meta.get("rows", []),
                "row_count": meta.get("row_count", 0),
                "col_count": meta.get("col_count", 0),
            }
    # Older real-document blueprints refer to source-store asset IDs (A001,
    # A002, ...), while the current runtime uses stable figure/table IDs. Keep
    # aliases at the ingestion boundary instead of duplicating or rewriting the
    # historical blueprint content.
    source_store_path = case_dir / "source_pack" / "source_store.json"
    if source_store_path.exists():
        source_store = json.loads(source_store_path.read_text())
        for source_asset in source_store.get("assets", []):
            alias = source_asset.get("asset_id")
            image_path = source_asset.get("image_path", "")
            canonical_id = Path(image_path).stem
            if alias and canonical_id in assets:
                assets[alias] = assets[canonical_id]
    return paper_summary, assets


def resolve_slide_assets(slides, figures):
    """Resolve historical asset aliases and conservative linked-asset fallbacks."""
    resolved = []
    for slide in slides:
        item = dict(slide)
        assigned = item.get("assigned_figure_id")
        if not assigned or assigned not in figures:
            candidates = [
                *item.get("asset_ids", []),
                *item.get("table_ids", []),
                *item.get("linked_evidence_ids", []),
            ]
            item["assigned_figure_id"] = next(
                (candidate for candidate in candidates if candidate in figures),
                "",
            )
        resolved.append(item)
    return resolved


def _blueprint_score(path):
    """Prefer evidence-rich blueprints; never let filename order choose content."""
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    slides = payload.get("slides", [])
    if not slides:
        return None
    evidence_items = sum(len(slide.get("must_cover_subset", [])) for slide in slides)
    evidence_chars = sum(
        len(str(item))
        for slide in slides
        for item in slide.get("must_cover_subset", [])
    )
    proposition_chars = sum(len(slide.get("primary_proposition", "")) for slide in slides)
    assigned_assets = sum(bool(slide.get("assigned_figure_id")) for slide in slides)
    # Evidence coverage dominates.  The remaining terms break ties between
    # equally complete plans without relying on filesystem or lexical order.
    score = evidence_items * 10_000 + evidence_chars * 10 + proposition_chars + assigned_assets * 500
    return score, payload


def resolve_blueprint(case_id, explicit_path=None, probe_root=None):
    if explicit_path:
        path = Path(explicit_path).resolve()
        scored = _blueprint_score(path)
        if scored is None:
            raise ValueError(f"invalid or empty blueprint: {path}")
        return path, scored[1]

    candidates = []
    probe_root = resolve_probe_root(probe_root)
    candidates.extend((probe_root / "runs").glob(f"{case_id}_*/turn_00/deck_blueprint.json"))
    scored = [(_blueprint_score(path), path.resolve()) for path in candidates]
    scored = [(value, path) for value, path in scored if value is not None]
    if not scored:
        raise FileNotFoundError(f"no valid blueprint found for {case_id}; supply --blueprint or use redeck generate")
    (_, payload), path = max(scored, key=lambda item: (item[0][0], str(item[1])))
    return path, payload


def _relative_luminance(hex_color):
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6:
        return 0.0
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(color_a, color_b):
    lum_a, lum_b = _relative_luminance(color_a), _relative_luminance(color_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def contrast_map(tokens):
    """Return the safer text variable for each palette background role."""
    result = {}
    for background, ink in (
        ("surface_canvas", "ink_canvas"),
        ("surface_contrast", "ink_contrast"),
        ("accent_primary", "ink_accent"),
    ):
        result[background] = ink
    return result


# ── Rendering ──

def render_slides(slide_dir, png_dir):
    from redeck_style.evaluation.snapshot import capture_page

    for source in sorted(Path(slide_dir).glob("slide_*.html")):
        capture_page(source, Path(png_dir) / f"{source.stem}.png")


def evaluate_bams_similarity(out_dir):
    evaluator = Path(__file__).resolve().parent / "evaluate_scene_similarity.py"
    result = subprocess.run(
        [sys.executable, str(evaluator), str(out_dir), "--json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    report = json.loads(result.stdout)
    return report[str(out_dir)]


def requires_source_review(result):
    return result.get("status") == "source-review-required" or bool(result.get("layout_validity", {}).get("source_asset_issue_count", 0))


def regeneration_candidates(results, selected_ids):
    return [result for result in results if result["slide_id"] in selected_ids
            and result["status"] != "in-band" and not requires_source_review(result)]


def bams_repair_feedback(result):
    if requires_source_review(result):
        return "Source asset review is required. Do not regenerate layout to conceal missing or fragmented evidence; correct and version the source asset first."
    if result["status"] == "layout-invalid":
        validity = result["layout_validity"]
        affected = ", ".join(
            dict.fromkeys(
                validity.get("overflow_roles", []) + validity.get("clipped_roles", [])
            )
        ) or "informative elements"
        contrast = validity.get("low_contrast_count", 0)
        contrast_roles = ", ".join(validity.get("low_contrast_roles", []))
        gradient = validity.get("gradient_violation_count", 0)
        collisions = validity.get("text_collision_count", 0)
        collision_roles = ", ".join(validity.get("text_collision_roles", []))
        graphic_collisions = validity.get("graphic_text_collision_count", 0)
        graphic_clearances = validity.get("graphic_text_clearance_count", 0)
        connector_rules = validity.get("connector_rule_collision_count", 0)
        connector_occlusions = validity.get("connector_occlusion_count", 0)
        text_clearances = validity.get("text_clearance_count", 0)
        text_associations = validity.get("text_association_count", 0)
        graphic_collision_roles = ", ".join(validity.get("graphic_text_collision_roles", []))
        return (
            "The previous composition failed the rendering-validity gate "
            f"({validity['overflow_count']} overflowing elements, "
            f"{validity['text_clip_count']} clipped text boxes, {collisions} text collisions, "
            f"{graphic_collisions} rule/connector-to-text collisions, "
            f"{graphic_clearances} large-text/divider clearance failures, "
            f"{connector_rules} arrow/separator conflicts, {connector_occlusions} hidden arrow endpoints, "
            f"{text_clearances} relation-label/body clearance failures, "
            f"{text_associations} labels wedged between prose groups, "
            f"{contrast} low-contrast text elements, "
            f"and {gradient} invalid gradients; affected fit roles: {affected}). "
            "Regenerate from scratch with explicit text height budgets and shorter display copy. "
            "For every absolute box, enforce left + width <= 1280 and top + height <= 720; "
            "for percentage boxes, enforce left% + width% <= 100 and top% + height% <= 100. "
            "Do not hide text with overflow:hidden or max-height unless its measured content fits. "
            + (
                f"Separate colliding text ({collision_roles}) using normal flow or corrected measured offsets. "
                if collisions else ""
            )
            + (
                f"Reroute or shorten rules/connectors that cross visible text ({graphic_collision_roles}); "
                "do not simply hide the connector. "
                if graphic_collisions else ""
            )
            + (
                "Keep arrow shafts and full arrowheads clear of unrelated separators, including rule endpoints. "
                "Dock arrows visibly outside target panels; do not hide endpoints behind fills. "
                if connector_rules or connector_occlusions else ""
            )
            + (
                "Leave at least 12px of breathing room between large display words and vertical dividers. "
                if graphic_clearances else ""
            )
            + (
                "Move small relation labels out of body-copy baselines; reserve a readable gap to unrelated sentences. "
                if text_clearances or text_associations else ""
            )
            + (
                f"Fix low-contrast text roles ({contrast_roles}) by using ink-canvas or ink-contrast "
                "for copy; reserve accent colors for borders, large display numerals, and filled fields. "
                if contrast else ""
            )
            + "Preserve the scene topology and BAMS distribution traits while fixing fit. "
            + (
                "Remove decorative gradients from: "
                + ", ".join(validity.get("gradient_roles", []))
                + ". Keep the canvas flat and use flat evidence-bound surfaces."
                if validity.get("gradient_violation_count") else ""
            )
        )
    if result["status"] == "too-literal":
        return (
            "The previous composition was too close to an element-for-element BAMS template copy "
            f"(geometry-copy score {result['copy_score']:.3f}). Regenerate from scratch: choose different "
            "values inside every allowed range, apply at least two declared content mutations, and merge or "
            "split regions while preserving the topology, hierarchy, rhythm, and motif family."
        )
    components = result["components"]
    weakest = sorted(components.items(), key=lambda item: item[1])[:3]
    guidance = {
        "dom": "increase meaningful structural detail instead of empty decoration",
        "node_density": "restore the reference's element density with informative labels, data marks, or repeated units",
        "semantic_roles": "use the requested mix of title/body/metric/chart/table/step roles",
        "spatial_occupancy": "follow the region topology and visual-mass distribution more closely",
        "repeat_rhythm": "implement the declared repeated-element system and instance range",
        "motifs": "apply the required motif family consistently across multiple element roles",
    }
    fixes = "; ".join(guidance[name] for name, _ in weakest)
    return (
        "The previous composition drifted outside the BAMS distribution "
        f"(similarity {result['similarity']:.3f}). Regenerate from scratch and specifically: {fixes}. "
        "Do not copy exact reference coordinates. Preserve all evidence and contrast rules."
    )


# ── Main ──

def build_parser():
    parser = argparse.ArgumentParser(description="ReDeck unified codegen")
    add_judge_arguments(parser)
    parser.add_argument("--case", required=True)
    parser.add_argument("--cases-root", type=Path, default=None,
                        help="Directory containing case/source_pack folders; defaults to REDECK_CASES_ROOT or ./cases.")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--api", default="local", choices=["local", "anthropic", "trapi"])
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument(
        "--group-size", type=int, default=1,
        help="Slides per realization call. Use 2-3 to let capable models coordinate deck rhythm.",
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--lum", default="light")
    parser.add_argument("--palette", default="gray-mono")
    parser.add_argument("--blueprint", default=None)
    parser.add_argument("--seed", type=int, default=42, help="Deterministic design-program seed")
    parser.add_argument("--information-density", choices=("balanced", "evidence-rich"), default="balanced",
                        help="Evidence and composition budget, independent of theme; evidence-rich adds grounded detail without relaxing readability.")
    parser.add_argument("--asset-mode", choices=ASSET_MODES, default="auto",
                        help="Assigned-source presentation: auto keeps existing behavior; preserve embeds the original image; table/chart require extracted table data. Applies only to selected slides.")
    parser.add_argument("--asset-policy", type=Path, default=None,
                        help="Optional JSON object mapping source asset IDs to modes; overrides --asset-mode per asset.")
    parser.add_argument(
        "--design-family", "--dialect", dest="dialect",
        default=None,
        help="Optional material family, e.g. type-sans-clean. --dialect and legacy source-group IDs remain explicit compatibility inputs.",
    )
    parser.add_argument(
        "--style-archetype",
        choices=("editorial-contrast", "technical-instrument", "display-architecture", "chromatic-system"),
        default=None,
        help="Cross-element style grammar, independent from Theme color tokens.",
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Optional directory containing compiled runtime artifacts",
    )
    parser.add_argument(
        "--slides",
        default=None,
        help="Optional comma-separated slide IDs for a focused smoke run",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--bams-retries",
        type=int,
        default=0,
        help=(
            "Opt-in regeneration count for structural failures (default: 0). "
            "Diagnostics are always recorded; visual acceptance remains a human decision."
        ),
    )
    parser.add_argument(
        "--visual-feedback",
        default=None,
        help="Optional JSON mapping slide IDs to human visual-review repair instructions",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if Path(args.case).name != args.case or args.case in {".", ".."}:
        parser.error("--case must be a simple case ID")
    probe_root = resolve_probe_root(args.probe_root)
    cases_root = resolve_cases_root(args.cases_root)
    case_dir = (cases_root / args.case).resolve()
    if not case_dir.exists():
        print(f"Case not found: {case_dir}"); sys.exit(1)

    model_tag = args.model.replace("/", "_").replace(".", "_")
    out_dir = Path(args.out) if args.out else Path(f"runs/{args.case}_{model_tag}")
    if (out_dir / "run_manifest.json").exists() or list((out_dir / "slide_code").glob("slide_*.html")):
        parser.error("Output already contains a run; use a fresh --out directory")
    slide_dir = out_dir / "slide_code"
    png_dir = out_dir / "slide_png"
    slide_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    # Load
    paper_summary, figures = load_case(case_dir)

    try:
        blueprint_path, bp = resolve_blueprint(args.case, args.blueprint, probe_root)
    except (FileNotFoundError, ValueError) as error:
        print(error); sys.exit(1)

    slides = resolve_slide_assets(bp["slides"], figures)
    save_source_context(out_dir, case_dir / "source_pack", {**bp, "slides": slides})
    total = len(slides)
    selected_slides = slides
    if args.slides:
        try:
            selected_ids = {int(value.strip()) for value in args.slides.split(",") if value.strip()}
        except ValueError:
            parser.error("--slides must be a comma-separated list of integers")
        selected_slides = [slide for slide in slides if slide["slide_id"] in selected_ids]
        if not selected_slides:
            parser.error("--slides did not match any blueprint slide IDs")
    visual_feedback = {}
    if args.visual_feedback:
        visual_feedback = json.loads(Path(args.visual_feedback).read_text())
    from redeck_style.library import RuntimeLibrary
    from redeck_style.pipeline import ProgramPipeline
    runtime_library = RuntimeLibrary(args.artifact_dir)
    theme = runtime_library.resolve_theme(args.palette, args.lum)
    (out_dir / "theme.json").write_text(
        json.dumps(theme.__dict__, indent=2, ensure_ascii=False) + "\n"
    )

    # Planning is sequential and deterministic. Realization may be parallel,
    # but every model receives exactly one validated program per slide.
    try:
        asset_policy = json.loads(args.asset_policy.read_text()) if args.asset_policy else {}
        if not isinstance(asset_policy, dict):
            raise ValueError("Asset policy must be an object mapping asset IDs to modes")
        program_pipeline = ProgramPipeline(
            runtime_library,
            theme,
            slides,
            figures,
            seed=args.seed,
            dialect_id=args.dialect,
            style_archetype=args.style_archetype,
            information_density=args.information_density,
            asset_mode=args.asset_mode,
            asset_policy=asset_policy,
            selected_slide_ids={slide["slide_id"] for slide in selected_slides},
        )
        initial_prompts = {slide["slide_id"]: program_pipeline.prompt_for(slide, paper_summary)
                           for slide in selected_slides}
    except (OSError, ValueError) as error:
        parser.error(str(error))
    source_audit = audit_source_assets(selected_slides, figures, program_pipeline.asset_presentations)
    (out_dir / "source_asset_audit.json").write_text(json.dumps(source_audit, ensure_ascii=False, indent=2) + "\n")
    source_failures = [item for item in source_audit if item["issues"]]
    (out_dir / "asset_presentation.json").write_text(json.dumps(program_pipeline.asset_presentations, ensure_ascii=False, indent=2) + "\n")
    (out_dir / "deck_plan.json").write_text(
        json.dumps(program_pipeline.deck_plan.to_dict(), indent=2, ensure_ascii=False) + "\n"
    )
    selection = program_pipeline.deck_plan.selection_audit
    print(f"  design family: {selection['selected_family']} ({selection['mode']}, content-fit score={selection['selected_score']})")
    print(f"  selection reasons: {json.dumps(selection['selected_reasons'], ensure_ascii=False)}")
    program_dir = out_dir / "slide_programs"
    prompt_dir = out_dir / "prompts"
    program_dir.mkdir(exist_ok=True)
    prompt_dir.mkdir(exist_ok=True)
    (prompt_dir / "system.txt").write_text(SYSTEM_PROMPT)
    for slide_id, prompt in initial_prompts.items():
        (prompt_dir / f"slide_{slide_id:02d}.txt").write_text(prompt)
    for slide_id, program in program_pipeline.programs.items():
        (program_dir / f"slide_{slide_id:02d}.json").write_text(
            json.dumps(program.to_dict(), indent=2, ensure_ascii=False) + "\n"
        )
    strategies = {program.composition.strategy for program in program_pipeline.programs.values()}
    vocab_count = sum(len(program.vocab) for program in program_pipeline.programs.values())
    print(f"  programs: {len(program_pipeline.programs)}, {len(strategies)} composition strategies, {vocab_count} vocab selections")

    manifest = {
        "case": args.case,
        "model_family": args.model.split("/", 1)[0] if "/" in args.model else args.model.split("-", 1)[0],
        "model": args.model,
        "api": args.api,
        "blueprint": str(blueprint_path),
        "source_dir": str((case_dir / "source_pack").resolve()),
        "judge_mode": args.judge_mode,
        "theme": theme.id,
        "dialect": program_pipeline.deck_plan.dialect_id,
        "design_family": program_pipeline.deck_plan.dialect_id,
        "selection_policy": selection["policy"],
        "compatibility_policy": runtime_library.graph["policy"],
        "runtime_source_hash": runtime_library.graph["source_hash"],
        "style_archetype": program_pipeline.deck_plan.style_archetype,
        "information_density": args.information_density,
        "asset_mode": args.asset_mode,
        "asset_policy": asset_policy,
        "program_schema": "2.0.0",
        "seed": args.seed,
        "slide_count": total,
        "selected_slide_count": len(selected_slides),
        "composition_strategy_count": len(strategies),
        "source_review_slide_ids": [item["slide_id"] for item in source_failures],
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"{args.case}: {len(selected_slides)}/{total} slides, model={args.model}, api={args.api}")
    print(f"  blueprint: {blueprint_path}")
    print(f"  theme: {theme.id}; dialect={program_pipeline.deck_plan.dialect_id}; seed={args.seed}")

    if args.dry_run:
        if source_failures:
            print(f"  source review required before generation: {[item['slide_id'] for item in source_failures]}")
        dry_group = selected_slides[:max(1, args.group_size)]
        prompt = (
            build_group_prompt(program_pipeline, dry_group, paper_summary, visual_feedback)
            if len(dry_group) > 1 else initial_prompts[dry_group[0]["slide_id"]]
        )
        print(f"  prompt: {len(prompt)} chars ≈ {len(prompt)//4} tokens")
        print(f"  system: {len(SYSTEM_PROMPT)} chars ≈ {len(SYSTEM_PROMPT)//4} tokens")
        print(prompt[:2000])
        return

    if source_failures:
        raise SystemExit(f"Source asset preflight failed on slides {[item['slide_id'] for item in source_failures]}; see {out_dir / 'source_asset_audit.json'}. No model requests were made.")
    # Generate
    client = get_client(args.api)
    total_in, total_out = 0, 0
    t0 = time.time()

    def gen_one(slide, repair_feedback=None, attempt_index=0):
        prompt = initial_prompts[slide["slide_id"]]
        human_feedback = visual_feedback.get(str(slide["slide_id"]))
        feedback = "\n\n".join(item for item in (human_feedback, repair_feedback) if item)
        if feedback:
            prompt += (
                "\n\n## VISUAL REPAIR FEEDBACK — higher priority than automated metrics\n"
                + feedback
            )
        (prompt_dir / f"slide_{slide['slide_id']:02d}.txt").write_text(prompt)
        (prompt_dir / f"slide_{slide['slide_id']:02d}_attempt_{attempt_index:02d}.txt").write_text(prompt)
        text, tin, tout, elapsed = call_llm(client, args.model, SYSTEM_PROMPT, prompt)
        html = extract_html(text)
        return slide["slide_id"], html, tin, tout, elapsed

    results = []

    def gen_group(group):
        prompt = build_group_prompt(
            program_pipeline, group, paper_summary, visual_feedback
        )
        group_id = "_".join(f"{slide['slide_id']:02d}" for slide in group)
        (prompt_dir / f"group_{group_id}.txt").write_text(prompt)
        text, tin, tout, elapsed = call_llm(client, args.model, SYSTEM_PROMPT, prompt)
        documents = extract_html_documents(text, len(group))
        return group, documents, tin, tout, elapsed

    group_size = max(1, args.group_size)
    groups = [selected_slides[index:index + group_size] for index in range(0, len(selected_slides), group_size)]
    use_groups = group_size > 1
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {
            ex.submit(gen_group, group) if use_groups else ex.submit(gen_one, group[0]):
            ",".join(str(slide["slide_id"]) for slide in group)
            for group in groups
        }
        for f in as_completed(futures):
            try:
                if use_groups:
                    group, documents, tin, tout, elapsed = f.result()
                    total_in += tin; total_out += tout
                    if len(documents) != len(group):
                        print(f"  group {futures[f]}: FAILED ({len(documents)}/{len(group)} documents)")
                    for slide, html in zip(group, documents):
                        sid = slide["slide_id"]
                        (slide_dir / f"slide_{sid:02d}.html").write_text(html)
                        results.append(sid)
                        print(f"  slide_{sid:02d}: {len(html)}B, group {elapsed:.0f}s")
                else:
                    sid, html, tin, tout, elapsed = f.result()
                    total_in += tin; total_out += tout
                    if html and '<' in html:
                        (slide_dir / f"slide_{sid:02d}.html").write_text(html)
                        results.append(sid)
                        print(f"  slide_{sid:02d}: {len(html)}B, {elapsed:.0f}s")
                    else:
                        print(f"  slide_{sid:02d}: FAILED")
            except Exception as e:
                print(f"  slide/group {futures[f]}: ERROR {e}")

    elapsed = time.time() - t0
    print(f"\nSlides: {len(results)}/{total}")
    print(f"Tokens: {total_in+total_out:,} (in:{total_in:,} out:{total_out:,})")
    print(f"Time: {elapsed:.0f}s; cost not estimated (provider/model pricing is not configured)")

    print("Rendering...")
    render_slides(str(slide_dir), str(png_dir))

    # Closed-loop structural repair. This measures resemblance to the selected
    # BAMS distribution separately from literal geometry copying.
    scene_evaluations = []
    if results:
        for attempt in range(args.bams_retries + 1):
            try:
                scene_evaluations = evaluate_bams_similarity(out_dir)
            except Exception as error:
                print(f"  BAMS evaluation error: {error}")
                break
            failures = regeneration_candidates(scene_evaluations, {slide["slide_id"] for slide in selected_slides})
            deferred = [item["slide_id"] for item in scene_evaluations if requires_source_review(item)]
            if deferred:
                print(f"  source review required, not layout regeneration: {deferred}")
            counts = {}
            for item in scene_evaluations:
                counts[item["status"]] = counts.get(item["status"], 0) + 1
            print(f"  BAMS distribution: {counts}")
            if not failures or attempt >= args.bams_retries:
                break

            archive = out_dir / "attempts"
            archive.mkdir(exist_ok=True)
            by_id = {slide["slide_id"]: slide for slide in selected_slides}
            print(f"  Structural repair attempt {attempt + 1}: {len(failures)} slides")
            for failure in failures:
                sid = failure["slide_id"]
                html_path = slide_dir / f"slide_{sid:02d}.html"
                png_path = png_dir / f"slide_{sid:02d}.png"
                if html_path.exists():
                    shutil.copy2(html_path, archive / f"slide_{sid:02d}_attempt_{attempt}.html")
                if png_path.exists():
                    shutil.copy2(png_path, archive / f"slide_{sid:02d}_attempt_{attempt}.png")
                try:
                    _, html, tin, tout, retry_elapsed = gen_one(
                        by_id[sid], bams_repair_feedback(failure), attempt + 1
                    )
                    total_in += tin
                    total_out += tout
                    if html and "<" in html:
                        html_path.write_text(html)
                        print(f"    slide_{sid:02d}: repaired, {len(html)}B, {retry_elapsed:.0f}s")
                except Exception as error:
                    print(f"    slide_{sid:02d}: repair ERROR {error}")
            render_slides(str(slide_dir), str(png_dir))

        if scene_evaluations:
            (out_dir / "scene_evaluation.json").write_text(
                json.dumps(scene_evaluations, indent=2, ensure_ascii=False) + "\n"
            )
            manifest["scene_evaluation"] = {
                "attempt_limit": args.bams_retries,
                "status_counts": {
                    status: sum(item["status"] == status for item in scene_evaluations)
                    for status in sorted({item["status"] for item in scene_evaluations})
                },
            }
            manifest["generated_slide_ids"] = sorted(
                int(match.group(1))
                for path in slide_dir.glob("slide_*.html")
                if (match := re.search(r"(\d+)$", path.stem))
            )
            manifest["rendered_slide_count"] = len(manifest["generated_slide_ids"])
            (out_dir / "run_manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
            )
    manifest["generation_usage"] = {"model": args.model, "input_tokens": total_in, "output_tokens": total_out,
                                    "elapsed_seconds": round(elapsed, 1), "cost_estimate": None}
    if results:
        content_review = review_run(out_dir, out_dir / "content_review", judge_options(args))
        spatial_status = "needs_repair" if any(item["status"] == "layout-invalid" for item in scene_evaluations) else "needs_visual_review"
        if any(requires_source_review(item) for item in scene_evaluations):
            spatial_status = "needs_source_review"
        manifest["evaluation"] = {
            "status": combine_status(spatial_status, content_review), "spatial_status": spatial_status,
            "content_status": content_review["status"], "content_coverage_complete": content_review["coverage_complete"],
            "content_report": content_review["report_path"], "visual_review": "not_run",
            "content_remediation": content_review["remediation"],
        }
        if len(results) != len(selected_slides):
            manifest["evaluation"]["status"] = "generation_incomplete"
        (out_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"  Evaluation: {manifest['evaluation']['status']}")
        if any(record["status"] == "error" for record in content_review["probes"]):
            raise SystemExit("Content evaluation failed; see content_review/report.json")
    print(f"Output: {out_dir}")


if __name__ == "__main__":
    main()
