"""HTML Spatial State Extraction — DOM-based geometry analysis via Playwright.

Extracts spatial state directly from HTML-rendered slides.
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

            # Extract all visible content elements with bounding boxes
            elements = page.evaluate("""() => {
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
                    const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                    if (m) return {r: +m[1], g: +m[2], b: +m[3]};
                    return null;
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

                    // Skip pure containers with no direct text
                    if ((isContainer || isStructuralContainer) && !directText && !isImg) continue;

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
                    let contrastVal = 0;
                    let fgColor = '';
                    let bgColor = '';
                    if (directText.length > 0 && !isImg) {
                        const fg = parseColor(style.color);
                        const bg = getEffectiveBg(el);
                        if (fg && bg) {
                            contrastVal = Math.round(contrastRatio(fg, bg) * 100) / 100;
                            fgColor = style.color;
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
                        // object-fit:cover crop detection
                        if (el.naturalWidth > 0 && el.naturalHeight > 0 && style.objectFit === 'cover') {
                            const natRatio = el.naturalWidth / el.naturalHeight;
                            const boxRatio = rect.width / rect.height;
                            if (natRatio > boxRatio) {
                                imgCropPct = 1 - (boxRatio / natRatio);  // horizontal crop
                            } else {
                                imgCropPct = 1 - (natRatio / boxRatio);  // vertical crop
                            }
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
                            if (clipB > 2) ancestorClipBottom = Math.max(ancestorClipBottom, Math.round(clipB));
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
                        fontSize, isOverflowing, overflowRight, overflowBottom,
                        clientWidth: el.clientWidth, clientHeight: el.clientHeight,
                        scrollWidth: el.scrollWidth, scrollHeight: el.scrollHeight,
                        isClipped: isClipped || ancestorClipBottom > 2 || isEllipsized || hasClipPath || imgCropPct > 0.15,
                        clippedBottom: Math.max(clippedBottom, ancestorClipBottom),
                        ancestorClipBottom, ancestorClipRight,
                        contrastRatio: contrastVal, fgColor, bgColor,
                        renderedLines: lineCount,
                        isImg, imgBroken, imgSrc, imgCropPct,
                        isEllipsized, hasClipPath, effectiveFontSize,
                        zIndex,
                        domPath: domPath.join('/'),
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
                return {elements: results, viewportExceedances: exceedances};
            }""")
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
    """Detect overlapping block pairs (excluding parent-child nesting).

    Uses visual bounds (which include overflowing descendants like KaTeX
    formulas) when available, falling back to CSS bounding box.
    Containment check uses CSS bbox only (DOM nesting), not visual bounds.
    """
    overlaps = []
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            a, b = blocks[i], blocks[j]
            ax, ay, aw, ah = _visual_rect(a)
            bx, by, bw, bh = _visual_rect(b)
            # Skip tiny elements
            if aw * ah < 0.1 or bw * bh < 0.1:
                continue
            # Skip overlap between SVG/chart internals — but only when
            # neither element has meaningful text (pure paths/shapes)
            if a.shape_type == "chart" and b.shape_type == "chart":
                if a.text_chars < 3 and b.text_chars < 3:
                    continue

            # Check if one fully contains the other (parent-child relationship)
            # Use CSS bbox (not visual bounds) — DOM nesting is a CSS property,
            # not affected by visual overflow from KaTeX etc.
            a_contains_b = (a.x <= b.x and a.y <= b.y and
                           a.x + a.w >= b.x + b.w - 0.05 and
                           a.y + a.h >= b.y + b.h - 0.05)
            b_contains_a = (b.x <= a.x and b.y <= a.y and
                           b.x + b.w >= a.x + a.w - 0.05 and
                           b.y + b.h >= a.y + a.h - 0.05)
            if a_contains_b or b_contains_a:
                continue

            # Check intersection using visual bounds
            x_overlap = max(0, min(ax + aw, bx + bw) - max(ax, bx))
            y_overlap = max(0, min(ay + ah, by + bh) - max(ay, by))
            intersection = x_overlap * y_overlap
            if intersection > 0.05:  # > 0.05 sq inches
                min_area = min(aw * ah, bw * bh)
                ratio = intersection / max(min_area, 0.01)
                if ratio > 0.05:
                    overlaps.append((a.block_id, b.block_id, round(ratio, 3)))
    return overlaps


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
    for a_id, b_id, ratio in state.overlap_pairs:
        a_blk = next((b for b in state.blocks if b.block_id == a_id or b.var_name == a_id), None)
        b_blk = next((b for b in state.blocks if b.block_id == b_id or b.var_name == b_id), None)
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
                # Canvas-edge safety margin: element is within bounds but
                # dangerously close to bottom edge (bottom > 690px)
                exceeds.append(f"bottom edge {by+bh}px in safety zone (>{VIEWPORT_H-30}px) — font rendering variance may push past canvas")
            label = "❌ OUT OF BOUNDS" if not is_safety_margin else "❌ CANVAS EDGE RISK"
            violations.append(
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
            # math glyphs — report as warning, not critical issue
            if max_ovf <= 8:
                warnings.append(
                    f"⚠️ MINOR OVERFLOW: \"{_preview(blk)}\" — {max_ovf}px overflow "
                    f"(likely sub-pixel or math glyph rendering). Safe to ignore unless visually clipped."
                )
                continue
            violations.append(
                f"❌ TEXT OVERFLOW: \"{_preview(blk)}\"\n"
                f"   scrollHeight: {blk.scroll_h_px}px | clientHeight: {blk.client_h_px}px | "
                f"overflow: {ovf_v}px vertical\n"
                f"   scrollWidth: {blk.scroll_w_px}px | clientWidth: {blk.client_w_px}px | "
                f"overflow: {ovf_h}px horizontal\n"
                f"   font-size: {blk.font_size_px}px | bbox: ({bx}, {by}, {bw}×{bh}) px"
            )

    # Low contrast (WCAG AA violation)
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
        if blk and blk.clipped_bottom_px > 5:
            violations.append(
                f"❌ CLIPPED: \"{_preview(blk)}\"\n"
                f"   {blk.clipped_bottom_px}px of content hidden by overflow:hidden\n"
                f"   scrollHeight: {blk.scroll_h_px}px | clientHeight: {blk.client_h_px}px"
            )

    # Broken images
    for bid in state.broken_images:
        blk = next((b for b in state.blocks if b.block_id == bid), None)
        if blk:
            violations.append(
                f"❌ BROKEN IMAGE: src={blk.img_src or 'unknown'}"
            )

    # Z-index occlusion
    for front_id, back_id in state.occlusion_pairs:
        front = next((b for b in state.blocks if b.block_id == front_id), None)
        back = next((b for b in state.blocks if b.block_id == back_id), None)
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


def _render_space_map(
    blocks: list,
    canvas_w: int = VIEWPORT_W,
    canvas_h: int = VIEWPORT_H,
    cols: int = 18,
    rows: int = 10,
) -> str:
    """Render an ASCII grid showing spatial occupancy.

    Uses +/-/| grid format and #/. text symbols — research shows these
    yield highest LLM spatial reasoning accuracy (Text2Space, Huang 2026;
    Levental 2026).
    """
    cell_w = canvas_w / cols
    cell_h = canvas_h / rows

    # Build occupancy grid
    grid = [[False] * cols for _ in range(rows)]
    sig_blocks = [b for b in blocks if b.w > 0.2 and b.h > 0.1]
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
    """Fallback: extract HTML spatial state via subprocess to avoid asyncio conflicts."""
    import subprocess
    import json
    import sys

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
            const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
            if (m) return {{r: +m[1], g: +m[2], b: +m[3]}};
            return null;
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
            if ((isContainer || isStructural) && !directText && !isImg) continue;
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
            let shapeType = 'textbox';
            if (isImg) shapeType = 'picture';
            else if (tag === 'table') shapeType = 'table';
            else if (tag === 'svg' || el.closest('svg')) shapeType = 'chart';
            else if (['h1','h2'].includes(tag)) shapeType = 'title';
            let isOverflowing = el.scrollHeight > el.clientHeight + 2 || el.scrollWidth > el.clientWidth + 2;
            let overflowRight = Math.max(0, el.scrollWidth - el.clientWidth);
            let overflowBottom = Math.max(0, el.scrollHeight - el.clientHeight);
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
                const fg = parseColor(style.color);
                const bg = getEffectiveBg(el);
                if (fg && bg) {{
                    contrastVal = Math.round(contrastRatio(fg, bg) * 100) / 100;
                    fgColor = style.color;
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
                // object-fit:cover crop detection
                if (el.naturalWidth > 0 && el.naturalHeight > 0 && style.objectFit === 'cover') {{
                    const natRatio = el.naturalWidth / el.naturalHeight;
                    const boxRatio = rect.width / rect.height;
                    if (natRatio > boxRatio) {{
                        imgCropPct = 1 - (boxRatio / natRatio);
                    }} else {{
                        imgCropPct = 1 - (natRatio / boxRatio);
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
                fontSize, isOverflowing, overflowRight, overflowBottom,
                isClipped: isClipped || isEllipsized || hasClipPath || imgCropPct > 0.15,
                clippedBottom,
                ancestorClipBottom, ancestorClipRight,
                contrastRatio: contrastVal, fgColor, bgColor,
                renderedLines: lineCount,
                isImg, imgBroken, imgSrc, imgCropPct,
                isEllipsized, hasClipPath, effectiveFontSize,
                zIndex,
                domPath: domPath.join('/'),
            }});
        }}
        return results;
    }}""")
finally:
    os.unlink(tmp_path)
page.close()
browser.close()
pw.stop()
print(json.dumps(elements))
'''

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
            text_chars=len(text),
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
            effective_font_size_px=round(el.get("effectiveFontSize", font_px), 1),
            dom_path=el.get("domPath", ""),
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
    _OVF_THRESHOLD_PX = 8
    overflow_blocks = [
        b.block_id for b in blocks
        if b.is_overflowing
        and (b.overflow_bottom_px > _OVF_THRESHOLD_PX
             or b.overflow_right_px > _OVF_THRESHOLD_PX)
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

    # Clipped blocks
    clipped_blocks = [b.block_id for b in blocks if b.is_clipped]

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
