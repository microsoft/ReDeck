#!/usr/bin/env python3
"""LLM-based component extraction from all 497 seed slides.

For each seed HTML, asks LLM to extract 6 parameterized CSS/HTML components:
  - background: .slide background CSS (gradients, patterns)
  - layout: zone dividers (sidebar, header, split) with position/size
  - decoration: ONE decorative SVG/CSS shape, simplified
  - separator: divider/rule style
  - typography: title CSS (font-size, weight, spacing, shadow)
  - content: content-specific structure for the seed's catalog content kind

All colors are first normalized to source-relative slots. The deterministic
StyleSpec builder later maps those slots to runtime semantic Theme tokens.

Output: pattern_library/metadata/seed_components.json
  { "seed_000": { "bg": "...", ..., "content": [{"content": "comparison-columns", "code": "..."}] }, ... }
"""

import json, os, sys, time, glob
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEEDS_DIR = Path(os.environ.get("REDECK_BAMS_SEEDS", ROOT / "offline/style_seeds"))
DEFAULT_CATALOG = ROOT / "pattern_library" / "metadata" / "pattern_catalog.json"
DEFAULT_OUTPUT = ROOT / "pattern_library" / "metadata" / "seed_components.json"

EXTRACT_PROMPT = """You extract reusable CSS/HTML components from a presentation slide.

Replace ALL hardcoded colors with CSS custom properties:
- Dark backgrounds → var(--source-dark)
- Light backgrounds → var(--source-light)
- Accent/highlight colors → var(--source-accent)
- Dark text → var(--source-ink-dark)
- Light text → var(--source-ink-light)

Return a JSON object with EXACTLY these 6 keys:

{
  "bg": ".slide background CSS (gradients, patterns). Use var(--xxx) colors. Max 300 chars.",
  "layout": "Major zone CSS (sidebar, header, panels). position + size. Use % where possible. Max 400 chars.",
  "deco": "ONE decorative element (SVG or CSS shape). Simplified, recolored var(--source-accent). Max 250 chars.",
  "sep": "Divider/rule CSS. Max 150 chars.",
  "typo": "Title CSS (font-size, weight, spacing, shadow). Max 200 chars.",
  "content": "Content-specific CSS/HTML structure such as rows, nodes, metrics, steps, or columns. Max 400 chars."
}

Rules:
- Each value is RAW CSS or HTML, not a description
- var(--xxx) for ALL colors — zero hardcoded hex values
- Keep components short and copy-pasteable
- Return ONLY the JSON object, no explanation"""


def get_client():
    sys.path.insert(0, str(ROOT))
    from scripts.codegen import get_client as shared_client

    return shared_client()


def extract_one(client, model, seed_id, html_text, content_kind):
    """Extract components from one seed."""
    import re as _re

    # Extract CSS only — much shorter, better LLM results
    css_match = _re.search(r'<style[^>]*>(.*?)</style>', html_text, _re.DOTALL)
    css_text = css_match.group(1) if css_match else ""
    if len(css_text) < 100:
        return None, "CSS too short"

    # Also extract first SVG for decoration
    svg_match = _re.search(r'(<svg[^>]*viewBox[^>]*>.*?</svg>)', html_text, _re.DOTALL)
    svg_hint = ""
    if svg_match and len(svg_match.group(1)) < 1000:
        svg_hint = f"\n\nSVG decoration found:\n{svg_match.group(1)[:800]}"

    input_text = css_text[:6000] + svg_hint

    # Detect if model needs max_completion_tokens vs max_tokens
    needs_mct = any(x in model.lower() for x in ['gpt-5', 'o3', 'o4'])

    try:
        kwargs = dict(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": f"The catalog content kind is {content_kind}. Extract from this CSS:\n{input_text}"},
            ],
        )
        if needs_mct:
            kwargs["extra_body"] = {"max_completion_tokens": 1500}
        else:
            kwargs["max_tokens"] = 1500

        r = client.chat.completions.create(**kwargs)
        text = r.choices[0].message.content or ""

        if not text:
            return None, "empty response"

        # Parse JSON — try multiple strategies
        # 1. Direct parse
        try:
            components = json.loads(text)
        except json.JSONDecodeError:
            # 2. Find JSON block in markdown
            m = _re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, _re.DOTALL)
            if m:
                components = json.loads(m.group(1))
            else:
                # 3. Find any {...} with our keys
                m = _re.search(r'(\{[^{}]*"bg"[^{}]*\})', text, _re.DOTALL)
                if m:
                    components = json.loads(m.group(1))
                else:
                    return None, f"no JSON found in: {text[:200]}"

        # Validate
        for key in ["bg", "layout", "deco", "sep", "typo", "content"]:
            if key not in components or not components[key] or len(str(components[key])) < 5:
                return None, f"missing/empty key: {key}"

        # Clean remaining hex colors
        for key in components:
            val = str(components[key])
            hex_colors = _re.findall(r'#[0-9a-fA-F]{6,8}', val)
            for hc in hex_colors:
                # Guess if it's dark or light
                r_val = int(hc[1:3], 16)
                brightness = r_val  # rough proxy
                if brightness < 80:
                    val = val.replace(hc, 'var(--source-dark)')
                elif brightness > 200:
                    val = val.replace(hc, 'var(--source-light)')
                else:
                    val = val.replace(hc, 'var(--source-accent)')
            components[key] = val

        components["content"] = [{"content": content_kind, "code": components["content"]}]
        return components, None

    except Exception as e:
        return None, str(e)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="0=all seeds")
    parser.add_argument("--resume", action="store_true", help="Skip already-extracted seeds")
    parser.add_argument("--seeds-dir", type=Path, default=DEFAULT_SEEDS_DIR)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    catalog = {item["id"]: item for item in json.loads(args.catalog.read_text())}

    # Load existing results for resume
    existing = {}
    if args.resume and args.out.exists():
        existing = json.loads(args.out.read_text())
        print(f"Resuming: {len(existing)} already extracted")

    # Find all seeds
    seed_files = sorted(args.seeds_dir.glob("seed_*.html"))
    if args.limit:
        seed_files = seed_files[:args.limit]

    # Filter out already extracted
    todo = [(sf.stem, sf) for sf in seed_files if sf.stem not in existing]
    print(f"Total seeds: {len(seed_files)}, todo: {len(todo)}")

    if not todo:
        print("Nothing to do")
        return

    client = get_client()
    results = dict(existing)
    success = 0
    fail = 0

    def process(seed_id, seed_path):
        html = seed_path.read_text(errors='replace')
        content_kind = catalog.get(seed_id, {}).get("dims", {}).get("content", "unknown")
        components, err = extract_one(client, args.model, seed_id, html, content_kind)
        return seed_id, components, err

    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(process, sid, sp): sid for sid, sp in todo}
        for i, f in enumerate(as_completed(futures)):
            seed_id, components, err = f.result()
            if components:
                results[seed_id] = components
                success += 1
            else:
                fail += 1
                print(f"  FAIL {seed_id}: {err}")

            # Save every 50
            if (i + 1) % 50 == 0:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
                print(f"  [{i+1}/{len(todo)}] saved ({success} ok, {fail} fail)")

    # Final save
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nDone: {success} ok, {fail} fail, {len(results)} total")
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
