"""FigureExtractor - extract figures, tables, and page screenshots from PDFs.

Unified extraction module based on the proven Method C (three-layer) approach:
  Layer 1: get_images()    -> embedded raster images (photos, pre-rendered charts)
  Layer 2: get_drawings()  -> vector-drawn figures (plots, diagrams, heatmaps)
  Layer 3: spatial grouping -> merge adjacent small images into composite figures
  Table:   find_tables()   -> structured table extraction with sub-table merging
  Screenshots: get_pixmap() -> full-page renders for VLM

Replaces the old PdfProcessor and MarkerProcessor figure extraction.
No LLM/VLM calls needed for extraction itself.
"""

import hashlib
import json
import logging
import re
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

from ..schemas.evidence import FigureRef, TableRef

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Layer 1 (raster): minimum image dimensions to keep
MIN_IMAGE_DIM = 100
MIN_IMAGE_AREA = 15_000  # px^2

# Layer 2 (vector): clustering parameters
MERGE_GAP = 15.0        # points: merge drawings within this gap
MIN_DRAWINGS = 4         # minimum drawings in a cluster
MIN_CLUSTER_AREA = 2_000  # minimum cluster area in pt^2
MIN_ASPECT = 0.08        # minimum aspect ratio

# Layer 3 (grouping): merge nearby raster images into composite figures
GROUP_GAP = 8.0          # points: merge images within this gap on same page
MIN_GROUP_IMAGES = 2     # minimum images to form a group

# Dedup
IOU_DEDUP_THRESH = 0.3   # suppress overlapping detections

# Render DPI
FIGURE_DPI = 300
SCREENSHOT_DPI = 200

# Limits
MAX_FIGURES_PER_PDF = 50


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _rect_iou(r1: fitz.Rect, r2: fitz.Rect) -> float:
    """Compute IoU between two fitz.Rects."""
    ix0 = max(r1.x0, r2.x0)
    iy0 = max(r1.y0, r2.y0)
    ix1 = min(r1.x1, r2.x1)
    iy1 = min(r1.y1, r2.y1)
    if ix0 >= ix1 or iy0 >= iy1:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    a1 = max((r1.x1 - r1.x0) * (r1.y1 - r1.y0), 1e-6)
    a2 = max((r2.x1 - r2.x0) * (r2.y1 - r2.y0), 1e-6)
    return inter / (a1 + a2 - inter)


def _rect_overlap_frac(small: fitz.Rect, big: fitz.Rect) -> float:
    """Fraction of small's area that overlaps big."""
    ix0 = max(small.x0, big.x0)
    iy0 = max(small.y0, big.y0)
    ix1 = min(small.x1, big.x1)
    iy1 = min(small.y1, big.y1)
    if ix0 >= ix1 or iy0 >= iy1:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area = max((small.x1 - small.x0) * (small.y1 - small.y0), 1e-6)
    return inter / area


def _cluster_rects(rects: list[fitz.Rect], gap: float) -> list[fitz.Rect]:
    """Iteratively merge overlapping/nearby rects."""
    if not rects:
        return []
    rects = [fitz.Rect(r) for r in rects]
    changed = True
    while changed:
        changed = False
        merged, used = [], [False] * len(rects)
        for i in range(len(rects)):
            if used[i]:
                continue
            cur = fitz.Rect(rects[i])
            exp = fitz.Rect(cur.x0 - gap, cur.y0 - gap, cur.x1 + gap, cur.y1 + gap)
            for j in range(i + 1, len(rects)):
                if used[j]:
                    continue
                if exp.intersects(rects[j]):
                    cur = cur | rects[j]
                    exp = fitz.Rect(cur.x0 - gap, cur.y0 - gap, cur.x1 + gap, cur.y1 + gap)
                    used[j] = True
                    changed = True
            merged.append(cur)
            used[i] = True
        rects = merged

    # Post-merge: combine clusters sharing >60% Y-overlap (multi-panel figures)
    changed = True
    while changed:
        changed = False
        new_rects, used = [], [False] * len(rects)
        for i in range(len(rects)):
            if used[i]:
                continue
            cur = fitz.Rect(rects[i])
            for j in range(i + 1, len(rects)):
                if used[j]:
                    continue
                o = rects[j]
                y_overlap = max(0, min(cur.y1, o.y1) - max(cur.y0, o.y0))
                min_h = min(cur.y1 - cur.y0, o.y1 - o.y0)
                if min_h > 0 and y_overlap / min_h > 0.6:
                    cur = cur | o
                    used[j] = True
                    changed = True
            new_rects.append(cur)
            used[i] = True
        rects = new_rects

    return rects


# ---------------------------------------------------------------------------
# Surya-based layout detection (replaces Layer 1/2/3)
# ---------------------------------------------------------------------------

# Surya detection config
SURYA_CONFIDENCE_THRESH = 0.30
SURYA_MIN_AREA_PX = 2500             # minimum area in pixels² at render DPI
SURYA_BBOX_PADDING_PT = 8.0          # padding in PDF points
SURYA_ADJACENT_MERGE_GAP_PT = 15.0   # merge same-type bboxes within this gap

SURYA_FIGURE_LABELS = {"figure", "picture", "image"}
SURYA_TABLE_LABELS = {"table"}
SURYA_CAPTION_LABELS = {"caption"}


def _detect_with_surya(
    doc,
    layout_predictor,
    dpi: int = FIGURE_DPI,
) -> list[dict]:
    """Use Surya LayoutPredictor to detect figures and tables.

    Returns list of dicts compatible with existing _deduplicate/_save_results,
    using layer="composite" for figures and layer="table" for tables.
    """
    scale = dpi / 72.0

    # Render all pages as PIL images
    page_images = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        page_images.append(img)

    # Run Surya layout detection
    layout_results = layout_predictor(page_images)

    # Collect caption bboxes per page
    caption_rects_by_page: dict[int, list[fitz.Rect]] = {}
    for page_num, result in enumerate(layout_results):
        captions = []
        for bbox in result.bboxes:
            if bbox.label.lower() in SURYA_CAPTION_LABELS:
                x1, y1, x2, y2 = bbox.bbox
                captions.append(fitz.Rect(
                    x1 / scale, y1 / scale, x2 / scale, y2 / scale,
                ))
        caption_rects_by_page[page_num] = captions

    # Extract figure and table bboxes
    raw_items = []
    for page_num, result in enumerate(layout_results):
        page = doc[page_num]
        page_rect = page.rect

        for bbox in result.bboxes:
            label = bbox.label.lower()
            confidence = bbox.confidence

            is_figure = label in SURYA_FIGURE_LABELS
            is_table = label in SURYA_TABLE_LABELS
            if not is_figure and not is_table:
                continue
            if confidence < SURYA_CONFIDENCE_THRESH:
                continue

            # Pixel → PDF point coordinates
            x1, y1, x2, y2 = bbox.bbox
            pt_rect = fitz.Rect(
                x1 / scale, y1 / scale, x2 / scale, y2 / scale,
            )

            # Area check in pixel space
            px_area = (x2 - x1) * (y2 - y1)
            if px_area < SURYA_MIN_AREA_PX:
                continue

            # Skip near-full-page detections
            page_area = page_rect.width * page_rect.height
            pt_area = (pt_rect.x1 - pt_rect.x0) * (pt_rect.y1 - pt_rect.y0)
            if page_area > 0 and pt_area > page_area * 0.80:
                continue

            # Add padding
            padded = fitz.Rect(
                max(0, pt_rect.x0 - SURYA_BBOX_PADDING_PT),
                max(0, pt_rect.y0 - SURYA_BBOX_PADDING_PT),
                min(page_rect.x1, pt_rect.x1 + SURYA_BBOX_PADDING_PT),
                min(page_rect.y1, pt_rect.y1 + SURYA_BBOX_PADDING_PT),
            )

            # Use "composite" for figures (triggers crop path in _save_results)
            # Use "table" for tables (triggers table path in _save_results)
            raw_items.append({
                "layer": "table" if is_table else "composite",
                "page": page_num,
                "rect": padded,
                "confidence": confidence,
                "surya_label": label,
            })

    # Merge adjacent same-type bboxes (fixes fragmented figure grids)
    merged_items = _merge_adjacent_surya_bboxes(raw_items)

    # Subtract overlapping caption regions from figure/table rects
    for item in merged_items:
        page_num = item["page"]
        captions = caption_rects_by_page.get(page_num, [])
        item["rect"] = _subtract_caption_from_rect(
            item["rect"], captions, doc[page_num].rect,
        )

    logger.info(
        "Surya detection: %d items (%d figures, %d tables) from %d pages",
        len(merged_items),
        sum(1 for x in merged_items if x["layer"] != "table"),
        sum(1 for x in merged_items if x["layer"] == "table"),
        len(doc),
    )
    return merged_items


def _merge_adjacent_surya_bboxes(items: list[dict]) -> list[dict]:
    """Merge same-page, same-layer bboxes that are spatially adjacent."""
    from collections import defaultdict

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for item in items:
        key = (item["page"], item["layer"])
        groups[key].append(item)

    merged_items = []
    for (page_num, layer), group in groups.items():
        if len(group) <= 1:
            merged_items.extend(group)
            continue

        if layer != "table":
            # Merge adjacent figure bboxes
            rects = [item["rect"] for item in group]
            clusters = _cluster_rects(rects, SURYA_ADJACENT_MERGE_GAP_PT)

            for cluster_rect in clusters:
                members = [
                    it for it in group
                    if _rect_overlap_frac(it["rect"], cluster_rect) > 0.3
                ]
                if not members:
                    continue
                best_conf = max(m.get("confidence", 0) for m in members)
                merged_items.append({
                    "layer": layer,
                    "page": page_num,
                    "rect": cluster_rect,
                    "confidence": best_conf,
                    "surya_label": "figure",
                    "n_merged": len(members),
                })
        else:
            # Tables: don't merge (existing _merge_sub_tables handles this)
            merged_items.extend(group)

    return merged_items


def _subtract_caption_from_rect(
    rect: fitz.Rect,
    caption_rects: list[fitz.Rect],
    page_rect: fitz.Rect,
) -> fitz.Rect:
    """Shrink figure/table rect to exclude overlapping Surya caption bboxes."""
    if not caption_rects:
        return rect

    rect_h = rect.y1 - rect.y0
    rect_w = rect.x1 - rect.x0

    for cap in caption_rects:
        x_overlap = min(rect.x1, cap.x1) - max(rect.x0, cap.x0)
        if x_overlap < rect_w * 0.3:
            continue

        # Caption below figure: shrink bottom
        if cap.y0 >= rect.y0 + rect_h * 0.5 and cap.y0 < rect.y1:
            new_y1 = cap.y0 - 2
            if new_y1 > rect.y0 + 30:
                rect = fitz.Rect(rect.x0, rect.y0, rect.x1, new_y1)

        # Caption above figure: shrink top
        elif cap.y1 <= rect.y0 + rect_h * 0.5 and cap.y1 > rect.y0:
            new_y0 = cap.y1 + 2
            if new_y0 < rect.y1 - 30:
                rect = fitz.Rect(rect.x0, new_y0, rect.x1, rect.y1)

    return rect


def _enrich_surya_tables_with_structure(
    doc, surya_tables: list[dict],
) -> list[dict]:
    """Add structured row/col data from find_tables() to Surya table bboxes."""
    enriched = []

    for item in surya_tables:
        page = doc[item["page"]]
        rect = item["rect"]
        caption = _find_table_caption(page, rect)

        rows = []
        row_count = 0
        col_count = 0
        try:
            tabs = page.find_tables()
            for t in tabs.tables:
                t_rect = fitz.Rect(t.bbox)
                if _rect_overlap_frac(t_rect, rect) > 0.5:
                    try:
                        extracted = t.extract()
                        rows.extend(extracted)
                        row_count += t.row_count
                        col_count = max(col_count, t.col_count)
                    except Exception:
                        pass
        except Exception:
            pass

        enriched.append({
            "layer": "table",
            "page": item["page"],
            "rect": rect,
            "caption": caption,
            "rows": rows,
            "row_count": row_count,
            "col_count": col_count,
            "confidence": item.get("confidence", 0),
        })

    return enriched


# ---------------------------------------------------------------------------
# Caption finders
# ---------------------------------------------------------------------------

def _find_figure_caption(
    page, rect: fitz.Rect, search_below: float = 60, search_above: float = 20
) -> str:
    """Search for 'Figure N:' or 'Table N:' caption near a rect."""
    blocks = page.get_text("dict")["blocks"]
    best, best_dist = "", 999
    for b in blocks:
        if b["type"] != 0:
            continue
        text = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
        if not re.match(r"(?:Figure|Fig\.?|Table)\s+\d+", text, re.IGNORECASE):
            continue
        by0, by1 = b["bbox"][1], b["bbox"][3]
        if rect.y1 - search_above <= by0 <= rect.y1 + search_below:
            d = abs(by0 - rect.y1)
            if d < best_dist:
                best_dist = d
                best = text[:800]
        if rect.y0 - search_below <= by1 <= rect.y0 + search_above:
            d = abs(rect.y0 - by1)
            if d < best_dist:
                best_dist = d
                best = text[:800]
    return best


def _find_table_caption(
    page, rect: fitz.Rect, search_below: float = 40, search_above: float = 40
) -> str:
    """Search for 'Table N:' caption near a table rect."""
    blocks = page.get_text("dict")["blocks"]
    best, best_dist = "", 999
    for b in blocks:
        if b["type"] != 0:
            continue
        text = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
        if not re.match(r"(?:Table)\s+\d+", text, re.IGNORECASE):
            continue
        by0, by1 = b["bbox"][1], b["bbox"][3]
        if rect.y1 - 5 <= by0 <= rect.y1 + search_below:
            d = abs(by0 - rect.y1)
            if d < best_dist:
                best_dist = d
                best = text[:800]
        if rect.y0 - search_above <= by1 <= rect.y0 + 10:
            d = abs(rect.y0 - by1)
            if d < best_dist:
                best_dist = d
                best = text[:800]
    return best


# ---------------------------------------------------------------------------
# Image post-processing
# ---------------------------------------------------------------------------

def _auto_trim_whitespace(
    pix_path: Path, threshold: int = 245, min_margin: int = 4
) -> tuple[int, int]:
    """Trim whitespace borders from a saved PNG image."""
    img = Image.open(pix_path).convert("RGB")
    arr = np.array(img)
    non_white = np.any(arr < threshold, axis=2)
    rows = np.any(non_white, axis=1)
    cols = np.any(non_white, axis=0)
    if not rows.any() or not cols.any():
        return img.size
    row_min, row_max = np.where(rows)[0][[0, -1]]
    col_min, col_max = np.where(cols)[0][[0, -1]]
    h, w = arr.shape[:2]
    row_min = max(0, row_min - min_margin)
    row_max = min(h - 1, row_max + min_margin)
    col_min = max(0, col_min - min_margin)
    col_max = min(w - 1, col_max + min_margin)
    if max(col_min, w - 1 - col_max, row_min, h - 1 - row_max) < w * 0.03:
        return img.size
    cropped = img.crop((col_min, row_min, col_max + 1, row_max + 1))
    cropped.save(pix_path)
    return cropped.size


def _crop_and_save(
    page, rect: fitz.Rect, dpi: int, output_dir: Path,
    prefix: str, page_num: int
) -> tuple[Path | None, int, int]:
    """Crop a region and save as PNG. Returns (path, width, height)."""
    clip = rect & page.rect
    if clip.is_empty:
        return None, 0, 0
    pix = page.get_pixmap(dpi=dpi, clip=clip)
    fname = f"{prefix}_p{page_num + 1}_{int(clip.x0)}_{int(clip.y0)}.png"
    out = output_dir / fname
    pix.save(str(out))
    final_w, final_h = _auto_trim_whitespace(out)
    return out, final_w, final_h


def _trim_body_text(page, rect: fitz.Rect, caption: str = "") -> fitz.Rect:
    """Shrink rect to exclude body text paragraphs bleeding into the figure."""
    blocks = page.get_text("dict")["blocks"]
    rect_w = rect.x1 - rect.x0
    rect_h = rect.y1 - rect.y0
    body_blocks_top = []
    body_blocks_bot = []
    body_blocks_left = []
    body_blocks_right = []

    for b in blocks:
        if b["type"] != 0:
            continue
        bx0, by0, bx1, by1 = b["bbox"]
        bw = bx1 - bx0
        bh = by1 - by0
        text = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
        if re.match(r"(?:Figure|Fig\.?|Table)\s+\d+", text, re.IGNORECASE):
            continue
        n_lines = len(b.get("lines", []))
        avg_chars_per_line = len(text) / max(n_lines, 1)
        if len(text) < 80 or avg_chars_per_line < 30:
            continue

        # Vertical overlap with figure
        v_overlap = min(by1, rect.y1) - max(by0, rect.y0)
        # Horizontal overlap with figure
        h_overlap = min(bx1, rect.x1) - max(bx0, rect.x0)

        # Side body text (tall text block overlapping vertically, to left/right)
        if v_overlap > rect_h * 0.3 and bw > 50:
            block_mid_x = (bx0 + bx1) / 2
            rect_mid_x = (rect.x0 + rect.x1) / 2
            # Left side: text block center is left of figure center,
            # and text right edge bleeds into figure
            if block_mid_x < rect_mid_x and bx1 > rect.x0 and bx0 < rect.x0:
                body_blocks_left.append(b)
                continue
            # Right side
            if block_mid_x > rect_mid_x and bx0 < rect.x1 and bx1 > rect.x1:
                body_blocks_right.append(b)
                continue

        # Top/bottom body text (original logic)
        if bw < rect_w * 0.3:
            continue
        if h_overlap < rect_w * 0.3:
            continue
        if by1 < rect.y0 or by0 > rect.y1:
            continue
        rect_mid_y = (rect.y0 + rect.y1) / 2
        block_mid_y = (by0 + by1) / 2
        if block_mid_y < rect_mid_y:
            body_blocks_top.append(b)
        else:
            body_blocks_bot.append(b)

    new_rect = fitz.Rect(rect)
    if body_blocks_top:
        max_body_bottom = max(b["bbox"][3] for b in body_blocks_top)
        trim_amount = max_body_bottom - new_rect.y0
        if 0 < trim_amount < rect_h * 0.30:
            new_rect.y0 = max_body_bottom + 2
    if body_blocks_bot:
        min_body_top = min(b["bbox"][1] for b in body_blocks_bot)
        trim_amount = new_rect.y1 - min_body_top
        if 0 < trim_amount < rect_h * 0.30:
            new_rect.y1 = min_body_top - 2
    if body_blocks_left:
        max_body_right = max(b["bbox"][2] for b in body_blocks_left)
        trim_amount = max_body_right - new_rect.x0
        if 0 < trim_amount < rect_w * 0.30:
            new_rect.x0 = max_body_right + 2
    if body_blocks_right:
        min_body_left = min(b["bbox"][0] for b in body_blocks_right)
        trim_amount = new_rect.x1 - min_body_left
        if 0 < trim_amount < rect_w * 0.30:
            new_rect.x1 = min_body_left - 2
    return new_rect


# ---------------------------------------------------------------------------
# Table detection helpers
# ---------------------------------------------------------------------------

def _get_table_rects(page) -> list[fitz.Rect]:
    try:
        return [fitz.Rect(t.bbox) for t in page.find_tables().tables]
    except Exception:
        return []


def _is_not_real_table(
    table_rect: fitz.Rect, drawings: list[dict], page_rect: fitz.Rect
) -> bool:
    """Detect if a 'table' detected by find_tables() is actually a figure."""
    table_area = (table_rect.x1 - table_rect.x0) * (table_rect.y1 - table_rect.y0)
    page_area = page_rect.width * page_rect.height
    inside = 0
    nearby = 0
    expanded = fitz.Rect(
        table_rect.x0 - 30, table_rect.y0 - 30,
        table_rect.x1 + 30, table_rect.y1 + 30,
    )
    for d in drawings:
        r = d["rect"]
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if table_rect.contains(fitz.Point(cx, cy)):
            inside += 1
        elif expanded.contains(fitz.Point(cx, cy)):
            nearby += 1
    if table_area < page_area * 0.05:
        if inside > 30 or (nearby > 20 and inside + nearby > 50):
            return True
    if inside > 50:
        return True
    if inside > 20 and nearby > 30:
        return True
    return False


def _merge_sub_tables(sub_tables: list[dict]) -> list[dict]:
    """Merge adjacent sub-tables that belong to the same logical table."""
    if not sub_tables:
        return []
    subs = sorted(sub_tables, key=lambda t: t["bbox"].y0)
    merged = []
    current = dict(subs[0])
    for i in range(1, len(subs)):
        nxt = subs[i]
        cur_rect = current["bbox"]
        nxt_rect = nxt["bbox"]
        x_overlap = min(cur_rect.x1, nxt_rect.x1) - max(cur_rect.x0, nxt_rect.x0)
        min_width = min(cur_rect.x1 - cur_rect.x0, nxt_rect.x1 - nxt_rect.x0)
        x_frac = x_overlap / max(min_width, 1e-6)
        y_gap = nxt_rect.y0 - cur_rect.y1
        col_diff = abs(current["col_count"] - nxt["col_count"])
        if x_frac > 0.7 and y_gap < 5 and col_diff <= 1:
            current["bbox"] = cur_rect | nxt_rect
            current["rows"].extend(nxt["rows"])
            current["row_count"] += nxt["row_count"]
            current["col_count"] = max(current["col_count"], nxt["col_count"])
        else:
            merged.append(current)
            current = dict(nxt)
    merged.append(current)
    return merged


# ---------------------------------------------------------------------------
# Layer extraction functions
# ---------------------------------------------------------------------------

def _extract_raster_images(doc, page_num: int) -> list[dict]:
    """Layer 1: Extract embedded raster images from a page."""
    page = doc[page_num]
    image_list = page.get_images(full=True)
    seen_xrefs: set[int] = set()
    seen_hashes: set[str] = set()
    results = []

    for img_info in image_list:
        xref = img_info[0]
        if xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)
        try:
            img_data = doc.extract_image(xref)
        except Exception:
            continue
        if not img_data or "image" not in img_data:
            continue
        w = img_data.get("width", 0)
        h = img_data.get("height", 0)
        if w < MIN_IMAGE_DIM or h < MIN_IMAGE_DIM:
            continue
        if w * h < MIN_IMAGE_AREA:
            continue
        content_hash = hashlib.md5(img_data["image"]).hexdigest()
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        try:
            bbox = page.get_image_bbox(img_info)
            if not bbox or bbox.is_empty:
                continue
        except Exception:
            continue
        bbox_w = bbox.x1 - bbox.x0
        bbox_h = bbox.y1 - bbox.y0
        if bbox_w < 50 or bbox_h < 50:
            continue
        results.append({
            "layer": "raster",
            "page": page_num,
            "rect": fitz.Rect(bbox),
            "native_size": (w, h),
            "ext": img_data.get("ext", "png"),
            "xref": xref,
            "img_bytes": img_data["image"],
        })
    return results


def _extract_vector_figures(doc, page_num: int) -> list[dict]:
    """Layer 2: Extract vector-drawn figure regions from a page."""
    page = doc[page_num]
    drawings = page.get_drawings()
    if len(drawings) < MIN_DRAWINGS:
        return []
    raw_tables = _get_table_rects(page)
    tables = [t for t in raw_tables if not _is_not_real_table(t, drawings, page.rect)]
    filtered_rects = []
    for d in drawings:
        r = d["rect"]
        if r.is_empty or r.is_infinite:
            continue
        w, h = r.x1 - r.x0, r.y1 - r.y0
        if w == 0 and h == 0:
            continue
        if h == 0 and w > 50:
            continue
        fill = d.get("fill")
        if fill and all(c > 0.95 for c in fill) and w > 200 and h > 100:
            continue
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if any(t.contains(fitz.Point(cx, cy)) for t in tables):
            continue
        filtered_rects.append(fitz.Rect(r))
    if len(filtered_rects) < MIN_DRAWINGS:
        return []
    clusters = _cluster_rects(filtered_rects, MERGE_GAP)
    results = []
    for cl in clusters:
        n = sum(
            1 for r in filtered_rects
            if cl.contains(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
        )
        if n < MIN_DRAWINGS:
            continue
        area = (cl.x1 - cl.x0) * (cl.y1 - cl.y0)
        if area < MIN_CLUSTER_AREA:
            continue
        cw, ch = cl.x1 - cl.x0, cl.y1 - cl.y0
        if cw == 0 or ch == 0:
            continue
        if min(cw / ch, ch / cw) < MIN_ASPECT:
            continue
        if cw > page.rect.width * 0.8 and ch < 3:
            continue
        # Reject page-spanning clusters
        page_area = page.rect.width * page.rect.height
        if area > page_area * 0.55:
            continue
        if min(cw, ch) / max(cw, ch) < 0.15:
            continue
        # Reject clusters with too much body text inside
        _text_in_rect = page.get_text("text", clip=cl)
        if len(_text_in_rect) > 500:
            continue
        if any(_rect_overlap_frac(cl, t) > 0.6 for t in tables):
            continue
        results.append({
            "layer": "vector",
            "page": page_num,
            "rect": cl,
            "n_drawings": n,
        })
    return results


def _group_nearby_images(raster_items: list[dict]) -> list[dict]:
    """Layer 3: Group spatially adjacent raster images into composite figures."""
    by_page: dict[int, list[dict]] = {}
    for item in raster_items:
        by_page.setdefault(item["page"], []).append(item)
    composites = []
    for page_num, items in by_page.items():
        if len(items) < MIN_GROUP_IMAGES:
            continue
        rects = [item["rect"] for item in items]
        groups = _cluster_rects(rects, GROUP_GAP)
        for group_rect in groups:
            members = [
                it for it in items
                if _rect_overlap_frac(it["rect"], group_rect) > 0.5
            ]
            if len(members) < MIN_GROUP_IMAGES or len(members) == 1:
                continue
            composites.append({
                "layer": "composite",
                "page": page_num,
                "rect": group_rect,
                "n_images": len(members),
            })
    return composites


def _extract_tables(doc, page_num: int) -> list[dict]:
    """Extract tables from a page using find_tables()."""
    page = doc[page_num]
    try:
        tabs = page.find_tables()
    except Exception:
        return []
    if not tabs.tables:
        return []
    drawings = page.get_drawings()
    sub_tables = []
    for t in tabs.tables:
        table_rect = fitz.Rect(t.bbox)
        if _is_not_real_table(table_rect, drawings, page.rect):
            continue
        tw = table_rect.x1 - table_rect.x0
        th = table_rect.y1 - table_rect.y0
        if tw < 30 or th < 8:
            continue
        try:
            rows = t.extract()
        except Exception:
            rows = []
        sub_tables.append({
            "bbox": table_rect,
            "rows": rows,
            "row_count": t.row_count,
            "col_count": t.col_count,
        })
    if not sub_tables:
        return []
    merged = _merge_sub_tables(sub_tables)
    results = []
    for tbl in merged:
        rect = tbl["bbox"]
        caption = _find_table_caption(page, rect)
        clean_rows = []
        for row in tbl["rows"]:
            clean_rows.append([cell if cell is not None else "" for cell in row])
        results.append({
            "layer": "table",
            "page": page_num,
            "rect": rect,
            "caption": caption,
            "rows": clean_rows,
            "row_count": tbl["row_count"],
            "col_count": tbl["col_count"],
        })
    return results


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _deduplicate(all_items: list[dict]) -> list[dict]:
    """Remove overlapping detections across layers."""
    tables = [it for it in all_items if it["layer"] == "table"]
    figures = [it for it in all_items if it["layer"] != "table"]

    # Dedup tables
    tables.sort(
        key=lambda x: -(x["rect"].x1 - x["rect"].x0) * (x["rect"].y1 - x["rect"].y0)
    )
    kept_tables = []
    for tbl in tables:
        suppressed = False
        for existing in kept_tables:
            if existing["page"] != tbl["page"]:
                continue
            if _rect_overlap_frac(tbl["rect"], existing["rect"]) > 0.7:
                suppressed = True
                break
        if not suppressed:
            kept_tables.append(tbl)

    # Dedup figures
    composites = [it for it in figures if it["layer"] == "composite"]
    rasters = [it for it in figures if it["layer"] == "raster"]
    vectors = [it for it in figures if it["layer"] == "vector"]

    # Phase 1: suppress rasters inside composites
    surviving_rasters = []
    for rast in rasters:
        inside_composite = False
        for comp in composites:
            if comp["page"] != rast["page"]:
                continue
            if _rect_overlap_frac(rast["rect"], comp["rect"]) > 0.5:
                inside_composite = True
                break
        if not inside_composite:
            surviving_rasters.append(rast)

    # Phase 2: standard dedup
    ordered = composites + surviving_rasters + vectors
    ordered.sort(key=lambda x: (
        {"composite": 0, "raster": 1, "vector": 2}.get(x["layer"], 9),
        -(x["rect"].x1 - x["rect"].x0) * (x["rect"].y1 - x["rect"].y0),
    ))

    kept_figures = []
    for item in ordered:
        suppressed = False
        for existing in kept_figures:
            if existing["page"] != item["page"]:
                continue
            iou = _rect_iou(item["rect"], existing["rect"])
            overlap = _rect_overlap_frac(item["rect"], existing["rect"])
            if iou > IOU_DEDUP_THRESH or overlap > 0.7:
                suppressed = True
                break
        if not suppressed:
            kept_figures.append(item)

    return kept_tables + kept_figures


# ===================================================================
# FigureExtractor - main public class
# ===================================================================

class FigureExtractor:
    """Extract figures, tables, and screenshots from PDF files.

    Produces FigureRef and TableRef objects in the new pyramid directory
    structure:
        source_pack/figures/     - extracted figure images
        source_pack/tables/      - table screenshots + JSON sidecar data
        source_pack/screenshots/ - full-page renders

    Usage:
        extractor = FigureExtractor(source_pack_dir)
        figures, tables, screenshots = extractor.extract(pdf_path)
    """

    def __init__(self, source_pack_dir: str | Path, layout_predictor=None):
        """Initialize extractor.

        Args:
            source_pack_dir: Path to the source_pack/ directory.
                Creates figures/, tables/, screenshots/ subdirs.
            layout_predictor: Optional Surya LayoutPredictor instance.
                If None, created on first use. Pass an instance to reuse
                across multiple extract() calls (avoids repeated model loading).
        """
        self.source_pack_dir = Path(source_pack_dir)
        self.figures_dir = self.source_pack_dir / "figures"
        self.tables_dir = self.source_pack_dir / "tables"
        self.screenshots_dir = self.source_pack_dir / "screenshots"
        self._layout_predictor = layout_predictor

    def _get_layout_predictor(self):
        """Lazy-load Surya LayoutPredictor."""
        if self._layout_predictor is None:
            from surya.layout import LayoutPredictor
            self._layout_predictor = LayoutPredictor()
        return self._layout_predictor

    def extract(
        self, pdf_path: str | Path
    ) -> tuple[list[FigureRef], list[TableRef], list[FigureRef]]:
        """Full extraction pipeline.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            (figures, tables, screenshots) — lists of schema objects.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        self.figures_dir.mkdir(parents=True, exist_ok=True)
        self.tables_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(str(pdf_path))
        source_file = pdf_path.name
        total_pages = len(doc)

        logger.info("FigureExtractor: processing %s (%d pages)", source_file, total_pages)

        # --- Detection phase: Surya (preferred) with heuristic fallback ---
        try:
            predictor = self._get_layout_predictor()
            surya_items = _detect_with_surya(doc, predictor, dpi=FIGURE_DPI)

            surya_figures = [it for it in surya_items if it["layer"] != "table"]
            surya_tables = [it for it in surya_items if it["layer"] == "table"]

            # Enrich tables with structured row/col data from find_tables()
            enriched_tables = _enrich_surya_tables_with_structure(doc, surya_tables)

            all_items = surya_figures + enriched_tables

            logger.info(
                "Surya path: %d figures, %d tables",
                len(surya_figures), len(enriched_tables),
            )
        except (ImportError, Exception) as e:
            logger.warning(
                "Surya detection unavailable (%s), falling back to heuristic",
                str(e)[:100],
            )
            # Fallback: original 3-layer heuristic
            all_raster = []
            all_vector = []
            all_tables = []

            for page_num in range(total_pages):
                all_raster.extend(_extract_raster_images(doc, page_num))
                all_vector.extend(_extract_vector_figures(doc, page_num))
                all_tables.extend(_extract_tables(doc, page_num))

            composites = _group_nearby_images(all_raster)
            all_items = all_raster + composites + all_vector + all_tables

            logger.info(
                "Heuristic fallback: %d raster, %d composite, %d vector, %d tables",
                len(all_raster), len(composites), len(all_vector), len(all_tables),
            )

        # Deduplicate
        deduped = _deduplicate(all_items)

        logger.info(
            "After dedup: %d items (r=%d, c=%d, v=%d, t=%d)",
            len(deduped),
            sum(1 for x in deduped if x["layer"] == "raster"),
            sum(1 for x in deduped if x["layer"] == "composite"),
            sum(1 for x in deduped if x["layer"] == "vector"),
            sum(1 for x in deduped if x["layer"] == "table"),
        )

        # Save crops and build schema objects
        figures, tables = self._save_results(doc, deduped, source_file)

        # Cap figures
        if len(figures) > MAX_FIGURES_PER_PDF:
            logger.info("Capping figures from %d to %d", len(figures), MAX_FIGURES_PER_PDF)
            figures = figures[:MAX_FIGURES_PER_PDF]

        # Render page screenshots
        screenshots = self._render_screenshots(doc, source_file, total_pages)

        doc.close()

        logger.info(
            "FigureExtractor complete: %d figures, %d tables, %d screenshots",
            len(figures), len(tables), len(screenshots),
        )
        return figures, tables, screenshots

    def _save_results(
        self, doc, items: list[dict], source_file: str
    ) -> tuple[list[FigureRef], list[TableRef]]:
        """Crop and save all detected items.

        ID scheme (unified — these IDs are used as filenames and by all
        downstream modules):
          Figures: fig_p{page}_{label}  e.g. fig_p1_fig1, fig_p8_vec2
          Tables:  tbl_p{page}_{label}  e.g. tbl_p4_tbl1, tbl_p6_tbl2

        Each figure and table also gets a JSON sidecar with metadata
        (caption, page, bbox, figure_type) so SourceIndexer can read
        structured info without guessing from filenames.
        """
        figures: list[FigureRef] = []
        tables: list[TableRef] = []
        fig_idx = 0
        tbl_idx = 0

        for item in items:
            page = doc[item["page"]]
            layer = item["layer"]
            page_num = item["page"]
            rect = item["rect"]
            page_1indexed = page_num + 1

            # --- Table handling ---
            if layer == "table":
                caption = item.get("caption", "")
                pad = 5.0
                rect = fitz.Rect(
                    max(0, rect.x0 - pad), max(0, rect.y0 - pad),
                    min(page.rect.x1, rect.x1 + pad),
                    min(page.rect.y1, rect.y1 + pad),
                )

                # Extend rect to include caption
                if caption:
                    for b in page.get_text("dict")["blocks"]:
                        if b["type"] != 0:
                            continue
                        text = " ".join(
                            s["text"] for l in b["lines"] for s in l["spans"]
                        ).strip()
                        if caption[:30] in text:
                            cap_top = b["bbox"][1]
                            cap_bottom = b["bbox"][3]
                            rect = fitz.Rect(
                                min(rect.x0, b["bbox"][0]),
                                min(rect.y0, cap_top - 2),
                                max(rect.x1, b["bbox"][2]),
                                max(rect.y1, cap_bottom + 2),
                            )
                            rect = rect & page.rect
                            break

                # Build table ID: tbl_p{page}_{label}
                tbl_label_match = re.search(r"(?:Table)\s+(\d+)", caption, re.IGNORECASE)
                label = f"tbl{tbl_label_match.group(1)}" if tbl_label_match else f"t{tbl_idx}"
                tbl_id = f"tbl_p{page_1indexed}_{label}"

                # Save PNG screenshot to tables/
                png_fname = f"{tbl_id}.png"
                clip = rect & page.rect
                if clip.is_empty:
                    continue
                pix = page.get_pixmap(dpi=FIGURE_DPI, clip=clip)
                out = self.tables_dir / png_fname
                pix.save(str(out))
                final_w, final_h = _auto_trim_whitespace(out)

                # Save JSON sidecar with structured data
                rows = item.get("rows", [])
                json_path = self.tables_dir / f"{tbl_id}.json"
                json_data = {
                    "table_id": tbl_id,
                    "page": page_1indexed,
                    "caption": caption,
                    "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
                    "row_count": item.get("row_count", 0),
                    "col_count": item.get("col_count", 0),
                    "rows": rows,
                }
                json_path.write_text(
                    json.dumps(json_data, ensure_ascii=False, indent=2)
                )

                # Build structured content for TableRef
                headers = [str(c).strip() if c else "" for c in rows[0]] if rows else []
                data_rows = []
                for row in rows[1:]:
                    data_rows.append([str(c).strip() if c else "" for c in row])
                content_lines = [" | ".join(headers)]
                content_lines.append(" | ".join(["---"] * max(len(headers), 1)))
                for row in data_rows:
                    content_lines.append(" | ".join(row))
                content = "\n".join(content_lines)

                tables.append(TableRef(
                    table_id=tbl_id,
                    source_file=source_file,
                    content=content,
                    caption=caption,
                    headers=headers,
                    row_count=len(data_rows),
                    image_path=str(out),
                    page_number=page_1indexed,
                    bbox=[rect.x0, rect.y0, rect.x1, rect.y1],
                ))
                tbl_idx += 1
                continue

            # --- Figure handling (raster / vector / composite) ---

            # Skip near-full-page images (likely page screenshots, not figures)
            fig_area = (rect.x1 - rect.x0) * (rect.y1 - rect.y0)
            page_area = page.rect.width * page.rect.height
            if page_area > 0 and fig_area / page_area > 0.70:
                logger.debug(
                    "Skipping near-full-page figure on p%d (%.0f%% of page)",
                    page_1indexed, fig_area / page_area * 100,
                )
                continue

            # Find caption on the UNPADDED rect first (before padding
            # moves the boundary past the caption text block)
            caption = _find_figure_caption(page, rect)

            if layer in ("vector", "composite"):
                # Asymmetric padding: more on sides/bottom (axis labels, legends)
                # less on top (section titles tend to bleed in from above)
                pad_x = 30.0
                pad_top = 15.0
                pad_bot = 30.0
                rect = fitz.Rect(
                    max(0, rect.x0 - pad_x), max(0, rect.y0 - pad_top),
                    min(page.rect.x1, rect.x1 + pad_x),
                    min(page.rect.y1, rect.y1 + pad_bot),
                )

            # Crop caption OUT of the figure rect (avoid including caption text)
            if caption:
                for b in page.get_text("dict")["blocks"]:
                    if b["type"] != 0:
                        continue
                    text = " ".join(
                        s["text"] for l in b["lines"] for s in l["spans"]
                    ).strip()
                    if caption[:30] in text:
                        cap_top = b["bbox"][1]
                        cap_bottom = b["bbox"][3]
                        # Caption below figure: shrink rect bottom
                        if cap_top >= rect.y0 + (rect.y1 - rect.y0) * 0.3:
                            new_y1 = cap_top - 2
                            if new_y1 > rect.y0 + 20:  # keep at least 20pt
                                rect = fitz.Rect(rect.x0, rect.y0, rect.x1, new_y1)
                        # Caption above figure: shrink rect top
                        elif cap_bottom <= rect.y0 + (rect.y1 - rect.y0) * 0.5:
                            new_y0 = cap_bottom + 2
                            if new_y0 < rect.y1 - 20:
                                rect = fitz.Rect(rect.x0, new_y0, rect.x1, rect.y1)
                        break

            # Trim body text
            if layer in ("vector", "composite"):
                rect = _trim_body_text(page, rect, caption)

            # Build figure ID: fig_p{page}_{label}
            fig_label_match = re.search(
                r"(?:Figure|Fig\.?)\s+(\d+)", caption, re.IGNORECASE
            )
            if fig_label_match:
                label = f"fig{fig_label_match.group(1)}"
            elif layer == "composite":
                label = f"comp{fig_idx}"
            elif layer == "raster":
                label = f"img{fig_idx}"
            else:
                label = f"vec{fig_idx}"
            fig_id = f"fig_p{page_1indexed}_{label}"

            # For single raster images: save original bytes if high-res
            if layer == "raster":
                native_w, native_h = item["native_size"]
                if native_w >= 400 and native_h >= 400:
                    ext = item["ext"]
                    fname = f"{fig_id}.{ext}"
                    out = self.figures_dir / fname
                    out.write_bytes(item["img_bytes"])

                    # Save figure sidecar JSON
                    self._save_figure_sidecar(
                        fig_id, caption, page_1indexed, rect, layer,
                        native_w, native_h,
                    )

                    figures.append(FigureRef(
                        figure_id=fig_id,
                        source_file=source_file,
                        image_path=str(out),
                        caption=caption,
                        description=f"Raster image from page {page_1indexed}",
                        page_number=page_1indexed,
                        bbox=[rect.x0, rect.y0, rect.x1, rect.y1],
                        width=native_w,
                        height=native_h,
                        figure_type="raster",
                    ))
                    fig_idx += 1
                    continue

            # Crop from page at high DPI
            clip = rect & page.rect
            if clip.is_empty:
                continue
            pix = page.get_pixmap(dpi=FIGURE_DPI, clip=clip)
            png_fname = f"{fig_id}.png"
            out = self.figures_dir / png_fname
            pix.save(str(out))
            pw, ph = _auto_trim_whitespace(out)

            # Save figure sidecar JSON
            self._save_figure_sidecar(
                fig_id, caption, page_1indexed, rect, layer, pw, ph,
            )

            figures.append(FigureRef(
                figure_id=fig_id,
                source_file=source_file,
                image_path=str(out),
                caption=caption,
                description=f"{layer.capitalize()} figure from page {page_1indexed}",
                page_number=page_1indexed,
                bbox=[rect.x0, rect.y0, rect.x1, rect.y1],
                width=pw,
                height=ph,
                figure_type=layer,
            ))
            fig_idx += 1

        return figures, tables

    def _save_figure_sidecar(
        self,
        fig_id: str,
        caption: str,
        page: int,
        rect: fitz.Rect,
        figure_type: str,
        width: int,
        height: int,
    ) -> None:
        """Save a JSON sidecar for a figure with metadata."""
        sidecar = {
            "figure_id": fig_id,
            "caption": caption,
            "page": page,
            "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
            "figure_type": figure_type,
            "width": width,
            "height": height,
        }
        json_path = self.figures_dir / f"{fig_id}.json"
        json_path.write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2)
        )

    def _render_screenshots(
        self, doc, source_file: str, total_pages: int
    ) -> list[FigureRef]:
        """Render page screenshots for VLM consumption."""
        # Render ALL pages as screenshots (used as fallback when no figures found)
        key_pages: set[int] = set(range(min(total_pages, 30)))

        screenshots: list[FigureRef] = []
        for page_num in sorted(key_pages):
            if page_num >= total_pages:
                continue
            try:
                page = doc[page_num]
                fig_id = f"screenshot_p{page_num + 1}"
                out_path = self.screenshots_dir / f"{fig_id}.png"
                pix = page.get_pixmap(dpi=SCREENSHOT_DPI)
                pix.save(str(out_path))
                screenshots.append(FigureRef(
                    figure_id=fig_id,
                    source_file=source_file,
                    image_path=str(out_path),
                    caption=f"Page {page_num + 1} screenshot",
                    description=f"Full page screenshot of page {page_num + 1}",
                    page_number=page_num + 1,
                    width=pix.width,
                    height=pix.height,
                    figure_type="page_screenshot",
                ))
            except Exception as e:
                logger.warning("Screenshot failed for page %d: %s", page_num + 1, e)

        logger.info("Rendered %d page screenshots", len(screenshots))
        return screenshots
