"""HTML Spatial State Extraction — DOM-based geometry analysis via Playwright.

Replaces the python-pptx code parser (spatial_state.py) for HTML-rendered slides.
Uses Playwright to render HTML and query actual DOM element bounding boxes,
providing accurate spatial state without manual coordinate parsing.
"""

import logging
import re
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ...schemas.issue_types import SlideDimensions

from .spatial_state import (
    ContentBlock,
    SlideState,
    AlignmentIssue,
    SLIDE_WIDTH,
    SLIDE_HEIGHT,
    USABLE_LEFT,
    USABLE_RIGHT,
    USABLE_TOP,
    USABLE_BOTTOM,
)

# ── Shared scan JS: cross-card paint-over + slide-bottom truncation ──────────
# Single source of truth for the two extraction-layer "blind-spot" recovery
# scans. It is injected (verbatim, via str.replace of the marker below) into BOTH
# the main inline page.evaluate AND the subprocess-fallback page.evaluate, so the
# two code paths can never diverge. Divergence here was a real bug: the subprocess
# fallback (triggered whenever extraction runs while another sync_playwright
# context is open) lacked these scans and silently reported 0 paint-over defects.
# Keep this as plain JS with SINGLE braces; never embed it directly in an f-string.
_PAINTOVER_C3_SCAN_MARKER = "/* __PAINTOVER_C3_SCAN__ */"
_PAINTOVER_C3_SCAN_JS = r"""
                // ── Slide-bottom truncation scan (C3) ──────────────────────
                // A filled content card whose bottom passes the SLIDE ROOT's
                // boundary is visibly sliced — but only when the root actually
                // clips (overflow:hidden/clip), measured against the root's real
                // bottom (rescaled decks may render on a taller overflow:visible
                // canvas where content below 720 is still visible).
                const truncBlocks = [];
                {
                  let slideRoot = null;
                  for (const el of document.body.querySelectorAll('*')) {
                    const r = el.getBoundingClientRect();
                    if (r.width >= 1255 && r.height >= 695 && Math.abs(r.top) < 6 && Math.abs(r.left) < 6) {
                      slideRoot = el; break;
                    }
                  }
                  const rootStyle = slideRoot ? window.getComputedStyle(slideRoot) : null;
                  const rootClips = rootStyle && (['hidden', 'clip'].includes(rootStyle.overflow) ||
                                                  ['hidden', 'clip'].includes(rootStyle.overflowY));
                  const EDGE = slideRoot ? slideRoot.getBoundingClientRect().bottom : 720;
                  if (slideRoot && rootClips) {
                    const isFilled2 = (st) => {
                      const b = st.backgroundColor, bi = st.backgroundImage;
                      return (b && b !== 'rgba(0, 0, 0, 0)' && b !== 'transparent') || (bi && bi !== 'none');
                    };
                    const directTextOf2 = (el) => {
                      let t = ''; for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent; return t.trim();
                    };
                    for (const el of slideRoot.querySelectorAll('div, section')) {
                      if (directTextOf2(el)) continue;
                      if (el === slideRoot) continue;
                      const r = el.getBoundingClientRect();
                      if (r.width < 40 || r.height < 20) continue;
                      if (r.bottom <= EDGE + 6) continue;
                      if (r.top >= EDGE) continue;
                      if (r.right > 1283) continue;
                      const st = window.getComputedStyle(el);
                      if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) continue;
                      if (!isFilled2(st)) continue;
                      const cls = String(el.className || '').toLowerCase();
                      if (/orb|bg-|blur|glow|halo|blob|backdrop|ornament|gradient/.test(cls)) continue;
                      let internallyClipped = false, p = el.parentElement;
                      while (p && p !== document.body && p !== slideRoot) {
                        const ps = window.getComputedStyle(p);
                        if (['hidden', 'clip'].includes(ps.overflow) || ['hidden', 'clip'].includes(ps.overflowY)) {
                          if (p.getBoundingClientRect().bottom <= EDGE + 6) { internallyClipped = true; break; }
                        }
                        p = p.parentElement;
                      }
                      if (internallyClipped) continue;
                      let contentCut = false;
                      for (const c of el.querySelectorAll('*')) {
                        if (c.children.length !== 0) continue;
                        const cr = c.getBoundingClientRect();
                        if (cr.bottom <= EDGE + 8 || cr.width <= 3 || cr.height <= 3) continue;
                        const isImg = c.tagName.toLowerCase() === 'img';
                        const ct = (c.innerText || '').trim();
                        if (ct.length > 0 || isImg) { contentCut = true; break; }
                      }
                      if (!contentCut) continue;
                      truncBlocks.push({
                        tag: el.tagName.toLowerCase(), id: el.id || '', classes: el.className || '',
                        shapeType: 'shape', text: '', fullText: '',
                        bbox: {x: r.x, y: r.y, width: r.width, height: r.height},
                        visualRect: {x: r.x, y: r.y, width: r.width, height: r.height},
                        fontSize: 0, isOverflowing: false, overflowRight: 0, overflowBottom: 0,
                        clientWidth: el.clientWidth, clientHeight: el.clientHeight,
                        scrollWidth: el.scrollWidth, scrollHeight: el.scrollHeight,
                        isClipped: false, clippedBottom: 0, ancestorClipBottom: 0, ancestorClipRight: 0,
                        contrastRatio: 21, fgColor: '', bgColor: '',
                        renderedLines: 0, isImg: false, imgBroken: false, imgSrc: '', imgCropPct: 0,
                        isEllipsized: false, hasClipPath: false, effectiveFontSize: 0,
                        zIndex: 0, domPath: '', isBottomTruncatedShape: true,
                      });
                    }
                  }
                }
                for (const b of truncBlocks) results.push(b);
"""


logger = logging.getLogger(__name__)

# Viewport dimensions — from single source of truth
VIEWPORT_W = SlideDimensions.VIEWPORT_W
VIEWPORT_H = SlideDimensions.VIEWPORT_H
DEVICE_SCALE_FACTOR = SlideDimensions.DEVICE_SCALE_FACTOR

# Conversion: pixels to inches
PX_TO_INCH_X = SlideDimensions.PX_TO_INCH_X
PX_TO_INCH_Y = SlideDimensions.PX_TO_INCH_Y


def _px_to_inches(bbox_px: dict) -> tuple[float, float, float, float]:
    """Convert pixel bbox {x, y, width, height} to inches."""
    return (
        bbox_px["x"] * PX_TO_INCH_X,
        bbox_px["y"] * PX_TO_INCH_Y,
        bbox_px["width"] * PX_TO_INCH_X,
        bbox_px["height"] * PX_TO_INCH_Y,
    )


_KATEX_CSS_CDN = "https://cdn.jsdelivr.net/npm/katex@0.16.45/dist/katex.min.css"


def _prerender_katex(html: str) -> str:
    """Pre-render $$...$$ and $...$ LaTeX formulas via KaTeX CLI.

    This ensures Playwright sees actual rendered math elements instead of
    raw LaTeX text, enabling accurate bounding box and overflow detection.
    """
    import subprocess as _sp

    # --- Pre-processing: fix common LLM artifacts ---
    # 1. Remove stray trailing $ on HTML lines (LLM artifact)
    html = re.sub(r'\$\s*$', '', html, flags=re.MULTILINE)
    # 2. Fix mismatched $...$$ -> $$...$$
    html = re.sub(
        r'(?<!\$)\$(?!\$)(.+?)\$\$',
        lambda m: f'$${m.group(1)}$$' if any(c in m.group(1) for c in ('\\', '_', '^')) else m.group(0),
        html,
    )

    display_pat = re.compile(r'\$\$(.+?)\$\$', re.DOTALL)
    inline_pat = re.compile(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)')
    # Also match \(...\) and \[...\] delimiters (common in LaTeX-to-HTML)
    # Use a heuristic: \( must appear after > or at text start, and \) before < or text end
    # to avoid matching \( inside display math blocks
    paren_inline_pat = re.compile(r'(?<=>)\s*\\\((.+?)\\\)\s*(?=<|:)', re.DOTALL)
    bracket_display_pat = re.compile(r'\\\[(.+?)\\\]', re.DOTALL)

    formulas: list[tuple[str, str, bool]] = []
    for m in display_pat.finditer(html):
        latex = m.group(1).strip()
        if any(c in latex for c in ('\\', '_', '^')):
            formulas.append((m.group(0), latex, True))
    for m in bracket_display_pat.finditer(html):
        latex = m.group(1).strip()
        if any(c in latex for c in ('\\', '_', '^')):
            formulas.append((m.group(0), latex, True))
    for m in inline_pat.finditer(html):
        latex = m.group(1).strip()
        if any(c in latex for c in ('\\', '_', '^')):
            formulas.append((m.group(0), latex, False))
    for m in paren_inline_pat.finditer(html):
        latex = m.group(1).strip()
        if any(c in latex for c in ('\\', '_', '^')):
            formulas.append((m.group(0), latex, False))

    if not formulas:
        return html

    rendered_any = False
    for full, latex, display in formulas:
        try:
            cmd = ["npx", "katex", "--no-throw-on-error"]
            if display:
                cmd.append("--display-mode")
            r = _sp.run(cmd, input=latex, capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                html = html.replace(full, r.stdout.strip(), 1)
                rendered_any = True
        except Exception:
            pass

    if rendered_any and _KATEX_CSS_CDN not in html:
        katex_link = f'<link rel="stylesheet" href="{_KATEX_CSS_CDN}">'
        if "<head>" in html:
            html = html.replace("<head>", f"<head>\n{katex_link}", 1)
        elif "<style>" in html:
            html = html.replace("<style>", f"{katex_link}\n<style>", 1)

    return html


def extract_html_slide_state(
    slide_id: int,
    html_code: str,
    browser=None,
) -> SlideState:
    """Extract spatial state from rendered HTML via Playwright DOM queries.

    Args:
        slide_id: Slide number
        html_code: Complete HTML page content
        browser: Optional Playwright browser instance (created if not provided)

    Returns:
        SlideState with accurate bounding boxes from rendered DOM
    """
    own_browser = browser is None
    playwright_ctx = None

    try:
        if own_browser:
            try:
                from playwright.sync_api import sync_playwright
                playwright_ctx = sync_playwright().start()
                browser = playwright_ctx.chromium.launch(headless=True)
            except Exception as e:
                if "asyncio" in str(e).lower():
                    # Fall back to subprocess-based extraction
                    return _extract_via_subprocess(slide_id, html_code)
                raise

        # Fix image paths for rendering
        # 1. Absolute paths → file://
        html_code = re.sub(
            r'(<img\s[^>]*src=["\'])(/[^"\']+)(["\'])',
            r'\1file://\2\3',
            html_code,
        )
        # 2. Relative paths → resolve from CWD upward (same as html_codegen_compiler)
        import os as _os
        _cwd = _os.getcwd()
        _search_roots = [_cwd]
        _probe = Path(_cwd)
        for _ in range(6):
            if (_probe / "cases").is_dir() or (_probe / "app").is_dir():
                if str(_probe) != _cwd:
                    _search_roots.append(str(_probe))
                break
            _probe = _probe.parent

        def _resolve_rel_src(m):
            prefix, path, suffix = m.group(1), m.group(2), m.group(3)
            if path.startswith(('file://', 'http://', 'https://', 'data:', '/')):
                return m.group(0)
            for root in _search_roots:
                abs_path = _os.path.join(root, path)
                if _os.path.exists(abs_path):
                    return f'{prefix}file://{abs_path}{suffix}'
            return m.group(0)

        html_code = re.sub(
            r'(<img\s[^>]*src=["\'])([^"\']+)(["\'])',
            _resolve_rel_src,
            html_code,
        )

        # Pre-render KaTeX formulas for accurate bounding boxes
        html_code = _prerender_katex(html_code)

        page = browser.new_page(
            viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
            device_scale_factor=DEVICE_SCALE_FACTOR,
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(html_code)
            tmp_path = tmp.name

        try:
            page.goto(f"file://{tmp_path}", wait_until="networkidle")
            page.wait_for_timeout(200)

            # Extract all visible content elements with bounding boxes.
            # The paint-over/C3 scans are injected from the shared constant (same
            # code the subprocess fallback uses) so the two paths never diverge.
            _main_extract_js = """() => {
                // Fix body overflow:hidden blind spot — temporarily remove
                // overflow:hidden from body and html so getBoundingClientRect()
                // returns true element dimensions, not clipped ones.
                const bodyOvf = document.body.style.overflow;
                const htmlOvf = document.documentElement.style.overflow;
                const bodyOvfComp = window.getComputedStyle(document.body).overflow;
                const htmlOvfComp = window.getComputedStyle(document.documentElement).overflow;
                if (bodyOvfComp === 'hidden' || htmlOvfComp === 'hidden') {
                    document.body.style.overflow = 'visible';
                    document.documentElement.style.overflow = 'visible';
                }

                // Helper: parse CSS color to {r,g,b}
                function parseColor(str) {
                    const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/);
                    if (m) return {r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1.0};
                    return null;
                }
                // Helper: alpha-composite fg color onto bg color
                function compositeAlpha(fg, bg) {
                    if (!fg || fg.a === undefined || fg.a >= 1.0) return fg;
                    if (!bg) bg = {r: 255, g: 255, b: 255, a: 1.0};
                    const a = fg.a;
                    return {
                        r: Math.round(fg.r * a + bg.r * (1 - a)),
                        g: Math.round(fg.g * a + bg.g * (1 - a)),
                        b: Math.round(fg.b * a + bg.b * (1 - a)),
                        a: 1.0
                    };
                }
                // Helper: relative luminance (WCAG 2.1)
                function luminance(c) {
                    const sRGB = [c.r/255, c.g/255, c.b/255];
                    const lin = sRGB.map(v => v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4));
                    return 0.2126*lin[0] + 0.7152*lin[1] + 0.0722*lin[2];
                }
                // Helper: contrast ratio
                function contrastRatio(fg, bg) {
                    const L1 = Math.max(luminance(fg), luminance(bg));
                    const L2 = Math.min(luminance(fg), luminance(bg));
                    return (L1 + 0.05) / (L2 + 0.05);
                }
                // Helper: get effective background color
                // Uses elementsFromPoint to detect overlay divs that sit
                // on top in z-order, then falls back to parent-chain walk.
                function getEffectiveBg(el) {
                    // Special handling for table cells: <tr> background is not
                    // returned by elementsFromPoint (tr doesn't participate in
                    // hit testing), so we must check table ancestors first.
                    const tag = el.tagName.toLowerCase();
                    if (tag === 'th' || tag === 'td') {
                        let tableAnc = el.parentElement;
                        while (tableAnc && tableAnc !== document.body) {
                            const tTag = tableAnc.tagName.toLowerCase();
                            if (tTag === 'tr' || tTag === 'thead' || tTag === 'tbody' || tTag === 'tfoot' || tTag === 'table') {
                                const s = window.getComputedStyle(tableAnc);
                                const bg = s.backgroundColor;
                                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                                    return parseColor(bg);
                                }
                            }
                            if (tTag === 'table') break;
                            tableAnc = tableAnc.parentElement;
                        }
                    }
                    const ownStyle = window.getComputedStyle(el);
                    const ownBg = ownStyle.backgroundColor;
                    if (ownBg && ownBg !== 'rgba(0, 0, 0, 0)' && ownBg !== 'transparent') {
                        const parsed = parseColor(ownBg);
                        if (parsed && parsed.a >= 1.0) return parsed;
                        // Semi-transparent bg: composite with parent background
                        if (parsed && parsed.a > 0 && parsed.a < 1.0) {
                            // Find the opaque parent background to composite against
                            let parentBg = {r: 255, g: 255, b: 255, a: 1.0};
                            let pNode = el.parentElement;
                            while (pNode && pNode !== document.documentElement) {
                                const ps = window.getComputedStyle(pNode);
                                const pbg = ps.backgroundColor;
                                if (pbg && pbg !== 'rgba(0, 0, 0, 0)' && pbg !== 'transparent') {
                                    const pp = parseColor(pbg);
                                    if (pp && pp.a >= 1.0) { parentBg = pp; break; }
                                }
                                pNode = pNode.parentElement;
                            }
                            return compositeAlpha(parsed, parentBg);
                        }
                    }
                    const rect = el.getBoundingClientRect();
                    const cx = rect.left + rect.width / 2;
                    const cy = rect.top + rect.height / 2;
                    // elementsFromPoint returns front-to-back order
                    try {
                        const stack = document.elementsFromPoint(cx, cy);
                        // Find el's position in the stack
                        const selfIdx = stack.indexOf(el);
                        // Check elements behind el (higher index = further back)
                        const start = selfIdx >= 0 ? selfIdx + 1 : 0;
                        for (let i = start; i < stack.length; i++) {
                            const node = stack[i];
                            if (node === document.documentElement) continue;
                            const s = window.getComputedStyle(node);
                            const bg = s.backgroundColor;
                            if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                                return parseColor(bg);
                            }
                        }
                    } catch(e) {}
                    // Fallback: walk up parent chain
                    let node = el.parentElement;
                    while (node && node !== document.documentElement) {
                        const s = window.getComputedStyle(node);
                        const bg = s.backgroundColor;
                        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
                            return parseColor(bg);
                        }
                        node = node.parentElement;
                    }
                    return {r: 255, g: 255, b: 255}; // default white
                }
                // Helper: count rendered lines via getClientRects
                function countLines(el) {
                    // Only for text-bearing elements
                    const range = document.createRange();
                    const childNodes = el.childNodes;
                    if (childNodes.length === 0) return 0;
                    range.setStart(childNodes[0], 0);
                    range.setEnd(childNodes[childNodes.length - 1], childNodes[childNodes.length - 1].length || 0);
                    const rects = range.getClientRects();
                    if (rects.length === 0) return 0;
                    // Count unique y-positions (each line has a distinct top)
                    const tops = new Set();
                    for (const r of rects) {
                        tops.add(Math.round(r.top));
                    }
                    return tops.size;
                }

                const results = [];
                const allElements = document.body.querySelectorAll('*');

                for (const el of allElements) {
                    const tag = el.tagName.toLowerCase();
                    if (['html', 'body', 'head', 'style', 'script', 'meta', 'link', 'br'].includes(tag)) continue;
                    // Skip KaTeX internal elements
                    if (el.closest('.katex') && !el.classList.contains('katex-display')) continue;
                    if (el.closest('.katex-mathml')) continue;

                    const rect = el.getBoundingClientRect();
                    if (rect.width < 3 || rect.height < 3) continue;

                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) continue;

                    // Get direct text content (not including children)
                    let directText = '';
                    for (const node of el.childNodes) {
                        if (node.nodeType === 3) directText += node.textContent;
                    }
                    directText = directText.trim();

                    const isImg = tag === 'img';
                    const isContainer = ['div', 'section', 'main', 'article', 'header', 'footer', 'nav'].includes(tag);
                    const isStructuralContainer = ['ul', 'ol', 'li', 'table', 'tbody', 'thead', 'tfoot', 'tr', 'td', 'th', 'dl', 'dt', 'dd', 'details', 'summary', 'fieldset', 'figure', 'figcaption'].includes(tag);

                    // Determine element type
                    let shapeType = 'textbox';

                    // Skip pure containers with no direct text — UNLESS they have
                    // a visible fill (background-color or background-image). Filled
                    // containers (chart bars, accent panels, card backgrounds) are
                    // significant visual elements that must participate in overlap
                    // detection. They are extracted as shape_type='shape'.
                    const isFilled = (() => {
                        const bg = style.backgroundColor;
                        const bi = style.backgroundImage;
                        const hasBg = bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent';
                        const hasBi = bi && bi !== 'none';
                        return !!(hasBg || hasBi);
                    })();
                    if ((isContainer || isStructuralContainer) && !directText && !isImg) {
                        // Extract filled containers as shape blocks if visible enough
                        if (!isFilled || rect.width < 20 || rect.height < 14) continue;
                        shapeType = 'shape';
                    }

                    // Compute styled height (CSS declared height before overflow expansion)
                    // and overflow property for styled-boundary detection
                    let styledHeight = 0;
                    const rawH = style.height;
                    if (rawH && rawH !== 'auto' && rawH !== '' && !rawH.includes('%')) {
                        styledHeight = parseFloat(rawH) || 0;
                    }
                    const styledOverflow = style.overflow || '';

                    // Get font size
                    const fontSize = parseFloat(style.fontSize) || 16;

                    // Effective font size accounting for transform:scale
                    let effectiveFontSize = fontSize;
                    const tfm = style.transform;
                    if (tfm && tfm !== 'none') {
                        const scaleMatch = tfm.match(/matrix\\(([\\d.e+-]+)/);
                        if (scaleMatch) {
                            const scaleFactor = Math.abs(parseFloat(scaleMatch[1]));
                            if (scaleFactor > 0 && scaleFactor < 1) effectiveFontSize = fontSize * scaleFactor;
                        }
                    }

                    // clip-path detection
                    const hasClipPath = style.clipPath && style.clipPath !== 'none';

                    // Refine element type
                    if (isImg) shapeType = 'picture';
                    else if (tag === 'table') shapeType = 'table';
                    else if (tag === 'svg' || el.closest('svg')) shapeType = 'chart';
                    else if (['h1', 'h2'].includes(tag)) shapeType = 'title';

                    // Check overflow — also measure overflow amount
                    let isOverflowing = el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2;
                    let overflowRight = Math.max(0, el.scrollWidth - el.clientWidth);
                    let overflowBottom = Math.max(0, el.scrollHeight - el.clientHeight);
                    let isSvgText = false;

                    // --- SVG element detection ---
                    // Track whether this element is inside an SVG at all
                    const isInSvg = !!el.closest('svg');

                    // SVG text clipping: getBBox gives actual text extent.
                    // Check against (1) SVG viewport and (2) sibling <rect>
                    // that visually contains this text (common pattern: rect+text
                    // siblings form a card/node in flow diagrams).
                    // Also use getComputedTextLength() for precise width measurement.
                    if ((tag === 'text' || tag === 'tspan') && isInSvg) {
                        isSvgText = true;
                        try {
                            const bbox = el.getBBox();
                            const svgRoot = el.closest('svg');
                            // --- Check 1: text vs SVG viewport ---
                            const vb = svgRoot.viewBox && svgRoot.viewBox.baseVal;
                            const svgW = (vb && vb.width) || (svgRoot.width && svgRoot.width.baseVal && svgRoot.width.baseVal.value) || svgRoot.clientWidth;
                            const svgH = (vb && vb.height) || (svgRoot.height && svgRoot.height.baseVal && svgRoot.height.baseVal.value) || svgRoot.clientHeight;
                            const svgX = (vb && vb.x) || 0;
                            const svgY = (vb && vb.y) || 0;
                            let maxClipH = Math.max(0, (bbox.x + bbox.width) - (svgX + svgW)) + Math.max(0, svgX - bbox.x);
                            let maxClipV = Math.max(0, (bbox.y + bbox.height) - (svgY + svgH)) + Math.max(0, svgY - bbox.y);
                            // --- Check 2: text vs containing sibling <rect> ---
                            // Use getComputedTextLength() for precise text width when available
                            let textRenderW = bbox.width;
                            try {
                                if (tag === 'text' && typeof el.getComputedTextLength === 'function') {
                                    textRenderW = Math.max(textRenderW, el.getComputedTextLength());
                                }
                            } catch(e2) {}
                            const parent = el.parentElement;
                            if (parent) {
                                const rects = parent.querySelectorAll(':scope > rect');
                                const cx = bbox.x + textRenderW / 2;
                                const cy = bbox.y + bbox.height / 2;
                                for (const r of rects) {
                                    const rx = parseFloat(r.getAttribute('x') || 0);
                                    const ry = parseFloat(r.getAttribute('y') || 0);
                                    const rw = parseFloat(r.getAttribute('width') || 0);
                                    const rh = parseFloat(r.getAttribute('height') || 0);
                                    if (rw < 10 || rh < 10) continue;
                                    // text center must be inside rect
                                    if (cx >= rx && cx <= rx + rw && cy >= ry && cy <= ry + rh) {
                                        const cR = Math.max(0, (bbox.x + textRenderW) - (rx + rw));
                                        const cL = Math.max(0, rx - bbox.x);
                                        const cB = Math.max(0, (bbox.y + bbox.height) - (ry + rh));
                                        const cT = Math.max(0, ry - bbox.y);
                                        maxClipH = Math.max(maxClipH, cR + cL);
                                        maxClipV = Math.max(maxClipV, cB + cT);
                                        break;
                                    }
                                }
                            }
                            if (maxClipH > 0.5 || maxClipV > 0.5) {
                                isOverflowing = true;
                                overflowRight = Math.max(overflowRight, Math.round(maxClipH));
                                overflowBottom = Math.max(overflowBottom, Math.round(maxClipV));
                            }
                        } catch(e) {}
                    }

                    // SVG non-text element viewBox clipping: rect, circle, ellipse, path, g
                    // that extend past the SVG viewport are visually clipped
                    if (isInSvg && !isSvgText && !['svg', 'defs', 'clippath', 'lineargradient', 'radialgradient', 'stop', 'marker'].includes(tag)) {
                        try {
                            const bbox = el.getBBox();
                            if (bbox.width >= 5 && bbox.height >= 5) {
                                const svgRoot = el.closest('svg');
                                const vb = svgRoot.viewBox && svgRoot.viewBox.baseVal;
                                const svgW = (vb && vb.width) || (svgRoot.width && svgRoot.width.baseVal && svgRoot.width.baseVal.value) || svgRoot.clientWidth;
                                const svgH = (vb && vb.height) || (svgRoot.height && svgRoot.height.baseVal && svgRoot.height.baseVal.value) || svgRoot.clientHeight;
                                const svgX = (vb && vb.x) || 0;
                                const svgY = (vb && vb.y) || 0;
                                const clipR = Math.max(0, (bbox.x + bbox.width) - (svgX + svgW));
                                const clipL = Math.max(0, svgX - bbox.x);
                                const clipB = Math.max(0, (bbox.y + bbox.height) - (svgY + svgH));
                                const clipT = Math.max(0, svgY - bbox.y);
                                const totalClipH = clipR + clipL;
                                const totalClipV = clipB + clipT;
                                if (totalClipH > 2 || totalClipV > 2) {
                                    isOverflowing = true;
                                    overflowRight = Math.max(overflowRight, Math.round(totalClipH));
                                    overflowBottom = Math.max(overflowBottom, Math.round(totalClipV));
                                }
                            }
                        } catch(e) {}
                    }

                    // Check overflow:hidden clipping
                    const overflowStyle = style.overflow + ' ' + style.overflowX + ' ' + style.overflowY;
                    const hasHidden = overflowStyle.includes('hidden');

                    // Detect visual overflow when CSS overflow:visible (default)
                    // scrollHeight == clientHeight in this case, so check child rects
                    if (!isOverflowing && !hasHidden && el.children.length > 0) {
                        const parentRect = el.getBoundingClientRect();
                        let visOvfR = 0, visOvfB = 0;
                        for (const child of el.children) {
                            const cr = child.getBoundingClientRect();
                            if (cr.width > 0 && cr.height > 0) {
                                visOvfR = Math.max(visOvfR, cr.right - parentRect.right);
                                visOvfB = Math.max(visOvfB, cr.bottom - parentRect.bottom);
                            }
                        }
                        if (visOvfR > 2 || visOvfB > 2) {
                            isOverflowing = true;
                            overflowRight = Math.max(overflowRight, Math.round(visOvfR));
                            overflowBottom = Math.max(overflowBottom, Math.round(visOvfB));
                        }
                    }
                    const isClipped = hasHidden && (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2);
                    const clippedBottom = isClipped ? Math.max(0, el.scrollHeight - el.clientHeight) : 0;

                    // text-overflow:ellipsis detection
                    const isEllipsized = style.textOverflow === 'ellipsis' && hasHidden && el.scrollWidth > el.clientWidth;

                    // Contrast ratio (for text elements only)
                    // For SVG text, use the 'fill' attribute/computed style instead of 'color'
                    let contrastVal = 0;
                    let fgColor = '';
                    let bgColor = '';
                    if (directText.length > 0 && !isImg) {
                        let fgColorStr = style.color;
                        if (isSvgText) {
                            // SVG text uses 'fill' for foreground color
                            const svgFill = style.fill || el.getAttribute('fill');
                            if (svgFill && svgFill !== 'none') fgColorStr = svgFill;
                        }
                        const fg = parseColor(fgColorStr);
                        const bg = getEffectiveBg(el);
                        if (fg && bg) {
                            contrastVal = Math.round(contrastRatio(fg, bg) * 100) / 100;
                            fgColor = fgColorStr;
                            bgColor = `rgb(${bg.r},${bg.g},${bg.b})`;
                        }
                    }

                    // Rendered line count (text elements with >10 chars)
                    let lineCount = 0;
                    if (directText.length > 10 && !isImg) {
                        try { lineCount = countLines(el); } catch(e) {}
                    }

                    // Image loading check
                    let imgBroken = false;
                    let imgSrc = '';
                    let imgCropPct = 0;
                    if (isImg) {
                        imgSrc = el.src || el.getAttribute('src') || '';
                        imgBroken = el.complete && el.naturalWidth === 0 && imgSrc.length > 0;
                        // object-fit crop detection (cover, none, scale-down)
                        if (el.naturalWidth > 0 && el.naturalHeight > 0) {
                            const natW = el.naturalWidth, natH = el.naturalHeight;
                            const boxW = rect.width, boxH = rect.height;
                            const fit = style.objectFit || 'fill';
                            if (fit === 'cover') {
                                const natRatio = natW / natH;
                                const boxRatio = boxW / boxH;
                                imgCropPct = natRatio > boxRatio
                                    ? 1 - (boxRatio / natRatio)
                                    : 1 - (natRatio / boxRatio);
                            } else if (fit === 'none') {
                                const visW = Math.min(boxW, natW);
                                const visH = Math.min(boxH, natH);
                                imgCropPct = 1 - (visW * visH) / (natW * natH);
                            } else if (fit === 'scale-down') {
                                if (natW <= boxW && natH <= boxH) {
                                    imgCropPct = 0;  // fits without scaling
                                } else {
                                    imgCropPct = 0;  // behaves like contain
                                }
                            }
                            // fill/contain: no crop
                            imgCropPct = Math.round(imgCropPct * 1000) / 1000;
                        }
                    }

                    // z-index
                    const zIndex = parseInt(style.zIndex) || 0;

                    // Visual bounds including descendants (not just direct children)
                    // For KaTeX: include the .katex container's bbox (which is accurate)
                    // but skip its internal elements whose absolute-positioned sub-elements
                    // (fractions, subscripts) return inflated getBoundingClientRect() values.
                    let vLeft = rect.x, vTop = rect.y, vRight = rect.right, vBottom = rect.bottom;
                    for (const desc of el.querySelectorAll('*')) {
                        // Skip KaTeX INTERNAL elements — their bbox is unreliable.
                        // But include the .katex container itself (its bbox is correct).
                        const katexAncestor = desc.closest('.katex');
                        if (katexAncestor && katexAncestor !== desc) continue;
                        if (desc.closest('.katex-mathml')) continue;
                        const cr = desc.getBoundingClientRect();
                        if (cr.width > 0 && cr.height > 0) {
                            vLeft = Math.min(vLeft, cr.x);
                            vTop = Math.min(vTop, cr.y);
                            vRight = Math.max(vRight, cr.right);
                            vBottom = Math.max(vBottom, cr.bottom);
                        }
                    }

                    // Ancestor clipping: check if this element is visually clipped
                    // by any ancestor with overflow:hidden/scroll/auto OR by any
                    // positioned ancestor with explicit fixed height (common pattern:
                    // card containers with position:absolute + height but no overflow prop)
                    let ancestorClipBottom = 0;
                    let ancestorClipRight = 0;
                    let clipParentTag = '';
                    let clipParentClass = '';
                    let clipParentHeight = 0;
                    let anc = el.parentElement;
                    while (anc && anc !== document.body) {
                        const aStyle = window.getComputedStyle(anc);
                        const aOvf = (aStyle.overflow + ' ' + aStyle.overflowY).toLowerCase();
                        const hasOverflowProp = aOvf.includes('hidden') || aOvf.includes('scroll') || aOvf.includes('auto');
                        // Also detect positioned ancestors with explicit height
                        // that act as visual boundaries even without overflow:hidden
                        const aPos = aStyle.position;
                        const hasExplicitH = aStyle.height && aStyle.height !== 'auto' && aStyle.height !== '';
                        const isPositioned = aPos === 'absolute' || aPos === 'relative' || aPos === 'fixed';
                        const isVisualBoundary = hasOverflowProp || (isPositioned && hasExplicitH);
                        if (isVisualBoundary) {
                            const aRect = anc.getBoundingClientRect();
                            const clipB = Math.max(0, rect.bottom - aRect.bottom);
                            const clipR = Math.max(0, rect.right - aRect.right);
                            if (clipB > 2) {
                                ancestorClipBottom = Math.max(ancestorClipBottom, Math.round(clipB));
                                if (!clipParentTag) {
                                    clipParentTag = anc.tagName.toLowerCase();
                                    clipParentClass = (anc.className || '').toString().split(' ').filter(c=>c)[0] || '';
                                    clipParentHeight = Math.round(aRect.height);
                                }
                            }
                            if (clipR > 2) ancestorClipRight = Math.max(ancestorClipRight, Math.round(clipR));
                        }
                        anc = anc.parentElement;
                    }

                    // Build DOM path for parent-child relationship detection
                    let domPath = [];
                    let pathEl = el;
                    while (pathEl && pathEl !== document.body) {
                        const pTag = pathEl.tagName.toLowerCase();
                        const pIdx = Array.from(pathEl.parentElement?.children || []).indexOf(pathEl);
                        domPath.unshift(pTag + '[' + pIdx + ']');
                        pathEl = pathEl.parentElement;
                    }

                    results.push({
                        tag, id: el.id || '', classes: el.className || '',
                        shapeType, text: directText.substring(0, 500),
                        fullText: el.innerText ? el.innerText.substring(0, 1000) : '',
                        bbox: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
                        visualRect: {x: vLeft, y: vTop, width: vRight - vLeft, height: vBottom - vTop},
                        fontSize, isOverflowing, overflowRight, overflowBottom, isSvgText, isInSvg,
                        clientWidth: el.clientWidth, clientHeight: el.clientHeight,
                        scrollWidth: el.scrollWidth, scrollHeight: el.scrollHeight,
                        isClipped: isClipped || ancestorClipBottom > 2 || isEllipsized || hasClipPath || imgCropPct > 0.15,
                        clippedBottom: Math.max(clippedBottom, ancestorClipBottom),
                        ancestorClipBottom, ancestorClipRight,
                        clipParentTag, clipParentClass, clipParentHeight,
                        contrastRatio: contrastVal, fgColor, bgColor,
                        renderedLines: lineCount,
                        isImg, imgBroken, imgSrc, imgCropPct,
                        isEllipsized, hasClipPath, effectiveFontSize,
                        zIndex,
                        domPath: domPath.join('/'),
                        styledHeight, isFilled, styledOverflow,
                    });
                }

                // Viewport exceedance scan — catch empty bar/shape divs
                // that overflow the 1280×720 canvas (skipped by main loop
                // because they have no directText).
                const exceedances = [];
                for (const el of document.body.querySelectorAll('*')) {
                    const st = window.getComputedStyle(el);
                    if (st.display === 'none' || st.visibility === 'hidden') continue;
                    if (parseFloat(st.opacity) === 0) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 3 || r.height < 3) continue;
                    const exR = Math.round(Math.max(0, r.right - 1280));
                    const exB = Math.round(Math.max(0, r.bottom - 720));
                    if (exR > 5 || exB > 5) {
                        let label = el.id || '';
                        if (!label && el.className) {
                            label = typeof el.className === 'string' ? el.className.split(' ')[0] : '';
                        }
                        if (!label) {
                            let p = el.parentElement;
                            while (p && p !== document.body && !label) {
                                label = p.id || '';
                                p = p.parentElement;
                            }
                        }
                        exceedances.push({
                            tag: el.tagName.toLowerCase(),
                            label: label.substring(0, 80),
                            right: Math.round(r.right),
                            bottom: Math.round(r.bottom),
                            exRight: exR, exBottom: exB,
                            x: Math.round(r.x), y: Math.round(r.y),
                            w: Math.round(r.width), h: Math.round(r.height),
                        });
                    }
                }
                // Restore original overflow settings
                document.body.style.overflow = bodyOvf;
                document.documentElement.style.overflow = htmlOvf;

                /* __PAINTOVER_C3_SCAN__ */

                return {elements: results, viewportExceedances: exceedances};
            }"""
            _main_extract_js = _main_extract_js.replace(
                _PAINTOVER_C3_SCAN_MARKER, _PAINTOVER_C3_SCAN_JS)
            elements = page.evaluate(_main_extract_js)
        finally:
            os.unlink(tmp_path)

        # Unpack dict return (elements + viewport exceedances)
        if isinstance(elements, dict):
            viewport_exceedances = elements.get("viewportExceedances", [])
            elements = elements.get("elements", [])
        else:
            viewport_exceedances = []

        page.close()

    except Exception as e:
        logger.error("HTML spatial state extraction failed: %s", e)
        return SlideState(slide_id=slide_id)
    finally:
        if own_browser:
            try:
                browser.close()
            except Exception:
                pass
            if playwright_ctx:
                try:
                    playwright_ctx.stop()
                except Exception:
                    pass

    return _build_state_from_elements(slide_id, elements, viewport_exceedances=viewport_exceedances)


def _visual_rect(b: ContentBlock) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) using visual bounds if available, else CSS bbox."""
    if hasattr(b, '_visual_bounds') and b._visual_bounds:
        return b._visual_bounds
    return (b.x, b.y, b.w, b.h)


def _detect_overlaps(blocks: list[ContentBlock]) -> list[tuple[str, str, float]]:
    """Detect overlapping block pairs using a pure-geometry rule.

    Three cases:
      1. No intersection → skip
      2. Full containment (A⊂B or B⊂A, ≥90% of one fits inside the other)
         → skip (normal nesting / layering)
      3. Partial overlap (intersection exists, but BOTH sides have substantial
         non-intersection parts) → flag as a defect

    This replaces the previous DOM-path / SVG-tag / panel-heuristic approach,
    which was fragile and kept missing real defects. The geometry alone decides.
    """
    MIN_DIM_IN = 0.0625          # ~6px: filter subpixel/line-height/rounding grazes
    MIN_ELEM_AREA = 0.05         # skip negligible elements
    CONTAIN_THRESH = 0.90        # 90% of an element inside another = "full containment"
    MIN_OVERLAP_FRAC = 0.03      # 3% of smaller element = "real partial overlap"

    def _close_dom_ancestor(pa: str, pb: str, max_depth_diff: int = 5) -> bool:
        """True if a and b share a close common DOM ancestor.

        Chart-internal structure: a heading <h3> and a bar <div> under the same
        chart container are NOT a defect — the heading is intentionally placed
        above the chart bars within a shared parent. We detect this by checking
        if one dom_path is a prefix of the other (ancestor/descendant) or they
        share a common prefix within `max_depth_diff` levels of each.
        In practice chart bars can be 4-5 levels deep within the chart container
        while the heading is 1 level deep, so max_depth_diff=5.
        """
        if not pa or not pb:
            return False
        # Direct ancestor/descendant
        if pa.startswith(pb + "/") or pb.startswith(pa + "/"):
            return True
        # Close common ancestor: compare path segments
        sa = pa.split("/")
        sb = pb.split("/")
        common = 0
        for x, y in zip(sa, sb):
            if x == y:
                common += 1
            else:
                break
        # Both within max_depth_diff levels of the common ancestor
        tail_a = len(sa) - common
        tail_b = len(sb) - common
        return tail_a <= max_depth_diff and tail_b <= max_depth_diff

    overlaps = []
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            a, b = blocks[i], blocks[j]
            ax, ay, aw, ah = _visual_rect(a)
            bx, by, bw, bh = _visual_rect(b)

            area_a = aw * ah
            area_b = bw * bh

            # Skip negligible elements
            if area_a < MIN_ELEM_AREA or area_b < MIN_ELEM_AREA:
                continue

            # Intersection
            ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
            iy = max(0, min(ay + ah, by + bh) - max(ay, by))

            # No meaningful 2D intersection
            if ix < MIN_DIM_IN or iy < MIN_DIM_IN:
                continue

            inter = ix * iy

            # Text char counts (used in multiple filters below)
            a_tc = a.text_chars if isinstance(a.text_chars, int) else 0
            b_tc = b.text_chars if isinstance(b.text_chars, int) else 0

            # Full containment: one element ≥90% inside the other → nesting, skip
            # BUT only if they have a real ancestor/descendant DOM relationship.
            # Sibling elements where a large one's edge overlaps a small one
            # should NOT be treated as nesting — that's a real collision.
            #
            # EXCEPTION: decorative background elements (no text, area > 70% of
            # canvas) overlapping anything is normal — they ARE the background.
            CANVAS_AREA = (SLIDE_WIDTH * SLIDE_HEIGHT)  # ~100 sq.in.
            a_is_bg = (a_tc == 0 and area_a > CANVAS_AREA * 0.70)
            b_is_bg = (b_tc == 0 and area_b > CANVAS_AREA * 0.70)
            if a_is_bg or b_is_bg:
                continue  # background/decorative element, skip

            is_full_containment = (
                inter / max(area_a, 0.001) > CONTAIN_THRESH
                or inter / max(area_b, 0.001) > CONTAIN_THRESH
            )
            if is_full_containment:
                if not (a.dom_path and b.dom_path):
                    continue  # no dom_path info, conservatively skip

                # Case 1: genuine ancestor/descendant nesting (HTML div>span)
                if (b.dom_path.startswith(a.dom_path + "/") or
                        a.dom_path.startswith(b.dom_path + "/")):
                    continue

                # Case 2: Close DOM siblings with geometric containment.
                # Skip when it's structural nesting (SVG rect+text, filled
                # card containing a label, icon badge in a header). But when
                # BOTH sides carry substantial text (≥5 chars each), it's a
                # real layout collision — e.g. oversized title div covering
                # a subtitle div.
                if _close_dom_ancestor(a.dom_path, b.dom_path, max_depth_diff=3):
                    both_have_text = (a_tc >= 5 and b_tc >= 5)
                    if not both_have_text:
                        continue
                    # Inline siblings in the same parent (span/em/strong/a
                    # within one <p> or <li>) are normal text flow, not a
                    # layout collision.
                    _INLINE = {"span","a","strong","em","b","i","mark","code","small","sub","sup"}
                    a_var = (a.var_name or "").lower()
                    b_var = (b.var_name or "").lower()
                    if a_var in _INLINE and b_var in _INLINE:
                        a_par = "/".join((a.dom_path or "").split("/")[:-1])
                        b_par = "/".join((b.dom_path or "").split("/")[:-1])
                        if a_par and a_par == b_par:
                            continue

                # else: siblings or unrelated with full containment — real
                # collision (e.g. two cards stacked at the same position)

            # Chart-internal filter: a text heading (textbox) overlapping an
            # empty shape (chart bar, accent) within the SAME chart container
            # is a normal chart layout, not a defect. The heading spans across
            # the bar area by design. Skip when:
            #   - one is text, the other is an empty shape (tc=0)
            #   - they share a close DOM ancestor (within 2 levels)
            #   - the shape is SMALLER than the text element (chart bars are
            #     small; a large card overlapping a subtitle is NOT chart-internal)
            if ((a_tc > 0 and b_tc == 0 and b.shape_type == "shape") or
                    (b_tc > 0 and a_tc == 0 and a.shape_type == "shape")):
                text_blk = a if a_tc > 0 else b
                shape_blk = b if a_tc > 0 else a
                shape_area = _visual_rect(shape_blk)[2] * _visual_rect(shape_blk)[3]
                text_area = _visual_rect(text_blk)[2] * _visual_rect(text_blk)[3]
                if shape_area <= text_area and _close_dom_ancestor(a.dom_path, b.dom_path, max_depth_diff=2):
                    continue

            # Partial overlap: real collision where both sides stick out
            ratio = inter / max(min(area_a, area_b), 0.001)
            # Two checks (either triggers a flag):
            # 1. Ratio-based: intersection > 3% of the smaller element (catches
            #    small-on-small and small-on-large collisions)
            # 2. Absolute-size: both overlap dimensions >= 8px (~0.08in) even if
            #    ratio is tiny (catches two LARGE panels overlapping by 12px —
            #    the Flowing "Core idea" card↔"Key results" card case where 12px
            #    overlap is visible but only 1% of the large card area)
            MIN_ABS_OVERLAP_IN = 0.08  # ~8px
            if ratio > MIN_OVERLAP_FRAC or (ix >= MIN_ABS_OVERLAP_IN and iy >= MIN_ABS_OVERLAP_IN):
                overlaps.append((a.block_id, b.block_id, round(ratio, 3)))

    return overlaps


def _detect_styled_overflow(blocks: list[ContentBlock]) -> list[str]:
    """Detect text blocks whose bottom extends past a filled container's
    styled visual boundary (CSS height).

    When a container has `overflow:visible`, its `getBoundingClientRect()` height
    expands to include overflowing children — but its visual boundary (background,
    border, rounded corners) stops at the CSS `height`. Text past that boundary
    appears to "spill out of the card" even though it renders. This check catches
    that by comparing the child's bottom against the container's styled_h_px
    (the CSS height, NOT the rendered bbox height).

    Only flags text blocks (text_chars > 0) that exceed the boundary by >8px,
    and only for filled containers (those with a visible background/border).
    Also flags filled child elements (cards/panels with background) that exceed
    the boundary — a visible card poking out of its parent container is a defect
    even if the card itself has no direct text.
    """
    MIN_EXCESS_PX = 5  # styled boundary excess: precise calculation, lower than overflow:hidden threshold
    issues = []
    # Find containers with a declared styled height AND a visible fill
    containers = []
    for b in blocks:
        if b.styled_h_px > 0 and b.is_filled:
            cx, cy, cw, ch = b.bbox_px
            visual_bottom = cy + b.styled_h_px
            containers.append((b, cx, cy, cw, visual_bottom))
    for container, cx, cy, cw, visual_bottom in containers:
        c_dom = container.dom_path or ""
        for child in blocks:
            if child is container:
                continue
            # Accept: has direct text OR is a filled element (visible card/panel)
            if child.text_chars < 1 and not child.is_filled:
                continue
            # Child must be a DOM descendant of this container (within 3 levels)
            # to avoid cross-container false positives
            ch_dom = child.dom_path or ""
            if not ch_dom.startswith(c_dom + "/"):
                continue
            depth_diff = ch_dom[len(c_dom):].count("/")
            if depth_diff > 3:
                continue
            bx, by, bw, bh = child.bbox_px
            # child must be horizontally within the container (at least 50% overlap)
            h_overlap = max(0, min(bx + bw, cx + cw) - max(bx, cx))
            if h_overlap < bw * 0.5:
                continue
            # child's top must be inside the container (it started inside but spills)
            if by < cy:
                continue
            # child's bottom exceeds the styled visual boundary
            excess = (by + bh) - visual_bottom
            if excess > MIN_EXCESS_PX:
                # Write the excess into overflow_bottom_px (not clipped — this is
                # visible overflow, not hidden content). Mark as overflowing.
                if excess > child.overflow_bottom_px:
                    child.overflow_bottom_px = int(excess)
                    child.is_overflowing = True
                issues.append(child.block_id)
    return issues


def _detect_occlusions(blocks: list[ContentBlock]) -> list[tuple[str, str]]:
    """Detect z-index occlusion: higher-z element fully covering a lower-z element with content.

    Only flags cases where:
    - Front element has higher z-index
    - Front element fully contains back element's bbox
    - Back element has visible content (text or image)
    - Front element is opaque (not a transparent overlay)
    - Elements are NOT in a DOM parent-child or sibling-inline relationship
    """
    # Inline tags that participate in normal text flow — sibling occlusion
    # among these is always a layout artefact, never real visual occlusion.
    _INLINE_TAGS = {"span", "strong", "em", "b", "i", "a", "code", "small",
                    "sub", "sup", "mark", "abbr", "cite", "q", "label"}

    occlusions = []
    for i in range(len(blocks)):
        for j in range(len(blocks)):
            if i == j:
                continue
            front, back = blocks[i], blocks[j]
            # Skip DOM parent-child pairs — inline nesting (e.g. <strong> inside
            # <span>) is normal HTML structure, not visual occlusion.
            if front.dom_path and back.dom_path:
                if back.dom_path.startswith(front.dom_path + "/") or \
                   front.dom_path.startswith(back.dom_path + "/"):
                    continue
                # Skip same-parent inline siblings — normal text flow layout
                front_parent = "/".join(front.dom_path.split("/")[:-1])
                back_parent = "/".join(back.dom_path.split("/")[:-1])
                if front_parent and front_parent == back_parent:
                    if front.var_name in _INLINE_TAGS and back.var_name in _INLINE_TAGS:
                        continue
            # Front must have higher z-index, or same z-index but later DOM order
            if front.z_index < back.z_index:
                continue
            if front.z_index == back.z_index and i < j:
                continue  # same z-index: only later DOM element occludes earlier
            # Back must have content worth seeing
            if back.text_chars < 5 and back.shape_type != "picture":
                continue
            # Front must fully contain back
            if (front.x <= back.x and front.y <= back.y and
                    front.x + front.w >= back.x + back.w - 0.05 and
                    front.y + front.h >= back.y + back.h - 0.05):
                # Front must not be tiny (likely a decorator)
                if front.w * front.h > 0.5:
                    occlusions.append((front.block_id, back.block_id))
            else:
                # Partial occlusion: front covers >30% of back's area and front
                # is opaque (filled). This catches cases like a panel covering
                # half of a title — text is visibly cut even though not fully hidden.
                if not getattr(front, 'is_filled', False):
                    continue
                fx, fy, fw, fh = front.bbox_px
                bx, by, bw, bh = back.bbox_px
                if bw < 1 or bh < 1:
                    continue
                ix = max(0, min(fx + fw, bx + bw) - max(fx, bx))
                iy = max(0, min(fy + fh, by + bh) - max(fy, by))
                inter = ix * iy
                back_area = bw * bh
                if back_area > 0 and inter / back_area > 0.30:
                    occlusions.append((front.block_id, back.block_id))
    return occlusions


def _detect_alignment_issues(blocks: list[ContentBlock]) -> list[AlignmentIssue]:
    """Detect misaligned elements that should be aligned."""
    issues = []
    # Check left-edge alignment for blocks with similar x coordinates
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            a, b = blocks[i], blocks[j]
            # Left edges close but not aligned
            if 0.05 < abs(a.x - b.x) < 0.3:
                issues.append(AlignmentIssue(
                    block_a=a.block_id,
                    block_b=b.block_id,
                    edge="left",
                    deviation=round(abs(a.x - b.x), 3),
                    suggestion=f"Align left edges of {a.var_name} and {b.var_name}",
                ))
            if len(issues) >= 5:
                return issues
    return issues


def format_html_spatial_state(state: SlideState) -> str:
    """Format HTML-based spatial state as human-readable text.

    Uses the same format as format_spatial_state() for compatibility
    with the repair agent prompt.
    """
    from .spatial_state import format_spatial_state
    return format_spatial_state(state)


def format_html_compact_state(state: SlideState) -> str:
    """Compact, actionable spatial representation for HTML slides.

    Designed to be easily understood by the repair agent:
    - Shows summary first, then only elements with problems
    - Explains what each warning means and why it matters
    - Omits noise (tiny elements, bullet markers, page numbers)
    """
    lines = []

    # Header
    n_violations = (len(state.overlap_pairs) + len(state.overflow_blocks) + len(state.oob_blocks)
                    + len(state.low_contrast_blocks) + len(state.clipped_blocks)
                    + len(state.broken_images) + len(state.occlusion_pairs)
                    + len(getattr(state, 'viewport_exceedances', [])))
    lines.append(f"SLIDE {state.slide_id} — {len(state.blocks)} elements | canvas {VIEWPORT_W}×{VIEWPORT_H} px")

    warnings = []

    # Space utilization — removed (bounding-box metric was misleading;
    # the accurate per-cell coverage is shown in the SPACE MAP section)

    # === VIOLATIONS (must fix) ===
    violations = []

    # Overlap
    _CONTAINER_TAGS = frozenset({
        "svg", "g", "path", "rect", "text", "line", "circle",
        "ellipse", "polygon", "polyline", "tspan", "use", "col", "colgroup",
    })
    def _is_container(blk):
        if not blk:
            return False
        sel = (blk.css_selector or "").lower()
        var_name = (getattr(blk, "var_name", "") or "").lower()
        tag = sel.split(".")[-1].split("[")[0].split(":")[0].strip()
        return (
            tag in _CONTAINER_TAGS
            or var_name in _CONTAINER_TAGS
            or "svg" in (blk.block_id or "").lower()
        )

    for a_id, b_id, ratio in state.overlap_pairs:
        a_blk = next((b for b in state.blocks if b.block_id == a_id or b.var_name == a_id), None)
        b_blk = next((b for b in state.blocks if b.block_id == b_id or b.var_name == b_id), None)
        # Skip container/SVG element overlaps (structural, not defects)
        if _is_container(a_blk) or _is_container(b_blk):
            continue
        if a_blk and b_blk:
            # Compute intersection in px
            ax, ay, aw, ah = a_blk.bbox_px
            bx, by, bw, bh = b_blk.bbox_px
            ovl_left = max(ax, bx)
            ovl_top = max(ay, by)
            ovl_right = min(ax + aw, bx + bw)
            ovl_bottom = min(ay + ah, by + bh)
            ovl_w_px = max(0, ovl_right - ovl_left)
            ovl_h_px = max(0, ovl_bottom - ovl_top)
            violations.append(
                f"❌ OVERLAP: \"{_preview(a_blk)}\" ↔ \"{_preview(b_blk)}\"\n"
                f"   A: ({ax}, {ay}, {aw}×{ah}) px   B: ({bx}, {by}, {bw}×{bh}) px\n"
                f"   intersection: {ovl_w_px}×{ovl_h_px} px"
            )

    # Out of bounds
    for bid in state.oob_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if blk:
            bx, by, bw, bh = blk.bbox_px
            exceeds = []
            is_safety_margin = True  # starts true, set false if actually OOB
            if bx + bw > VIEWPORT_W:
                exceeds.append(f"right edge {bx+bw}px > canvas {VIEWPORT_W}px")
                is_safety_margin = False
            if by + bh > VIEWPORT_H:
                exceeds.append(f"bottom edge {by+bh}px > canvas {VIEWPORT_H}px")
                is_safety_margin = False
            if bx < 0:
                exceeds.append(f"left edge {bx}px < 0")
                is_safety_margin = False
            if by < 0:
                exceeds.append(f"top edge {by}px < 0")
                is_safety_margin = False
            if not exceeds:
                # Element within bounds but close to bottom edge.
                # If bottom edge touches canvas exactly (==720px), text is
                # likely clipped — treat as a real defect, not just a warning.
                if by + bh >= VIEWPORT_H:
                    exceeds.append(f"bottom edge {by+bh}px touches canvas boundary {VIEWPORT_H}px — text likely clipped")
                    is_safety_margin = False
                else:
                    exceeds.append(f"bottom edge {by+bh}px in safety zone (>{VIEWPORT_H-30}px) — font rendering variance may push past canvas")
            label = "❌ OUT OF BOUNDS" if not is_safety_margin else "⚠️ CANVAS EDGE (info only, not a defect)"
            target = violations if not is_safety_margin else warnings
            target.append(
                f"{label}: \"{_preview(blk)}\"\n"
                f"   bbox: ({bx}, {by}, {bw}×{bh}) px | canvas: {VIEWPORT_W}×{VIEWPORT_H} px\n"
                f"   {'; '.join(exceeds)}"
            )

    # Overflow (text content exceeds container — detected by Playwright)
    for bid in state.overflow_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if blk:
            bx, by, bw, bh = blk.bbox_px
            ovf_v = blk.overflow_bottom_px
            ovf_h = blk.overflow_right_px
            max_ovf = max(ovf_v, ovf_h)
            # Tiny overflows (≤8px) are usually sub-pixel rounding or inline
            # math glyphs — report as warning, not critical issue.
            # Exception: SVG text has no sub-pixel ambiguity; any overflow clips characters.
            if max_ovf <= 8 and not getattr(blk, 'is_svg_text', False):
                warnings.append(
                    f"⚠️ MINOR OVERFLOW: \"{_preview(blk)}\" — {max_ovf}px overflow "
                    f"(likely sub-pixel or math glyph rendering). Safe to ignore unless visually clipped."
                )
                continue
            svg_label = "SVG TEXT OVERFLOW" if getattr(blk, 'is_svg_text', False) else "TEXT OVERFLOW"
            violations.append(
                f"❌ {svg_label}: \"{_preview(blk)}\"\n"
                f"   scrollHeight: {blk.scroll_h_px}px | clientHeight: {blk.client_h_px}px | "
                f"overflow: {ovf_v}px vertical\n"
                f"   scrollWidth: {blk.scroll_w_px}px | clientWidth: {blk.client_w_px}px | "
                f"overflow: {ovf_h}px horizontal\n"
                f"   font-size: {blk.font_size_px}px | bbox: ({bx}, {by}, {bw}×{bh}) px"
            )

    # Low contrast (WCAG AA violation) — treat as a real violation so repair
    # agent stops introducing white-on-light-background regressions.
    for bid in state.low_contrast_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if blk:
            threshold = 3.0 if blk.font_size_pt >= 18 else 4.5
            violations.append(
                f"❌ LOW CONTRAST: \"{_preview(blk)}\"\n"
                f"   ratio: {blk.contrast_ratio:.1f}:1 (WCAG AA min: {threshold:.1f}:1 for {blk.font_size_px:.0f}px text)\n"
                f"   fg: {blk.fg_color} | bg: {blk.bg_color}"
            )

    # Clipped content (overflow:hidden hiding content)
    for bid in state.clipped_blocks:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if not blk or blk.clipped_bottom_px <= 5:
            continue
        # Skip container/SVG elements
        if _is_container(blk):
            continue
        # Note: do NOT skip based on scroll_h vs client_h — overflow:hidden
        # clamps scrollHeight to clientHeight, so scroll==client is expected
        # for truly clipped content. clipped_bottom_px is the reliable signal.
        clip_parent_info = ""
        if blk.clip_parent_class or blk.clip_parent_tag:
            parent_id = f".{blk.clip_parent_class}" if blk.clip_parent_class else blk.clip_parent_tag
            needed = blk.clip_parent_height_px + blk.clipped_bottom_px
            clip_parent_info = (
                f"\n   ↳ clipped by parent {parent_id} "
                f"(height:{blk.clip_parent_height_px}px → grow to {needed}px)"
            )
        violations.append(
            f"❌ CLIPPED: \"{_preview(blk)}\"\n"
            f"   {blk.clipped_bottom_px}px of content hidden by overflow:hidden\n"
            f"   scrollHeight: {blk.scroll_h_px}px | clientHeight: {blk.client_h_px}px"
            f"{clip_parent_info}"
        )

    # Broken images
    for bid in state.broken_images:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if blk:
            violations.append(
                f"❌ BROKEN IMAGE: src={blk.img_src or 'unknown'}"
            )

    # Image crop — excessive content cropped by object-fit
    for blk in state.blocks:
        if getattr(blk, 'shape_type', '') != 'picture':
            continue
        crop = getattr(blk, 'img_crop_pct', 0.0)
        if crop > ISSUE_MIN_IMG_CROP_PCT:
            bx, by, bw, bh = blk.bbox_px
            violations.append(
                f"❌ IMAGE CROP: \"{_preview(blk)}\" — {round(crop * 100)}% of content cropped\n"
                f"   visible: {round(bw)}×{round(bh)}px | src: {blk.img_src or 'unknown'}"
            )

    # Z-index occlusion
    for front_id, back_id in state.occlusion_pairs:
        front = next((b for b in state.blocks if b.block_id == front_id), None)
        back = next((b for b in state.blocks if b.block_id == back_id), None)
        # Skip container/SVG elements occluding others (structural layering)
        if _is_container(front):
            continue
        if front and back:
            violations.append(
                f"❌ OCCLUDED: \"{_preview(back)}\" hidden behind \"{_preview(front)}\"\n"
                f"   front z-index: {front.z_index} | back z-index: {back.z_index}"
            )

    # Viewport exceedances (empty containers/bars exceeding canvas bounds)
    for exc in getattr(state, 'viewport_exceedances', []):
        parts = []
        if exc.get("exRight", 0) > 0:
            parts.append(f"right edge {exc['right']}px exceeds canvas {VIEWPORT_W}px by {exc['exRight']}px")
        if exc.get("exBottom", 0) > 0:
            parts.append(f"bottom edge {exc['bottom']}px exceeds canvas {VIEWPORT_H}px by {exc['exBottom']}px")
        violations.append(
            f"❌ VIEWPORT OVERFLOW: {exc['tag']} at ({exc['x']}, {exc['y']}, {exc['w']}×{exc['h']}) px\n"
            f"   {'; '.join(parts)}"
        )

    # === WARNINGS (review before submit) ===

    # Small font warning — text below readable minimum
    small_font_blocks = [
        b for b in state.blocks
        if b.font_size_px > 0
        and b.font_size_px < 14
        and b.text_chars > 10
        and b.shape_type not in ('picture', 'chart')
    ]
    if small_font_blocks:
        details = "  ".join(
            f"{b.css_selector or b.var_name}: font {b.font_size_px:.0f}px"
            for b in small_font_blocks[:6]
        )
        warnings.append(
            f"⚠ SMALL FONT: {len(small_font_blocks)} element(s) below 14px "
            f"body minimum:\n   {details}"
        )

    # Note: overflow is now detected by Playwright (isOverflowing) and
    # reported above as violations. No estimated utilization warnings needed.

    # Tight adjacency (potential visual collision)
    sorted_blocks = sorted(state.blocks, key=lambda b: (b.y, b.x))
    for i in range(len(sorted_blocks) - 1):
        a = sorted_blocks[i]
        if a.text_chars < 10:
            continue  # skip bullet markers
        for j in range(i + 1, min(i + 3, len(sorted_blocks))):
            b = sorted_blocks[j]
            if b.text_chars < 10:
                continue
            # Skip parent-child (one fully contains the other)
            a_cont_b = (a.x <= b.x and a.y <= b.y and
                        a.x + a.w >= b.x + b.w - 0.05 and
                        a.y + a.h >= b.y + b.h - 0.05)
            b_cont_a = (b.x <= a.x and b.y <= a.y and
                        b.x + b.w >= a.x + a.w - 0.05 and
                        b.y + b.h >= a.y + a.h - 0.05)
            if a_cont_b or b_cont_a:
                continue
            a_right = a.x + a.w
            b_right = b.x + b.w
            horiz_overlap = min(a_right, b_right) - max(a.x, b.x)
            if horiz_overlap >= 0.5:  # same column
                gap = b.y - (a.y + a.h)
                if gap < -0.05:
                    ax, ay, aw, ah_px = a.bbox_px
                    bx_px, by_px, bw_px, bh_px = b.bbox_px
                    gap_px = by_px - (ay + ah_px)
                    if abs(gap) >= 0.15:
                        # Significant visual overlap → hard issue
                        violations.append(
                            f"❌ OVERLAP: \"{_preview(a)}\" ↔ \"{_preview(b)}\"\n"
                            f"   A: ({ax}, {ay}, {aw}×{ah_px}) px   B: ({bx_px}, {by_px}, {bw_px}×{bh_px}) px\n"
                            f"   vertical overlap: {abs(gap_px)}px"
                        )
                    else:
                        warnings.append(
                            f"⚠️ TIGHT: \"{_preview(a)}\" ↔ \"{_preview(b)}\" — {abs(gap_px)}px overlap"
                        )
                break

    # Output violations (from both _detect_overlaps and tight adjacency)
    if violations:
        lines.append(f"\n🚨 ISSUES TO FIX ({len(violations)}):")
        lines.extend(violations)

    if warnings:
        lines.append(f"\n⚠️ WARNINGS ({len(warnings)}):")
        lines.extend(warnings)

    # === CLEAN STATE ===
    if not violations and not warnings:
        lines.append("\nNo overlap, overflow, or out-of-bounds defects.")
        lines.append("NOTE: This check covers hard spatial defects only. "
                     "Density balance, content distribution, and visual weight "
                     "are NOT evaluated — use the space map below to judge those.")

    # === LAYOUT ANCHOR (always shown) ===
    # Budgeted element map so the agent knows WHERE objects are.
    # Shows significant elements with bbox, text preview, and font size.
    # This enables spatial planning without blind guessing.
    sig_blocks = [b for b in state.blocks if b.w > 0.4 and b.h > 0.15 and (b.text_chars > 5 or b.shape_type in ("picture", "chart", "table"))]
    if sig_blocks:
        # Sort top→bottom, left→right
        sig_blocks.sort(key=lambda b: (round(b.y, 1), b.x))
        lines.append(f"\n📐 LAYOUT ANCHOR ({len(sig_blocks)} elements):")
        total_words = 0
        bullet_count = 0
        for blk in sig_blocks:
            bx, by, bw, bh = blk.bbox_px
            sel = f" {blk.css_selector}" if blk.css_selector else ""
            text = " ".join(blk.text_lines) if blk.text_lines else ""
            preview = text[:50] + ("…" if len(text) > 50 else "")
            font_info = f" font:{blk.font_size_px:.0f}px" if blk.font_size_px > 0 else ""
            lines.append(
                f"  {blk.var_name}{sel}: ({bx},{by}) {bw}×{bh}px{font_info}"
                f"  \"{preview}\""
            )
            # Word/bullet count
            words = len(text.split()) if text else 0
            total_words += words
            if blk.var_name in ("li", "ul", "ol") or (blk.css_selector and "li" in blk.css_selector):
                bullet_count += 1
            elif text.startswith("•") or text.startswith("–") or text.startswith("-"):
                bullet_count += 1
        # Summary stats
        lines.append(f"  ── total body words: ~{total_words} | bullet-like elements: {bullet_count}")
        if bullet_count > 8:
            lines.append(f"  ⚠️ BULLET LIMIT EXCEEDED: {bullet_count} > 8 — consider removing {bullet_count - 8} bullet(s) to improve readability.")

        # Font size warnings — body text below 14px, headings below 22px
        _small_font_elements = []
        _FOOTNOTE_TAGS = {"small", "sup", "sub", "abbr"}
        _FOOTNOTE_CLASSES = {"small", "footnote", "caption", "note", "footer", "source", "credit", "ref"}
        for blk in state.blocks:
            if blk.font_size_px <= 0 or blk.text_chars < 10:
                continue
            if blk.shape_type in ("picture", "chart"):
                continue
            # Skip footnote-like elements
            tag = blk.var_name.lower() if blk.var_name else ""
            css_cls = blk.css_selector.lower() if blk.css_selector else ""
            if tag in _FOOTNOTE_TAGS:
                continue
            if any(fc in css_cls for fc in _FOOTNOTE_CLASSES):
                continue
            is_heading = tag in ("h1", "h2", "h3") or "title" in css_cls
            min_px = 22 if is_heading else 14
            if blk.font_size_px < min_px:
                label = f"heading min {min_px}px" if is_heading else f"body min {min_px}px"
                preview = blk.text_lines[0][:40] if blk.text_lines else tag
                _small_font_elements.append(
                    f"    {tag} {blk.css_selector}: font {blk.font_size_px:.0f}px ({label})  \"{preview}\""
                )
        if _small_font_elements:
            lines.append(f"  ⚠ SMALL FONT: {len(_small_font_elements)} element(s) below minimum:")
            lines.extend(_small_font_elements[:8])

        # Content mass warnings (extreme cases only)
        if total_words < 20 and total_words > 0:
            lines.append(
                f"  🚨 SPARSE CONTENT: only ~{total_words} words on this slide. "
                f"Unless this is a title/divider slide, content may have been "
                f"over-deleted. Check that key information was preserved."
            )
        elif total_words > 250:
            lines.append(
                f"  ⚠ DENSE CONTENT: ~{total_words} words. Consider condensing "
                f"— slides with >250 words risk being flagged as text_wall."
            )

    # === ASCII SPACE MAP (single source of truth for coverage) ===
    lines.append(_render_space_map(state.blocks))

    return "\n".join(lines)


# ── Single source of truth: "what counts as a significant spatial issue" ──
#
# Canonical thresholds for filtering noise / false positives. These were
# historically duplicated in scripts/redeck_repair.py (count_issues) and again,
# inconsistently, inside agent_repair.py's submit gate and stagnation trigger —
# which is precisely why the agent could believe a slide was "clean" while the
# external scorer still reported clipped-text issues. count_significant_issues
# is now the ONE place the rule lives; scripts/redeck_repair.count_issues, the
# submit gate, the stagnation trigger, and best-state tracking all call it.
#
# Placed here (a leaf module imported by both scripts/redeck_repair.py and
# agent_repair.py) so there is no import cycle.
ISSUE_MIN_OVERLAP_AREA_FRAC = 0.05   # ignore overlaps < 5% of smaller element
ISSUE_MIN_OOB_EXCESS_PX = 5          # ignore OOB ≤ 5px past canvas edge
ISSUE_MIN_CLIP_PX = 8                # ignore clips < 8px (sub-pixel / minor font overflow)
ISSUE_MIN_OVERFLOW_PX = 8            # ignore overflows ≤ 8px
ISSUE_MIN_IMG_CROP_PCT = 0.25        # ignore image crops ≤ 25% (normal cover aspect-ratio adaptation)

# Container/structural tags whose overlaps/overflows are layering artifacts, not
# defects. NOTE: this set matches scripts/redeck_repair._is_container_element
# EXACTLY (it intentionally omits "text"/"tspan", unlike the compact-formatter's
# local _is_container) so the count stays byte-identical to the legacy scorer.
_ISSUE_CONTAINER_TAGS = frozenset({
    "svg", "g", "col", "colgroup", "path", "rect",
    "ellipse", "polygon", "polyline", "line", "circle", "use",
})


def _issue_is_container(block) -> bool:
    """Structural/container element with no visual content of its own.

    Only skips SVG elements that are genuinely small chart-internal decorations
    (area < 10000 sq.px ≈ ~100×100px). Large SVG-drawn panels/cards are NOT
    treated as containers — their overlaps with text are real defects.

    Non-SVG structural tags (col, colgroup) are always skipped.
    """
    if not block:
        return False
    sel = (block.css_selector or "").lower()
    bid = (block.block_id or "").lower()
    var_name = (getattr(block, "var_name", "") or "").lower()
    tag = sel.split(".")[-1].split("[")[0].split(":")[0].strip()

    # Non-SVG structural tags: always skip
    _NON_SVG_CONTAINER_TAGS = frozenset({"col", "colgroup"})
    if tag in _NON_SVG_CONTAINER_TAGS or var_name in _NON_SVG_CONTAINER_TAGS:
        return True

    # SVG tags: only skip if the element is small (chart-internal decoration)
    _SVG_TAGS = frozenset({"svg", "g", "path", "rect", "circle", "ellipse",
                           "polygon", "polyline", "line", "use"})
    if tag in _SVG_TAGS or var_name in _SVG_TAGS or "svg" in bid:
        # Small SVG element = chart bar, axis tick, icon path → skip
        # Large SVG element = card panel, background shape → don't skip
        bx, by, bw, bh = block.bbox_px if hasattr(block, 'bbox_px') else (0, 0, 0, 0)
        area_px = bw * bh
        if area_px < 10000:  # ~100x100px or smaller
            return True
        return False

    return False


def count_significant_issues(state, canvas_w: int = 1280, canvas_h: int = 720) -> dict:
    """Single source of truth for hard spatial defects, with noise filtered.

    Returns a dict mapping category name -> list of identifiers (block ids or
    (a,b) tuples). The total issue count is sum(len(v) for v in result.values()).
    A faithful port of scripts/redeck_repair.count_issues (all six categories) so
    that every consumer — the external scorer, the agent submit gate, the
    stagnation trigger, and best-state tracking — agrees on what "clean" means.

    Categories: overlap, text_overflow, out_of_bounds, clipped, occlusion,
    canvas_truncation.
    """
    import re as _re
    blocks = state.blocks
    by_id = {}
    for b in blocks:
        by_id.setdefault(b.block_id, b)

    def _get(bid):
        return next((b for b in blocks if b.block_id == bid), None)

    out = {
        "overlap": [],
        "text_overflow": [],
        "out_of_bounds": [],
        "clipped": [],
        "occlusion": [],
        "canvas_truncation": [],
        "image_crop": [],
    }

    # 1) Overlaps — skip container sides and tiny (<5% of smaller) overlaps.
    #    EXCEPTION: a paint-over shape (a chart bar / accent box that escaped its
    #    card and is pixel-confirmed via elementFromPoint to paint over another
    # 1) Overlaps — the pure-geometry overlap detector already handles
    #    containment-vs-partial-overlap; here we just filter containers and
    #    apply the minimum overlap-area fraction. Skip shape-vs-shape overlaps
    #    ONLY when they are sub-threshold (the pure-geometry detector already
    #    filtered out full containment; any shape-vs-shape pair here is a real
    #    partial overlap between two distinct visible cards/panels).
    for a_id, b_id, area in state.overlap_pairs:
        a_blk = _get(a_id)
        b_blk = _get(b_id)
        if _issue_is_container(a_blk) or _issue_is_container(b_blk):
            continue
        if area < ISSUE_MIN_OVERLAP_AREA_FRAC:
            # Skip decorative-vs-decorative overlaps: two elements with no text
            # overlapping each other is not a visual defect (orbs, shapes, SVG decorations)
            a_text = (a_blk.text_chars or 0) if a_blk else 0
            b_text = (b_blk.text_chars or 0) if b_blk else 0
            if a_text == 0 and b_text == 0:
                # Exception: two large filled panels colliding IS a defect
                # (e.g. two card backgrounds overlapping). Check absolute overlap ≥8x8px.
                if a_blk and b_blk:
                    ax,ay,aw,ah = a_blk.bbox_px; bx,by,bw,bh = b_blk.bbox_px
                    ox = max(0, min(ax+aw,bx+bw)-max(ax,bx))
                    oy = max(0, min(ay+ah,by+bh)-max(ay,by))
                    # Only flag if both are filled (visible panels) AND overlap is large
                    if (getattr(a_blk, 'is_filled', False) and getattr(b_blk, 'is_filled', False)
                            and ox >= 8 and oy >= 8):
                        out["overlap"].append((a_id, b_id))
                continue
            # Text-involving overlap below 5% ratio — already handled by
            # _detect_overlaps absolute-size check, skip here
            continue
        out["overlap"].append((a_id, b_id))

    # 2) Text overflow — skip ≤8px, non-text decorative, and containers
    #    Exception: SVG text has no sub-pixel ambiguity, threshold = 0
    #    Exception: filled elements (visible cards/panels) are visual overflow
    #    even without direct text
    for bid in state.overflow_blocks:
        blk = _get(bid)
        if not blk:
            continue
        svg_text = getattr(blk, 'is_svg_text', False)
        # Use lower threshold (5px) for styled-boundary overflow (precise calc)
        # vs standard 8px for scrollHeight-based overflow
        is_styled_ovf = not blk.is_clipped and blk.overflow_bottom_px > 0
        threshold = 5 if is_styled_ovf else ISSUE_MIN_OVERFLOW_PX
        if not svg_text and (blk.overflow_bottom_px <= threshold
                and blk.overflow_right_px <= threshold):
            continue
        if not blk.text_lines and not (isinstance(blk.text_chars, str) and blk.text_chars.strip()):
            if isinstance(blk.text_chars, int) and blk.text_chars == 0:
                # Exception: filled elements (visible cards) overflowing are still defects
                if not getattr(blk, 'is_filled', False):
                    continue
        if _issue_is_container(blk):
            continue
        out["text_overflow"].append(bid)

    # 3) Out of bounds — skip ≤5px past either canvas edge
    for bid in state.oob_blocks:
        blk = _get(bid)
        if blk:
            bx, by, bw, bh = blk.bbox_px
            right_excess = max(0, bx + bw - canvas_w)
            bottom_excess = max(0, by + bh - canvas_h)
            if right_excess <= ISSUE_MIN_OOB_EXCESS_PX and bottom_excess <= ISSUE_MIN_OOB_EXCESS_PX:
                continue
        out["out_of_bounds"].append(bid)

    # 4) Clipped by parent overflow:hidden — skip <8px, containers,
    #    chart-internal minor clips, and decorative-punctuation-only minor clips
    for bid in state.clipped_blocks:
        blk = _get(bid)
        if not blk:
            continue
        if blk.clipped_bottom_px < ISSUE_MIN_CLIP_PX:
            continue
        if _issue_is_container(blk):
            continue
        if (getattr(blk, 'shape_type', None) == 'chart'
                and blk.clipped_bottom_px <= 15
                and (blk.text_chars or 0) <= 20):
            continue
        _text_joined = " ".join((blk.text_lines or []))
        if ((blk.text_chars or 0) <= 5
                and blk.clipped_bottom_px <= 10
                and blk.text_lines
                and not _re.search(r'[a-zA-Z0-9]', _text_joined)):
            continue
        out["clipped"].append(bid)

    # 5) Occlusion — skip container fronts
    for front, back in state.occlusion_pairs:
        front_blk = _get(front)
        if _issue_is_container(front_blk):
            continue
        out["occlusion"].append((front, back))

    # 6) Canvas-edge content truncation — elements at the canvas bottom whose
    #    content (scrollHeight or font descenders) extends off-canvas. Avoid
    #    double-counting elements already flagged as clipped.
    seen_clipped = set(state.clipped_blocks)
    for blk in blocks:
        if blk.block_id in seen_clipped:
            continue
        if _issue_is_container(blk):
            continue
        bx, by, bw, bh = blk.bbox_px
        bottom_px = by + bh
        if bottom_px < canvas_h - 2:
            continue
        visible_h = max(1, canvas_h - by)
        scroll_h = blk.scroll_h_px or 0
        excess = scroll_h - visible_h
        font_px = blk.font_size_px or 0
        font_excess = font_px * 1.2 - visible_h
        effective_excess = max(excess, font_excess)
        if effective_excess >= ISSUE_MIN_CLIP_PX and blk.text_lines:
            out["canvas_truncation"].append(blk.block_id)

    # 7) Image crop — img elements with excessive content cropped by
    #    object-fit (cover/none) or container overflow:hidden.
    for blk in blocks:
        if getattr(blk, 'shape_type', '') != 'picture':
            continue
        crop = getattr(blk, 'img_crop_pct', 0.0)
        if crop > ISSUE_MIN_IMG_CROP_PCT:
            out["image_crop"].append(blk.block_id)

    return out


def count_significant_issue_total(state, canvas_w: int = 1280, canvas_h: int = 720) -> int:
    """Convenience: total significant-issue count (the scalar count_issues returns)."""
    return sum(len(v) for v in count_significant_issues(state, canvas_w, canvas_h).values())


# ── Deterministic content/structure checks ─────────────────────────
# Migrated from geom_checks.py to operate directly on SlideState.blocks
# (Playwright DOM), avoiding the lossy SlideExtraction conversion.

def run_deterministic_checks(
    state: SlideState,
    slide_id: int,
    source_text: str = "",
    all_states: list["SlideState"] | None = None,
) -> list:
    """Run deterministic (non-LLM) content and structure checks on a slide.

    Returns a list of Issue dicts (not Issue objects — caller constructs).
    Checks: empty_slide, empty_placeholder, meta_content, spelling,
    non_slide_content, bullet_count. Entity coverage requires all_states.
    Overlap/OOB/clipped are NOT checked here — they are already in
    count_significant_issues() with better precision.
    """
    import re as _re
    from ...schemas.issue import Issue, IssueEvidence, FixDetail
    from ...schemas.common import Severity, Confidence, IssueStatus, Verdict

    issues: list[Issue] = []
    blocks = state.blocks

    # ── All text for this slide ──
    all_text = " ".join(
        " ".join(b.text_lines) for b in blocks if b.text_lines
    )
    total_chars = sum(b.text_chars for b in blocks if isinstance(b.text_chars, int))

    # 1. Empty slide
    if len(blocks) == 0 or total_chars == 0:
        issues.append(Issue(
            issue_id=f"B_geom_slide{slide_id}_empty",
            rubric_id="B2",
            issue_type="empty_slide",
            severity=Severity.MAJOR,
            confidence=Confidence.HIGH,
            affected_slides=[slide_id],
            evidence=IssueEvidence(
                description=f"Slide {slide_id} has {len(blocks)} elements "
                           f"and {total_chars} chars of text",
            ),
            why_this_fails="Empty or near-empty slide provides no content value",
            fixability="medium",
            planned_fix=f"Regenerate slide {slide_id} with substantial content.",
        ))
        return issues  # No point checking further

    # 2. Empty placeholders — large filled blocks with no text/image
    MIN_W_PX = 1.5 * 96  # ~144px
    MIN_H_PX = 0.5 * 96  # ~48px
    for blk in blocks:
        bx, by, bw, bh = blk.bbox_px
        if bw < MIN_W_PX or bh < MIN_H_PX:
            continue
        # Has content → skip
        if blk.text_lines and any(t.strip() for t in blk.text_lines):
            continue
        if blk.shape_type in ("picture", "image", "chart", "table"):
            continue
        # Full-width thin bands (decorative) → skip
        if bw >= 1200 and bh < 120:
            continue
        # Full-slide wrapper → skip
        if bw >= 1200 and bh >= 680:
            continue
        # Container with child content → skip
        has_child = False
        for other in blocks:
            if other is blk:
                continue
            if not (other.text_lines or other.shape_type in ("picture", "image")):
                continue
            ox, oy, ow, oh = other.bbox_px
            if (ox >= bx - 5 and oy >= by - 5 and
                ox + ow <= bx + bw + 5 and oy + oh <= by + bh + 5):
                has_child = True
                break
        if has_child:
            continue
        # Adjacent picture → skip
        has_pic = False
        for other in blocks:
            if other.shape_type not in ("picture", "image"):
                continue
            ox, oy, ow, oh = other.bbox_px
            ix = max(0, min(bx + bw, ox + ow) - max(bx, ox))
            iy = max(0, min(by + bh, oy + oh) - max(by, oy))
            if ix > 0 and iy > 0 and ow * oh > 0 and (ix * iy) / (ow * oh) > 0.3:
                has_pic = True
                break
        if has_pic:
            continue

        issues.append(Issue(
            issue_id=f"B_geom_slide{slide_id}_empty_placeholder_{blk.block_id}",
            rubric_id="B2",
            issue_type="empty_placeholder",
            severity=Severity.MAJOR,
            confidence=Confidence.HIGH,
            affected_slides=[slide_id],
            evidence=IssueEvidence(
                description=f"Slide {slide_id}: element '{blk.var_name or blk.block_id}' "
                           f"({bw:.0f}×{bh:.0f}px) has no text or image. "
                           f"It renders as a large empty box.",
            ),
            why_this_fails="Large empty shapes waste slide space",
            fixability="easy",
            planned_fix=f"Delete the empty shape '{blk.var_name or blk.block_id}'.",
        ))

    # 3. Meta-content (editorial instructions left in slide)
    _META_PATTERNS = [
        "[RECURRING]", "[TODO]", "[FIX]", "[NOTE]", "[EDIT]",
        "Note to editor", "Restore or add",
        "[PLACEHOLDER]", "[INSERT", "[REPLACE",
        "Revise the setup", "Revise the ",
        "Add a slide that", "Add opening slides",
    ]
    for blk in blocks:
        if not blk.text_lines:
            continue
        text = " ".join(blk.text_lines)
        for pattern in _META_PATTERNS:
            if pattern.lower() in text.lower():
                issues.append(Issue(
                    issue_id=f"A7_slide{slide_id}_meta_{blk.block_id}",
                    rubric_id="A7",
                    issue_type="content_anomaly",
                    severity=Severity.CRITICAL,
                    confidence=Confidence.HIGH,
                    affected_slides=[slide_id],
                    evidence=IssueEvidence(
                        description=f"Text contains meta-instruction: '{pattern}'. "
                                   f"Only presentation-ready content should appear.",
                    ),
                ))
                break

    # 4. Spelling errors
    _KNOWN_TYPOS = {
        "acheive": "achieve", "acheived": "achieved",
        "accomodate": "accommodate", "algorythm": "algorithm",
        "architechture": "architecture", "artifical": "artificial",
        "benchamrk": "benchmark", "catagory": "category",
        "comparision": "comparison", "consistant": "consistent",
        "dependant": "dependent", "efficency": "efficiency",
        "enviroment": "environment", "evalution": "evaluation",
        "heirarchy": "hierarchy", "implemention": "implementation",
        "independant": "independent", "langauge": "language",
        "neccessary": "necessary", "occured": "occurred",
        "paramater": "parameter", "performace": "performance",
        "preformance": "performance", "reccomend": "recommend",
        "relavent": "relevant", "seperate": "separate",
        "signficant": "significant", "similiar": "similar",
        "threshhold": "threshold", "trasformer": "transformer",
    }
    words = _re.findall(r'\b[a-zA-Z]{4,}\b', all_text.lower())
    found_typos = [(w, _KNOWN_TYPOS[w]) for w in words if w in _KNOWN_TYPOS]
    if found_typos:
        seen = set()
        unique = []
        for t, c in found_typos:
            if t not in seen:
                seen.add(t)
                unique.append((t, c))
        typo_list = ", ".join(f'"{t}" → "{c}"' for t, c in unique[:5])
        issues.append(Issue(
            issue_id=f"A_spell_slide{slide_id}_{unique[0][0]}",
            rubric_id="A",
            issue_type="spelling_error",
            severity=Severity.MINOR,
            confidence=Confidence.HIGH,
            affected_slides=[slide_id],
            evidence=IssueEvidence(
                description=f"Slide {slide_id}: spelling error(s): {typo_list}.",
            ),
        ))

    # 5. Non-slide content (speaker notes, placeholders, lorem ipsum)
    _NON_SLIDE_RE = _re.compile(
        r'click to (?:edit|add)|speaker notes?:|note to (?:editor|self)|'
        r'insert (?:image|chart|diagram) here|lorem ipsum',
        _re.IGNORECASE,
    )
    for blk in blocks:
        if not blk.text_lines:
            continue
        text = " ".join(blk.text_lines)
        m = _NON_SLIDE_RE.search(text)
        if m:
            issues.append(Issue(
                issue_id=f"A_meta_slide{slide_id}_{m.group()[:20]}",
                rubric_id="A",
                issue_type="non_slide_content",
                severity=Severity.MAJOR,
                confidence=Confidence.HIGH,
                affected_slides=[slide_id],
                evidence=IssueEvidence(
                    description=f"Slide {slide_id}: contains non-slide content: "
                               f'"{m.group()}". Remove or replace.',
                ),
            ))
            break

    # 6. Bullet count
    bullet_count = 0
    for blk in blocks:
        if not blk.text_lines:
            continue
        tag = (blk.var_name or "").lower()
        if tag in ("li", "listitem"):
            bullet_count += 1
        else:
            text = " ".join(blk.text_lines).strip()
            if text and text[0] in "•–-▸●":
                bullet_count += 1
            elif _re.match(r'^\d+[\.\)]\s', text):
                bullet_count += 1
    if bullet_count > 8:
        issues.append(Issue(
            issue_id=f"A_bullets_slide{slide_id}",
            rubric_id="A",
            issue_type="too_many_bullets",
            severity=Severity.MINOR,
            confidence=Confidence.HIGH,
            affected_slides=[slide_id],
            evidence=IssueEvidence(
                description=f"Slide has {bullet_count} bullet points (max 8). "
                           f"Remove {bullet_count - 8} by merging or deleting.",
            ),
        ))

    # 7. Entity coverage (requires all_states for cross-slide check)
    if source_text and all_states:
        all_slide_text = ""
        for s in all_states:
            for b in s.blocks:
                if b.text_lines:
                    all_slide_text += " ".join(b.text_lines).lower() + " "

        # Proper nouns (multi-word capitalized)
        proper_nouns = set(_re.findall(
            r'[A-Z][a-z]+(?:[-\s][A-Z][a-z]+)+', source_text
        ))
        # Hyphenated technical terms
        hyphenated = set(_re.findall(r'\b[a-z]+-[a-z]+(?:-[a-z]+)*\b', source_text.lower()))

        source_lower = source_text.lower()
        missing = []
        for term in proper_nouns:
            count = source_lower.count(term.lower())
            if count >= 2 and term.lower() not in all_slide_text:
                missing.append((term, count))
        for term in hyphenated:
            if len(term) > 8:
                count = source_lower.count(term)
                if count >= 3 and term not in all_slide_text:
                    missing.append((term, count))

        if missing:
            missing.sort(key=lambda x: -x[1])
            for entity, count in missing[:5]:
                # Find best slide for this entity
                target_sid = slide_id
                entity_words = set(entity.lower().split())
                best_overlap = 0
                for s in all_states:
                    s_text = " ".join(
                        " ".join(b.text_lines) for b in s.blocks if b.text_lines
                    ).lower()
                    overlap = sum(1 for w in entity_words if w in s_text)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        # Need slide_id from state — use blocks' first id
                        target_sid = getattr(s, 'slide_id', slide_id)

                issues.append(Issue(
                    issue_id=f"C4_ent_{entity[:12].replace(' ','_').replace('-','_')}",
                    rubric_id="C4",
                    issue_type="missing_entity",
                    severity=Severity.MAJOR,
                    confidence=Confidence.HIGH,
                    affected_slides=[target_sid],
                    evidence=IssueEvidence(
                        description=f"Source mentions '{entity}' {count} times "
                                   f"but it does not appear on any slide.",
                    ),
                    planned_fix=f"Insert '{entity}' on slide {target_sid}",
                    fix_detail=FixDetail(correct_content=entity),
                ))

    # 8. Element undersized — detect elements with large unused space below/beside them
    _CTAGS = {"tr", "thead", "tbody", "table", "tfoot"}
    _content_blocks = [
        b for b in blocks
        if b.bbox_px[2] > 20 and b.bbox_px[3] > 10  # min size in px
        and not (b.bbox_px[2] / 1280 > 0.95 and b.bbox_px[3] / 720 > 0.90)  # exclude full-canvas wrappers
        and not (b.var_name in _CTAGS and b.bbox_px[2] / 1280 > 0.80)  # exclude wide table row containers
    ]
    if _content_blocks:
        cols, rows = 24, 14
        cw, ch = 1280 / cols, 720 / rows
        grid = [[False] * cols for _ in range(rows)]
        for blk in _content_blocks:
            bx, by, bw, bh = blk.bbox_px
            for r in range(rows):
                ry = r * ch
                if by + bh <= ry or by >= ry + ch: continue
                for c in range(cols):
                    cx = c * cw
                    if bx + bw <= cx or bx >= cx + cw: continue
                    grid[r][c] = True
        mid_r, mid_c = rows // 2, cols // 2
        qf = {}
        for qn, rr, cr in [
            ("TL", range(0, mid_r), range(0, mid_c)),
            ("TR", range(0, mid_r), range(mid_c, cols)),
            ("BL", range(mid_r, rows), range(0, mid_c)),
            ("BR", range(mid_r, rows), range(mid_c, cols)),
        ]:
            cells = sum(1 for r in rr for c in cr if grid[r][c])
            total_q = len(list(rr)) * len(list(cr))
            qf[qn] = cells / max(1, total_q)
        max_q = max(qf.values())
        min_q = min(qf.values())
        if max_q >= 0.55 and min_q < 0.40:
            sparse_quads = [qn for qn, v in qf.items() if v < 0.40]
            dense_quads = [qn for qn, v in qf.items() if v >= 0.55]
            issues.append(Issue(
                issue_id=f"B9_slide{slide_id}_undersized",
                rubric_id="B9",
                issue_type="density_imbalance",
                sub_type="element_undersized",
                severity=Severity.MAJOR,
                confidence=Confidence.HIGH,
                affected_slides=[slide_id],
                evidence=IssueEvidence(
                    description=(
                        f"Slide {slide_id}: quadrant fill imbalance — "
                        f"{', '.join(sparse_quads)} at "
                        f"{', '.join(f'{round(qf[q]*100)}%' for q in sparse_quads)} "
                        f"while {', '.join(dense_quads)} at "
                        f"{', '.join(f'{round(qf[q]*100)}%' for q in dense_quads)}. "
                        f"Elements in the sparse region should be stretched."
                    ),
                ),
                planned_fix=(
                    f"Increase width/height of elements in the "
                    f"{', '.join(sparse_quads)} region via CSS."
                ),
            ))

    # 9. Column height mismatch — detect side-by-side panels with mismatched bottom edges
    left_cols = [b for b in blocks if b.bbox_px[0] < 200 and 300 < b.bbox_px[2] < 900 and b.bbox_px[3] > 150]
    right_cols = [b for b in blocks if b.bbox_px[0] > 500 and 200 < b.bbox_px[2] < 700 and b.bbox_px[3] > 150]
    if left_cols and right_cols:
        left_bottom = max(b.bbox_px[1] + b.bbox_px[3] for b in left_cols)
        right_bottom = max(b.bbox_px[1] + b.bbox_px[3] for b in right_cols)
        diff = abs(left_bottom - right_bottom)
        if diff > 80:
            shorter = "right" if right_bottom < left_bottom else "left"
            issues.append(Issue(
                issue_id=f"B9_slide{slide_id}_col_mismatch",
                rubric_id="B9",
                issue_type="density_imbalance",
                sub_type="column_height_mismatch",
                severity=Severity.MINOR if diff < 150 else Severity.MAJOR,
                confidence=Confidence.HIGH,
                affected_slides=[slide_id],
                evidence=IssueEvidence(
                    description=(
                        f"Slide {slide_id}: left column ends at y={left_bottom:.0f}px, "
                        f"right column ends at y={right_bottom:.0f}px "
                        f"(diff={diff:.0f}px). The {shorter} column looks unfinished."
                    ),
                ),
                planned_fix=(
                    f"Stretch elements in the {shorter} column to align "
                    f"bottom edges within ~30px."
                ),
            ))

    return issues


def _render_space_map(
    blocks: list,
    canvas_w: int = VIEWPORT_W,
    canvas_h: int = VIEWPORT_H,
    cols: int = 24,
    rows: int = 14,
) -> str:
    """Render an ASCII grid showing spatial occupancy.

    Uses +/-/| grid format and #/. text symbols — research shows these
    yield highest LLM spatial reasoning accuracy (Text2Space, Huang 2026;
    Levental 2026).
    """
    cell_w = canvas_w / cols
    cell_h = canvas_h / rows

    # Build occupancy grid — filter out containers that inflate coverage.
    # Two rules: (1) full-canvas wrappers, (2) wide row-like containers
    # (tr, thead, tbody, table) whose children are the real content.
    _CONTAINER_TAGS = {"tr", "thead", "tbody", "table", "tfoot"}
    grid = [[False] * cols for _ in range(rows)]
    sig_blocks = [
        b for b in blocks
        if b.bbox_px[2] > 20 and b.bbox_px[3] > 10  # min size in px
        # Exclude full-canvas containers (both dimensions > 95% of canvas)
        and not (b.bbox_px[2] / canvas_w > 0.95 and b.bbox_px[3] / canvas_h > 0.90)
        # Exclude wide row containers (table rows, etc.) — their children
        # (td/th) are the real content and have narrower bboxes
        and not (b.var_name in _CONTAINER_TAGS and b.bbox_px[2] / canvas_w > 0.80)
    ]
    for blk in sig_blocks:
        bx, by, bw, bh = blk.bbox_px
        for r in range(rows):
            ry = r * cell_h
            if by + bh <= ry or by >= ry + cell_h:
                continue
            for c in range(cols):
                cx = c * cell_w
                if bx + bw <= cx or bx >= cx + cell_w:
                    continue
                grid[r][c] = True

    # Count coverage
    filled = sum(sum(row) for row in grid)
    total = rows * cols
    pct = round(100 * filled / total) if total else 0

    # Render with +/-/| grid format and #/. symbols
    lines = [f"\nSPACE MAP (each cell ~{int(cell_w)}x{int(cell_h)} px, # = content, . = empty):"]

    # Find empty rows for annotation
    empty_row_indices = set()
    for r in range(rows):
        if not any(grid[r]):
            empty_row_indices.add(r)

    # Find largest contiguous empty band
    max_empty_start = max_empty_len = 0
    cur_start = cur_len = 0
    for r in range(rows):
        if r in empty_row_indices:
            if cur_len == 0:
                cur_start = r
            cur_len += 1
        else:
            if cur_len > max_empty_len:
                max_empty_start = cur_start
                max_empty_len = cur_len
            cur_len = 0
    if cur_len > max_empty_len:
        max_empty_start = cur_start
        max_empty_len = cur_len

    top_border = "+" + "-" * cols + "+"
    bot_border = "+" + "-" * cols + "+"
    lines.append(top_border)
    for r in range(rows):
        row_str = ""
        for c in range(cols):
            row_str += "#" if grid[r][c] else "."
        annotation = ""
        if r in empty_row_indices:
            annotation = "  <- empty"
        lines.append(f"|{row_str}|{annotation}")
    lines.append(bot_border)

    # Summary
    summary = f"Coverage: {pct}%"
    if max_empty_len >= 2:
        band_pct = round(100 * max_empty_len / rows)
        if max_empty_start + max_empty_len >= rows:
            where = f"Bottom {band_pct}%"
        elif max_empty_start == 0:
            where = f"Top {band_pct}%"
        else:
            where = f"Middle y={int(max_empty_start * cell_h)}-{int((max_empty_start + max_empty_len) * cell_h)}px"
        summary += f" | {where} of slide has no content."

    if pct < 65:
        summary += f"\nContent occupies only {pct}% of canvas. Consider expanding elements to use available space."

    # Empty band warning: only when content exists ABOVE and BELOW the band
    # (genuine gap, not just bottom margin)
    if max_empty_len >= 3:
        has_content_above = any(any(grid[r]) for r in range(max_empty_start))
        has_content_below = any(
            any(grid[r]) for r in range(max_empty_start + max_empty_len, rows)
        )
        if has_content_above and has_content_below:
            y_start = int(max_empty_start * cell_h)
            y_end = int((max_empty_start + max_empty_len) * cell_h)
            summary += (
                f"\n⚠ EMPTY BAND: rows {max_empty_start}-"
                f"{max_empty_start + max_empty_len - 1} "
                f"(y={y_start}-{y_end}px) are entirely unused between "
                f"content areas. Consider redistributing elements vertically."
            )

    # Quadrant fill ratios — always shown so the agent can judge balance.
    mid_r, mid_c = rows // 2, cols // 2
    quad_fills = {}
    for qname, r_range, c_range in [
        ("TL", range(0, mid_r),    range(0, mid_c)),
        ("TR", range(0, mid_r),    range(mid_c, cols)),
        ("BL", range(mid_r, rows), range(0, mid_c)),
        ("BR", range(mid_r, rows), range(mid_c, cols)),
    ]:
        cells = sum(1 for r in r_range for c in c_range if grid[r][c])
        total_q = len(r_range) * len(c_range)
        quad_fills[qname] = round(100 * cells / max(1, total_q))

    summary += "\nQuadrant fill: " + " | ".join(f"{k}={v}%" for k, v in quad_fills.items())

    # Extreme coverage warnings
    if pct < 30:
        summary += (
            f"\n🚨 CRITICAL LOW COVERAGE: {pct}% — the slide appears nearly "
            f"empty. This is likely an overcorrection. Check whether "
            f"content was accidentally deleted."
        )

    lines.append(summary)
    return "\n".join(lines)


def _preview(blk) -> str:
    """Short text preview for a block, with CSS selector."""
    sel = f" [{blk.css_selector}]" if blk.css_selector else ""
    if blk.text_lines:
        text = " ".join(blk.text_lines)
        return (text[:40] + ("..." if len(text) > 40 else "")) + sel
    return (blk.var_name or blk.block_id) + sel


def _extract_via_subprocess(slide_id: int, html_code: str) -> SlideState:
    """Fallback: extract HTML spatial state via subprocess to avoid asyncio conflicts.

    Runs in a clean, isolated process — so it is correct even when the caller
    holds another sync_playwright context open (the condition that silently
    degrades the in-process path). The paint-over/C3 scans are injected from the
    SAME shared constant as the main path, so this fallback is not blind to them.
    """
    import subprocess
    import json
    import sys

    marker = _PAINTOVER_C3_SCAN_MARKER

    script = f'''
import json, sys, os, re, tempfile
sys.path.insert(0, os.getcwd())
from playwright.sync_api import sync_playwright

html = json.loads(sys.stdin.read())

# Pre-render KaTeX formulas so Playwright sees actual rendered math
import subprocess as _sp
def _render_katex(html_src):
    import re as _re
    display_pat = _re.compile(r'\$\$(.+?)\$\$', _re.DOTALL)
    inline_pat = _re.compile(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)')
    formulas = []
    for m in display_pat.finditer(html_src):
        latex = m.group(1).strip()
        if any(c in latex for c in ('\\\\', '_', '^')):
            formulas.append((m.group(0), latex, True))
    for m in inline_pat.finditer(html_src):
        latex = m.group(1).strip()
        if any(c in latex for c in ('\\\\', '_', '^')):
            formulas.append((m.group(0), latex, False))
    if not formulas:
        return html_src
    rendered_any = False
    for full, latex, display in formulas:
        try:
            cmd = ["npx", "katex", "--no-throw-on-error"]
            if display:
                cmd.append("--display-mode")
            r = _sp.run(cmd, input=latex, capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                html_src = html_src.replace(full, r.stdout.strip(), 1)
                rendered_any = True
        except Exception:
            pass
    if rendered_any:
        css_link = '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.45/dist/katex.min.css">'
        if css_link not in html_src:
            if "<head>" in html_src:
                html_src = html_src.replace("<head>", f"<head>\\n{{css_link}}", 1)
            elif "<style>" in html_src:
                html_src = html_src.replace("<style>", f"{{css_link}}\\n<style>", 1)
    return html_src

html = _render_katex(html)

pw = sync_playwright().start()
browser = pw.chromium.launch(headless=True)

# Fix image paths
# 1. Absolute paths
html = re.sub(r'(<img\\s[^>]*src=["\\'\\'])(/[^"\\'\\' ]+)(["\\'\\'])', r'\\1file://\\2\\3', html)
# 2. Relative paths — resolve from CWD upward
_cwd = os.getcwd()
_roots = [_cwd]
_p = os.path.abspath(_cwd)
for _ in range(6):
    if os.path.isdir(os.path.join(_p, "cases")) or os.path.isdir(os.path.join(_p, "app")):
        if _p != _cwd:
            _roots.append(_p)
        break
    _p = os.path.dirname(_p)

def _resolve_rel(m):
    prefix, path, suffix = m.group(1), m.group(2), m.group(3)
    if path.startswith(('file://', 'http://', 'https://', 'data:', '/')):
        return m.group(0)
    for root in _roots:
        abs_path = os.path.join(root, path)
        if os.path.exists(abs_path):
            return f'{{prefix}}file://{{abs_path}}{{suffix}}'
    return m.group(0)

html = re.sub(r'(<img\\s[^>]*src=["\\'\\'])([^"\\'\\' ]+)(["\\'\\'])', _resolve_rel, html)

page = browser.new_page(viewport={{"width": 1280, "height": 720}}, device_scale_factor=2)
with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tmp:
    tmp.write(html)
    tmp_path = tmp.name
try:
    page.goto(f"file://{{tmp_path}}", wait_until="networkidle")
    page.wait_for_timeout(200)
    elements = page.evaluate("""() => {{
        function parseColor(str) {{
            const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/);
            if (m) return {{r: +m[1], g: +m[2], b: +m[3], a: m[4] !== undefined ? +m[4] : 1.0}};
            return null;
        }}
        function compositeAlpha(fg, bg) {{
            if (!fg || fg.a === undefined || fg.a >= 1.0) return fg;
            if (!bg) bg = {{r: 255, g: 255, b: 255, a: 1.0}};
            const a = fg.a;
            return {{
                r: Math.round(fg.r * a + bg.r * (1 - a)),
                g: Math.round(fg.g * a + bg.g * (1 - a)),
                b: Math.round(fg.b * a + bg.b * (1 - a)),
                a: 1.0
            }};
        }}
        function luminance(c) {{
            const sRGB = [c.r/255, c.g/255, c.b/255];
            const lin = sRGB.map(v => v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4));
            return 0.2126*lin[0] + 0.7152*lin[1] + 0.0722*lin[2];
        }}
        function contrastRatio(fg, bg) {{
            const L1 = Math.max(luminance(fg), luminance(bg));
            const L2 = Math.min(luminance(fg), luminance(bg));
            return (L1 + 0.05) / (L2 + 0.05);
        }}
        function getEffectiveBg(el) {{
            // Special handling for table cells: <tr> background is not
            // returned by elementsFromPoint, so check table ancestors first.
            const tag = el.tagName.toLowerCase();
            if (tag === 'th' || tag === 'td') {{
                let tableAnc = el.parentElement;
                while (tableAnc && tableAnc !== document.body) {{
                    const tTag = tableAnc.tagName.toLowerCase();
                    if (tTag === 'tr' || tTag === 'thead' || tTag === 'tbody' || tTag === 'tfoot' || tTag === 'table') {{
                        const s = window.getComputedStyle(tableAnc);
                        const bg = s.backgroundColor;
                        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return parseColor(bg);
                    }}
                    if (tTag === 'table') break;
                    tableAnc = tableAnc.parentElement;
                }}
            }}
            const ownStyle = window.getComputedStyle(el);
            const ownBg = ownStyle.backgroundColor;
            if (ownBg && ownBg !== 'rgba(0, 0, 0, 0)' && ownBg !== 'transparent') {{
                const parsed = parseColor(ownBg);
                if (parsed && parsed.a >= 1.0) return parsed;
                if (parsed && parsed.a > 0 && parsed.a < 1.0) {{
                    let parentBg = {{r: 255, g: 255, b: 255, a: 1.0}};
                    let pNode = el.parentElement;
                    while (pNode && pNode !== document.documentElement) {{
                        const ps = window.getComputedStyle(pNode);
                        const pbg = ps.backgroundColor;
                        if (pbg && pbg !== 'rgba(0, 0, 0, 0)' && pbg !== 'transparent') {{
                            const pp = parseColor(pbg);
                            if (pp && pp.a >= 1.0) {{ parentBg = pp; break; }}
                        }}
                        pNode = pNode.parentElement;
                    }}
                    return compositeAlpha(parsed, parentBg);
                }}
            }}
            const rect = el.getBoundingClientRect();
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            try {{
                const stack = document.elementsFromPoint(cx, cy);
                const selfIdx = stack.indexOf(el);
                const start = selfIdx >= 0 ? selfIdx + 1 : 0;
                for (let i = start; i < stack.length; i++) {{
                    const node = stack[i];
                    if (node === document.documentElement) continue;
                    const s = window.getComputedStyle(node);
                    const bg = s.backgroundColor;
                    if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return parseColor(bg);
                }}
            }} catch(e) {{}}
            let node = el.parentElement;
            while (node && node !== document.documentElement) {{
                const s = window.getComputedStyle(node);
                const bg = s.backgroundColor;
                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return parseColor(bg);
                node = node.parentElement;
            }}
            return {{r: 255, g: 255, b: 255}};
        }}
        function countLines(el) {{
            const range = document.createRange();
            const cn = el.childNodes;
            if (cn.length === 0) return 0;
            range.setStart(cn[0], 0);
            range.setEnd(cn[cn.length-1], cn[cn.length-1].length || 0);
            const rects = range.getClientRects();
            const tops = new Set();
            for (const r of rects) tops.add(Math.round(r.top));
            return tops.size;
        }}
        const results = [];
        const allElements = document.body.querySelectorAll('*');
        for (const el of allElements) {{
            const tag = el.tagName.toLowerCase();
            if (['html','body','head','style','script','meta','link','br'].includes(tag)) continue;
            if (el.closest('.katex') && !el.classList.contains('katex-display')) continue;
            if (el.closest('.katex-mathml')) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width < 3 || rect.height < 3) continue;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) continue;
            let directText = '';
            for (const node of el.childNodes) {{
                if (node.nodeType === 3) directText += node.textContent;
            }}
            directText = directText.trim();
            const isImg = tag === 'img';
            const isContainer = ['div','section','main','article','header','footer','nav'].includes(tag);
            const isStructural = ['ul','ol','li','table','tbody','thead','tfoot','tr','td','th','dl','dt','dd','details','summary','fieldset','figure','figcaption'].includes(tag);
            const isFilled = (() => {{
                const bg = style.backgroundColor;
                const bi = style.backgroundImage;
                const hasBg = bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent';
                const hasBi = bi && bi !== 'none';
                return !!(hasBg || hasBi);
            }})();
            let shapeType = 'textbox';
            if ((isContainer || isStructural) && !directText && !isImg) {{
                if (!isFilled || rect.width < 20 || rect.height < 14) continue;
                shapeType = 'shape';
            }}
            let styledHeight = 0;
            const rawH = style.height;
            if (rawH && rawH !== 'auto' && rawH !== '' && !rawH.includes('%')) {{
                styledHeight = parseFloat(rawH) || 0;
            }}
            const styledOverflow = style.overflow || '';
            const fontSize = parseFloat(style.fontSize) || 16;
            // Effective font size accounting for transform:scale
            let effectiveFontSize = fontSize;
            const tfm = style.transform;
            if (tfm && tfm !== 'none') {{
                const scaleMatch = tfm.match(/matrix\\(([\\d.e+-]+)/);
                if (scaleMatch) {{
                    const scaleFactor = Math.abs(parseFloat(scaleMatch[1]));
                    if (scaleFactor > 0 && scaleFactor < 1) effectiveFontSize = fontSize * scaleFactor;
                }}
            }}
            // clip-path detection
            const hasClipPath = style.clipPath && style.clipPath !== 'none';
            if (isImg) shapeType = 'picture';
            else if (tag === 'table') shapeType = 'table';
            else if (tag === 'svg' || el.closest('svg')) shapeType = 'chart';
            else if (['h1','h2'].includes(tag)) shapeType = 'title';
            let isOverflowing = el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2;
            let overflowRight = Math.max(0, el.scrollWidth - el.clientWidth);
            let overflowBottom = Math.max(0, el.scrollHeight - el.clientHeight);
            let isSvgText = false;
            // --- SVG element detection ---
            const isInSvg = !!el.closest('svg');
            // SVG text clipping: getBBox gives actual text extent
            if ((tag === 'text' || tag === 'tspan') && isInSvg) {{
                isSvgText = true;
                try {{
                    const bbox = el.getBBox();
                    const svgRoot = el.closest('svg');
                    const vb = svgRoot.viewBox && svgRoot.viewBox.baseVal;
                    const svgW = (vb && vb.width) || (svgRoot.width && svgRoot.width.baseVal && svgRoot.width.baseVal.value) || svgRoot.clientWidth;
                    const svgH = (vb && vb.height) || (svgRoot.height && svgRoot.height.baseVal && svgRoot.height.baseVal.value) || svgRoot.clientHeight;
                    const svgX = (vb && vb.x) || 0;
                    const svgY = (vb && vb.y) || 0;
                    let maxClipH = Math.max(0, (bbox.x + bbox.width) - (svgX + svgW)) + Math.max(0, svgX - bbox.x);
                    let maxClipV = Math.max(0, (bbox.y + bbox.height) - (svgY + svgH)) + Math.max(0, svgY - bbox.y);
                    // Use getComputedTextLength() for precise text width
                    let textRenderW = bbox.width;
                    try {{
                        if (tag === 'text' && typeof el.getComputedTextLength === 'function') {{
                            textRenderW = Math.max(textRenderW, el.getComputedTextLength());
                        }}
                    }} catch(e2) {{}}
                    const parent = el.parentElement;
                    if (parent) {{
                        const rects = parent.querySelectorAll(':scope > rect');
                        const cx = bbox.x + textRenderW / 2;
                        const cy = bbox.y + bbox.height / 2;
                        for (const r of rects) {{
                            const rx = parseFloat(r.getAttribute('x') || 0);
                            const ry = parseFloat(r.getAttribute('y') || 0);
                            const rw = parseFloat(r.getAttribute('width') || 0);
                            const rh = parseFloat(r.getAttribute('height') || 0);
                            if (rw < 10 || rh < 10) continue;
                            if (cx >= rx && cx <= rx + rw && cy >= ry && cy <= ry + rh) {{
                                const cR = Math.max(0, (bbox.x + bbox.width) - (rx + rw));
                                const cL = Math.max(0, rx - bbox.x);
                                const cB = Math.max(0, (bbox.y + bbox.height) - (ry + rh));
                                const cT = Math.max(0, ry - bbox.y);
                                maxClipH = Math.max(maxClipH, cR + cL);
                                maxClipV = Math.max(maxClipV, cB + cT);
                                break;
                            }}
                        }}
                    }}
                    if (maxClipH > 0.5 || maxClipV > 0.5) {{
                        isOverflowing = true;
                        overflowRight = Math.max(overflowRight, Math.round(maxClipH));
                        overflowBottom = Math.max(overflowBottom, Math.round(maxClipV));
                    }}
                }} catch(e) {{}}
            }}
            // SVG non-text element viewBox clipping
            if (isInSvg && !isSvgText && !['svg','defs','clippath','lineargradient','radialgradient','stop','marker'].includes(tag)) {{
                try {{
                    const bbox = el.getBBox();
                    if (bbox.width >= 5 && bbox.height >= 5) {{
                        const svgRoot = el.closest('svg');
                        const vb = svgRoot.viewBox && svgRoot.viewBox.baseVal;
                        const svgW = (vb && vb.width) || (svgRoot.width && svgRoot.width.baseVal && svgRoot.width.baseVal.value) || svgRoot.clientWidth;
                        const svgH = (vb && vb.height) || (svgRoot.height && svgRoot.height.baseVal && svgRoot.height.baseVal.value) || svgRoot.clientHeight;
                        const svgX = (vb && vb.x) || 0;
                        const svgY = (vb && vb.y) || 0;
                        const clipR = Math.max(0, (bbox.x + bbox.width) - (svgX + svgW));
                        const clipL = Math.max(0, svgX - bbox.x);
                        const clipB = Math.max(0, (bbox.y + bbox.height) - (svgY + svgH));
                        const clipT = Math.max(0, svgY - bbox.y);
                        const totalClipH = clipR + clipL;
                        const totalClipV = clipB + clipT;
                        if (totalClipH > 2 || totalClipV > 2) {{
                            isOverflowing = true;
                            overflowRight = Math.max(overflowRight, Math.round(totalClipH));
                            overflowBottom = Math.max(overflowBottom, Math.round(totalClipV));
                        }}
                    }}
                }} catch(e) {{}}
            }}
            const ovfStyle = style.overflow + ' ' + style.overflowX + ' ' + style.overflowY;
            const hasHidden = ovfStyle.includes('hidden');
            // Detect visual overflow when CSS overflow:visible (default)
            if (!isOverflowing && !hasHidden && el.children.length > 0) {{
                const parentRect = el.getBoundingClientRect();
                let visOvfR = 0, visOvfB = 0;
                for (const child of el.children) {{
                    const cr = child.getBoundingClientRect();
                    if (cr.width > 0 && cr.height > 0) {{
                        visOvfR = Math.max(visOvfR, cr.right - parentRect.right);
                        visOvfB = Math.max(visOvfB, cr.bottom - parentRect.bottom);
                    }}
                }}
                if (visOvfR > 2 || visOvfB > 2) {{
                    isOverflowing = true;
                    overflowRight = Math.max(overflowRight, Math.round(visOvfR));
                    overflowBottom = Math.max(overflowBottom, Math.round(visOvfB));
                }}
            }}
            const isClipped = hasHidden && (el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2);
            const clippedBottom = isClipped ? Math.max(0, el.scrollHeight - el.clientHeight) : 0;
            // text-overflow:ellipsis detection
            const isEllipsized = style.textOverflow === 'ellipsis' && hasHidden && el.scrollWidth > el.clientWidth;
            let contrastVal = 0, fgColor = '', bgColor = '';
            if (directText.length > 0 && !isImg) {{
                let fgColorStr = style.color;
                if (isSvgText) {{
                    const svgFill = style.fill || el.getAttribute('fill');
                    if (svgFill && svgFill !== 'none') fgColorStr = svgFill;
                }}
                const fg = parseColor(fgColorStr);
                const bg = getEffectiveBg(el);
                if (fg && bg) {{
                    contrastVal = Math.round(contrastRatio(fg, bg) * 100) / 100;
                    fgColor = fgColorStr;
                    bgColor = `rgb(${{bg.r}},${{bg.g}},${{bg.b}})`;
                }}
            }}
            let lineCount = 0;
            if (directText.length > 10 && !isImg) {{
                try {{ lineCount = countLines(el); }} catch(e) {{}}
            }}
            let imgBroken = false, imgSrc = '';
            let imgCropPct = 0;
            if (isImg) {{
                imgSrc = el.src || el.getAttribute('src') || '';
                imgBroken = el.complete && el.naturalWidth === 0 && imgSrc.length > 0;
                // object-fit crop detection (cover, none, scale-down)
                if (el.naturalWidth > 0 && el.naturalHeight > 0) {{
                    const natW = el.naturalWidth, natH = el.naturalHeight;
                    const boxW = rect.width, boxH = rect.height;
                    const fit = style.objectFit || 'fill';
                    if (fit === 'cover') {{
                        const natRatio = natW / natH;
                        const boxRatio = boxW / boxH;
                        imgCropPct = natRatio > boxRatio
                            ? 1 - (boxRatio / natRatio)
                            : 1 - (natRatio / boxRatio);
                    }} else if (fit === 'none') {{
                        const visW = Math.min(boxW, natW);
                        const visH = Math.min(boxH, natH);
                        imgCropPct = 1 - (visW * visH) / (natW * natH);
                    }} else if (fit === 'scale-down') {{
                        if (natW <= boxW && natH <= boxH) {{
                            imgCropPct = 0;
                        }} else {{
                            imgCropPct = 0;  // behaves like contain
                        }}
                    }}
                    imgCropPct = Math.round(imgCropPct * 1000) / 1000;
                }}
            }}
            const zIndex = parseInt(style.zIndex) || 0;
            // Visual bounds including descendants — skip KaTeX internals
            // whose absolute-positioned sub-elements return inflated bboxes.
            // Include .katex container itself (its bbox is correct).
            let vLeft = rect.x, vTop = rect.y, vRight = rect.right, vBottom = rect.bottom;
            for (const desc of el.querySelectorAll('*')) {{
                const katexAncestor = desc.closest('.katex');
                if (katexAncestor && katexAncestor !== desc) continue;
                if (desc.closest('.katex-mathml')) continue;
                const cr = desc.getBoundingClientRect();
                if (cr.width > 0 && cr.height > 0) {{
                    vLeft = Math.min(vLeft, cr.x);
                    vTop = Math.min(vTop, cr.y);
                    vRight = Math.max(vRight, cr.right);
                    vBottom = Math.max(vBottom, cr.bottom);
                }}
            }}
            // Ancestor clipping: check if this element is visually clipped
            // by any ancestor with overflow:hidden/scroll/auto OR by any
            // positioned ancestor with explicit fixed height
            let ancestorClipBottom = 0;
            let ancestorClipRight = 0;
            let ancestor = el.parentElement;
            while (ancestor && ancestor !== document.body) {{
                const aStyle = window.getComputedStyle(ancestor);
                const aOvf = (aStyle.overflow + ' ' + aStyle.overflowY).toLowerCase();
                const hasOverflowProp = aOvf.includes('hidden') || aOvf.includes('scroll') || aOvf.includes('auto');
                const aPos = aStyle.position;
                const hasExplicitH = aStyle.height && aStyle.height !== 'auto' && aStyle.height !== '';
                const isPositioned = aPos === 'absolute' || aPos === 'relative' || aPos === 'fixed';
                const isVisualBoundary = hasOverflowProp || (isPositioned && hasExplicitH);
                if (isVisualBoundary) {{
                    const aRect = ancestor.getBoundingClientRect();
                    const clipB = Math.max(0, rect.bottom - aRect.bottom);
                    const clipR = Math.max(0, rect.right - aRect.right);
                    if (clipB > 2) ancestorClipBottom = Math.max(ancestorClipBottom, Math.round(clipB));
                    if (clipR > 2) ancestorClipRight = Math.max(ancestorClipRight, Math.round(clipR));
                }}
                ancestor = ancestor.parentElement;
            }}
            // Build DOM path for parent-child relationship detection
            let domPath = [];
            let pathEl = el;
            while (pathEl && pathEl !== document.body) {{
                const pTag = pathEl.tagName.toLowerCase();
                const pIdx = Array.from(pathEl.parentElement?.children || []).indexOf(pathEl);
                domPath.unshift(pTag + '[' + pIdx + ']');
                pathEl = pathEl.parentElement;
            }}
            results.push({{
                tag, shapeType, text: directText.substring(0, 500),
                fullText: el.innerText ? el.innerText.substring(0, 1000) : '',
                bbox: {{x: rect.x, y: rect.y, width: rect.width, height: rect.height}},
                visualRect: {{x: vLeft, y: vTop, width: vRight - vLeft, height: vBottom - vTop}},
                fontSize, isOverflowing, overflowRight, overflowBottom, isSvgText, isInSvg,
                isClipped: isClipped || isEllipsized || hasClipPath || imgCropPct > 0.15,
                clippedBottom,
                ancestorClipBottom, ancestorClipRight,
                contrastRatio: contrastVal, fgColor, bgColor,
                renderedLines: lineCount,
                isImg, imgBroken, imgSrc, imgCropPct,
                isEllipsized, hasClipPath, effectiveFontSize,
                zIndex,
                domPath: domPath.join('/'),
                styledHeight, isFilled, styledOverflow,
            }});
        }}
        {marker}
        return results;
    }}""")
finally:
    os.unlink(tmp_path)
page.close()
browser.close()
pw.stop()
print(json.dumps(elements))
'''

    # Inject the shared paint-over/C3 scan JS in place of the marker. We do this
    # via str.replace AFTER the f-string is built so the scan's single braces are
    # not mis-parsed as f-string fields.
    script = script.replace(_PAINTOVER_C3_SCAN_MARKER, _PAINTOVER_C3_SCAN_JS)

    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            input=json.dumps(html_code),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.error("Subprocess extraction failed: %s", result.stderr[-300:])
            return SlideState(slide_id=slide_id)

        elements = json.loads(result.stdout)
    except Exception as e:
        logger.error("Subprocess extraction error: %s", e)
        return SlideState(slide_id=slide_id)

    # Build state from elements (same logic as main path)
    return _build_state_from_elements(slide_id, elements)


def _build_state_from_elements(slide_id: int, elements: list[dict], viewport_exceedances: list[dict] | None = None) -> SlideState:
    """Build SlideState from extracted DOM elements.

    Uses Playwright-provided data directly — no char-based estimation.
    Includes: overflow, contrast, clipping, broken images, z-index occlusion.
    """
    blocks = []
    for i, el in enumerate(elements):
        x, y, w, h = _px_to_inches(el["bbox"])
        if x + w < 0 or y + h < 0 or x > SLIDE_WIDTH or y > SLIDE_HEIGHT:
            continue

        text = el.get("text", "") or el.get("fullText", "")
        # For shape blocks (filled containers with no directText), text_chars
        # should be 0: their fullText includes children's text (el.innerText)
        # but they have no own content. Using fullText's length would make
        # them look like text elements in the overlap filter.
        shape_type_val = el.get("shapeType", "textbox")
        own_text_chars = len(el.get("text", "")) if shape_type_val == "shape" else len(text)
        font_pt = el.get("fontSize", 16) * 0.75
        font_px = el.get("fontSize", 16)

        # Raw px bbox
        bb = el["bbox"]
        bbox_px = (round(bb["x"]), round(bb["y"]), round(bb["width"]), round(bb["height"]))

        # Playwright overflow data — accurate, from rendering engine
        is_overflowing = el.get("isOverflowing", False)
        overflow_bottom = round(el.get("overflowBottom", 0))
        overflow_right = round(el.get("overflowRight", 0))

        # Build CSS selector for code location
        el_id = el.get("id", "")
        el_classes = el.get("classes", "")
        el_tag = el.get("tag", "div")
        if el_id:
            css_sel = f"#{el_id}"
        elif el_classes and isinstance(el_classes, str):
            first_class = el_classes.split()[0] if el_classes.strip() else ""
            css_sel = f".{first_class}" if first_class else el_tag
        else:
            css_sel = el_tag

        blocks.append(ContentBlock(
            block_id=f"blk_{len(blocks)+1:02d}",
            var_name=el.get("tag", "div"),
            shape_type=el.get("shapeType", "textbox"),
            css_selector=css_sel,
            x=round(x, 2), y=round(y, 2),
            w=round(w, 2), h=round(h, 2),
            text_chars=own_text_chars,
            font_size_pt=round(font_pt, 1),
            text_lines=text.split("\n")[:10] if text else [],
            is_overflowing=is_overflowing,
            overflow_bottom_px=overflow_bottom,
            overflow_right_px=overflow_right,
            # Contrast
            contrast_ratio=el.get("contrastRatio", 0.0),
            fg_color=el.get("fgColor", ""),
            bg_color=el.get("bgColor", ""),
            # Rendered lines
            rendered_lines=el.get("renderedLines", 0),
            # Clipping (self or by ancestor overflow:hidden)
            is_clipped=el.get("isClipped", False) or el.get("ancestorClipBottom", 0) > 2,
            clipped_bottom_px=max(round(el.get("clippedBottom", 0)), round(el.get("ancestorClipBottom", 0))),
            clip_parent_tag=el.get("clipParentTag", ""),
            clip_parent_class=el.get("clipParentClass", ""),
            clip_parent_height_px=round(el.get("clipParentHeight", 0)),
            # Image
            img_broken=el.get("imgBroken", False),
            img_src=el.get("imgSrc", ""),
            img_crop_pct=el.get("imgCropPct", 0.0),
            # z-index
            z_index=el.get("zIndex", 0),
            # Raw px data for agent
            bbox_px=bbox_px,
            client_w_px=el.get("clientWidth", 0),
            client_h_px=el.get("clientHeight", 0),
            scroll_w_px=el.get("scrollWidth", 0),
            scroll_h_px=el.get("scrollHeight", 0),
            font_size_px=round(font_px, 1),
            # Blind-spot detection
            is_ellipsized=el.get("isEllipsized", False),
            has_clip_path=el.get("hasClipPath", False),
            is_svg_text=el.get("isSvgText", False),
            is_in_svg=el.get("isInSvg", False),
            effective_font_size_px=round(el.get("effectiveFontSize", font_px), 1),
            dom_path=el.get("domPath", ""),
            # Cross-card paint-over / slide-bottom truncation markers
            is_paint_over=el.get("isPaintOverShape", False),
            paint_over_text=el.get("paintOverText", ""),
            is_bottom_truncated=el.get("isBottomTruncatedShape", False),
            # Styled boundary + fill
            styled_h_px=round(el.get("styledHeight", 0)),
            is_filled=el.get("isFilled", False),
            styled_overflow=el.get("styledOverflow", ""),
        ))
        # Attach visual bounds (including overflowing children) for OOB detection
        vis = el.get("visualRect")
        if vis:
            vx2, vy2, vw2, vh2 = _px_to_inches(vis)
            blocks[-1]._visual_bounds = (round(vx2, 2), round(vy2, 2), round(vw2, 2), round(vh2, 2))

    overlap_pairs = _detect_overlaps(blocks)
    # Filter out sub-pixel / math-glyph overflow (≤8px) — these are
    # rendering artefacts from KaTeX / inline formulas, not real
    # content overflow that the agent can fix.
    # Exception: SVG text has no sub-pixel ambiguity; any overflow clips characters.
    _OVF_THRESHOLD_PX = 8
    overflow_blocks = [
        b.block_id for b in blocks
        if b.is_overflowing
        and (b.overflow_bottom_px > _OVF_THRESHOLD_PX
             or b.overflow_right_px > _OVF_THRESHOLD_PX
             or getattr(b, 'is_svg_text', False))
    ]

    # OOB detection: use visual bounds (including overflowing children) when available
    # Canvas-edge safety margin: text elements near the bottom edge (bottom > 690px)
    # are flagged as OOB because font rendering differences across Playwright sessions
    # (e.g. Liberation Sans vs Segoe UI fallback) can cause different text wrapping,
    # pushing content past the 720px canvas boundary in the final render.
    _CANVAS_EDGE_MARGIN_PX = 30  # 720 - 690 = 30px safety zone
    _CANVAS_EDGE_MARGIN_IN = _CANVAS_EDGE_MARGIN_PX * PX_TO_INCH_Y
    oob_blocks = []
    for b in blocks:
        vx, vy, vw, vh = b._visual_bounds if hasattr(b, '_visual_bounds') else (b.x, b.y, b.w, b.h)
        if vx < -0.03 or vy < -0.03 or vx + vw > SLIDE_WIDTH + 0.03 or vy + vh > SLIDE_HEIGHT + 0.03:
            oob_blocks.append(b.block_id)
        elif (b.text_chars > 10
              and vy + vh > SLIDE_HEIGHT - _CANVAS_EDGE_MARGIN_IN
              and b.shape_type not in ("picture", "chart")):
            # Text element in the canvas-edge safety zone — flag as OOB
            oob_blocks.append(b.block_id)

    # Viewport exceedance: match to nearest containing block or store as raw
    unmatched_exceedances = []
    if viewport_exceedances:
        oob_block_set = set(oob_blocks)
        for exc in viewport_exceedances:
            ex, ey, ew, eh = exc["x"], exc["y"], exc["w"], exc["h"]
            # Find the nearest containing block (block whose bbox contains this element)
            best_block = None
            best_area = float("inf")
            for b in blocks:
                bx, by, bw, bh = b.bbox_px
                # Check if block contains this element (80% containment)
                ix_l = max(bx, ex)
                iy_t = max(by, ey)
                ix_r = min(bx + bw, ex + ew)
                iy_b = min(by + bh, ey + eh)
                if ix_r > ix_l and iy_b > iy_t:
                    intersection = (ix_r - ix_l) * (iy_b - iy_t)
                    el_area = max(ew * eh, 1)
                    if intersection / el_area > 0.3:
                        blk_area = bw * bh
                        if blk_area < best_area:
                            best_area = blk_area
                            best_block = b
            if best_block and best_block.block_id not in oob_block_set:
                oob_blocks.append(best_block.block_id)
                oob_block_set.add(best_block.block_id)
            elif not best_block:
                unmatched_exceedances.append(exc)

    # Low contrast: WCAG AA requires ≥4.5:1 for normal text (<18pt),
    # ≥3:1 for large text (≥18pt or ≥14pt bold)
    low_contrast_blocks = []
    for b in blocks:
        if b.contrast_ratio > 0 and b.text_chars > 3:
            threshold = 3.0 if b.font_size_pt >= 18 else 4.5
            if b.contrast_ratio < threshold:
                low_contrast_blocks.append(b.block_id)

    # Clipped blocks (content hidden by overflow:hidden)
    clipped_blocks = [b.block_id for b in blocks if b.is_clipped]

    # Styled-boundary overflow: content visibly spills past a filled container's
    # CSS height (overflow:visible, so content is NOT hidden — it's overflow, not clip)
    styled_overflow = _detect_styled_overflow(blocks)
    for bid in styled_overflow:
        if bid not in overflow_blocks:
            overflow_blocks.append(bid)

    # Broken images
    broken_images = [b.block_id for b in blocks if b.img_broken]

    # Z-index occlusion: detect when a higher-z element fully covers a lower-z element
    occlusion_pairs = _detect_occlusions(blocks)

    usable_w = USABLE_RIGHT - USABLE_LEFT
    usable_h = USABLE_BOTTOM - USABLE_TOP
    total_area = usable_w * usable_h
    used_area = sum(b.w * b.h for b in blocks)

    return SlideState(
        slide_id=slide_id,
        blocks=blocks,
        total_area=round(total_area, 2),
        used_area=round(min(used_area, total_area), 2),
        free_area=round(max(0, total_area - used_area), 2),
        overlap_pairs=overlap_pairs,
        coord_overlap_pairs=overlap_pairs,
        overflow_blocks=overflow_blocks,
        oob_blocks=oob_blocks,
        alignment_issues=_detect_alignment_issues(blocks),
        low_contrast_blocks=low_contrast_blocks,
        clipped_blocks=clipped_blocks,
        broken_images=broken_images,
        occlusion_pairs=occlusion_pairs,
        viewport_exceedances=unmatched_exceedances,
    )
