"""FigureExtractor - extract figures, tables, and page screenshots from PDFs.

Primary: YOLO11 document-layout model (ML-based, GPU-accelerated)
  - Detects Picture, Table, Caption classes with high accuracy
  - Trained on DocLayNet at 1280x1280 resolution

Fallback: 4-layer heuristic (when YOLO unavailable)
  Layer 1: get_images()    -> embedded raster images (photos, pre-rendered charts)
  Layer 2: get_drawings()  -> vector-drawn figures (plots, diagrams, heatmaps)
  Layer 3: spatial grouping -> merge adjacent small images into composite figures
  Layer 4: caption-guided  -> infer figure bbox from caption proximity
  Table:   find_tables()   -> structured table extraction with sub-table merging
  Screenshots: get_pixmap() -> full-page renders for VLM

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
FIGURE_DPI = 400
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
    # BUT only if X-gap is small (avoid merging across columns in dual-column papers)
    MAX_X_GAP_FOR_PANEL_MERGE = 50.0  # points (~17mm)
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
                # X-gap: distance between the two rects horizontally
                x_gap = max(0, max(cur.x0, o.x0) - min(cur.x1, o.x1))
                if (min_h > 0 and y_overlap / min_h > 0.6
                        and x_gap < MAX_X_GAP_FOR_PANEL_MERGE):
                    cur = cur | o
                    used[j] = True
                    changed = True
            new_rects.append(cur)
            used[i] = True
        rects = new_rects

    return rects


# ---------------------------------------------------------------------------
# YOLO11-based layout detection (primary ML path)
# ---------------------------------------------------------------------------

YOLO_MODEL_REPO = "Armaggheddon/yolo11-document-layout"
YOLO_MODEL_FILE = "yolo11m_doc_layout.pt"  # medium model: best accuracy
YOLO_CONFIDENCE_THRESH = 0.30
YOLO_RENDER_SCALE = 2.0      # 2× zoom for 1280px inference
YOLO_BBOX_PADDING_PT = 6.0   # padding in PDF points
YOLO_IMGSZ = 1280             # model trained at this resolution

# DocLayNet label mapping (model classes)
YOLO_FIGURE_LABELS = {"Picture"}
YOLO_TABLE_LABELS = {"Table"}
YOLO_CAPTION_LABELS = {"Caption"}

_yolo_model_cache = None


def _get_yolo_model():
    """Load and cache YOLO11 document layout model."""
    global _yolo_model_cache
    if _yolo_model_cache is not None:
        return _yolo_model_cache
    try:
        from ultralytics import YOLO
        from huggingface_hub import hf_hub_download
        model_path = hf_hub_download(
            repo_id=YOLO_MODEL_REPO,
            filename=YOLO_MODEL_FILE,
        )
        _yolo_model_cache = YOLO(model_path)
        logger.info("YOLO11 document layout model loaded: %s", model_path)
        return _yolo_model_cache
    except Exception as e:
        logger.warning("Cannot load YOLO11 model: %s", e)
        return None


def _detect_with_yolo(doc, dpi_scale: float = YOLO_RENDER_SCALE) -> list[dict]:
    """Use YOLO11 to detect figures, tables, and captions on all pages.

    Returns list of dicts with keys: layer, page, rect, confidence.
    Figures get layer="yolo_figure", tables get layer="table".
    """
    model = _get_yolo_model()
    if model is None:
        return []

    all_items = []
    caption_rects_by_page: dict[int, list[fitz.Rect]] = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(dpi_scale, dpi_scale)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Run YOLO inference
        results = model(img, imgsz=YOLO_IMGSZ, conf=YOLO_CONFIDENCE_THRESH, verbose=False)
        r = results[0]

        page_captions = []
        for box, cls, conf in zip(r.boxes.xyxy, r.boxes.cls, r.boxes.conf):
            label = model.names[int(cls)]
            x1, y1, x2, y2 = box.tolist()
            confidence = conf.item()

            # Convert pixel coords → PDF points
            pt_rect = fitz.Rect(
                x1 / dpi_scale, y1 / dpi_scale,
                x2 / dpi_scale, y2 / dpi_scale,
            )

            if label in YOLO_CAPTION_LABELS:
                page_captions.append(pt_rect)
                continue

            is_figure = label in YOLO_FIGURE_LABELS
            is_table = label in YOLO_TABLE_LABELS
            if not is_figure and not is_table:
                continue

            # Skip tiny detections
            pt_area = (pt_rect.x1 - pt_rect.x0) * (pt_rect.y1 - pt_rect.y0)
            if pt_area < 400:  # ~20x20 pt
                continue

            # Skip near-full-page detections
            page_area = page.rect.width * page.rect.height
            if page_area > 0 and pt_area > page_area * 0.80:
                continue

            # Add light padding
            padded = fitz.Rect(
                max(0, pt_rect.x0 - YOLO_BBOX_PADDING_PT),
                max(0, pt_rect.y0 - YOLO_BBOX_PADDING_PT),
                min(page.rect.x1, pt_rect.x1 + YOLO_BBOX_PADDING_PT),
                min(page.rect.y1, pt_rect.y1 + YOLO_BBOX_PADDING_PT),
            )

            all_items.append({
                "layer": "table" if is_table else "yolo_figure",
                "page": page_num,
                "rect": padded,
                "confidence": confidence,
            })

        caption_rects_by_page[page_num] = page_captions

    # Merge adjacent same-type figure bboxes on the same page
    merged_items = _merge_adjacent_yolo_bboxes(all_items)

    # Subtract caption regions from figure rects
    for item in merged_items:
        if item["layer"] == "table":
            continue
        captions = caption_rects_by_page.get(item["page"], [])
        if captions:
            item["rect"] = _subtract_caption_from_rect(
                item["rect"], captions, doc[item["page"]].rect,
            )

    n_fig = sum(1 for x in merged_items if x["layer"] != "table")
    n_tbl = sum(1 for x in merged_items if x["layer"] == "table")
    logger.info(
        "YOLO detection: %d items (%d figures, %d tables) from %d pages",
        len(merged_items), n_fig, n_tbl, len(doc),
    )
    return merged_items


def _merge_adjacent_yolo_bboxes(items: list[dict]) -> list[dict]:
    """Merge same-page, same-type YOLO bboxes that overlap or are adjacent."""
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
            rects = [item["rect"] for item in group]
            clusters = _cluster_rects(rects, 15.0)
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
                    "n_merged": len(members),
                })
        else:
            merged_items.extend(group)

    return merged_items


def _subtract_caption_from_rect(
    rect: fitz.Rect,
    caption_rects: list[fitz.Rect],
    page_rect: fitz.Rect,
) -> fitz.Rect:
    """Shrink figure/table rect to exclude overlapping caption bboxes."""
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


def _enrich_yolo_tables_with_structure(
    doc, yolo_tables: list[dict],
) -> list[dict]:
    """Add structured row/col data from find_tables() to YOLO table bboxes."""
    enriched = []

    for item in yolo_tables:
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


def _trim_body_text(page, rect: fitz.Rect, caption: str = "", layer: str = "") -> fitz.Rect:
    """Shrink rect to exclude body text paragraphs bleeding into the figure."""
    blocks = page.get_text("dict")["blocks"]
    rect_w = rect.x1 - rect.x0
    rect_h = rect.y1 - rect.y0
    # YOLO bboxes may span both columns in dual-column papers — allow
    # more aggressive trimming (up to 55% of width/height)
    max_trim_frac = 0.55 if layer == "yolo_figure" else 0.30
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
            # Only skip caption-like text if it's directly below/above the
            # figure (within 30pt of the top/bottom edge) AND horizontally
            # overlaps the figure significantly.  Captions from adjacent
            # columns (e.g. "Table 4:" to the left) should NOT be protected.
            h_overlap_cap = min(bx1, rect.x1) - max(bx0, rect.x0)
            h_frac_cap = h_overlap_cap / max(rect_w, 1)
            cap_near_bottom = abs(by0 - rect.y1) < 30 or abs(by1 - rect.y1) < 30
            cap_near_top = abs(by0 - rect.y0) < 30 or abs(by1 - rect.y0) < 30
            if (cap_near_bottom or cap_near_top) and h_frac_cap > 0.3:
                continue
        n_lines = len(b.get("lines", []))
        avg_chars_per_line = len(text) / max(n_lines, 1)
        # Lower threshold: detect even short text fragments that bleed in
        if len(text) < 20 or (n_lines < 2 and avg_chars_per_line < 15):
            continue
        # Skip axis tick labels: many short lines (e.g. "0% 5% 10% 15%")
        if n_lines >= 3 and avg_chars_per_line < 8:
            continue

        # Vertical overlap with figure
        v_overlap = min(by1, rect.y1) - max(by0, rect.y0)
        # Horizontal overlap with figure
        h_overlap = min(bx1, rect.x1) - max(bx0, rect.x0)

        # Side body text (tall text block overlapping vertically, to left/right)
        # Two cases:
        #   (a) Original: text block crosses the rect boundary (partially inside)
        #   (b) YOLO-specific: text block is fully inside the rect but occupies
        #       the left/right column while the figure is in the other column
        if v_overlap >= rect_h * 0.28 and bw > 50:
            block_mid_x = (bx0 + bx1) / 2
            rect_mid_x = (rect.x0 + rect.x1) / 2

            # Case (a): text block straddles the rect boundary or is very
            # close to it (within 12pt — accounts for YOLO bbox jitter and
            # glyph overshoot at render time).
            # Left side: text block center is left of figure center,
            # and text right edge is near or past the figure left edge
            if block_mid_x < rect_mid_x and bx1 > rect.x0 - 12 and bx0 < rect.x0 + 12:
                body_blocks_left.append(b)
                continue
            # Right side
            if block_mid_x > rect_mid_x and bx0 < rect.x1 + 12 and bx1 > rect.x1 - 12:
                body_blocks_right.append(b)
                continue

            # Case (b): YOLO bbox spans both columns; text column is fully
            # inside the bbox but sits clearly to one side of center.
            # Requirements: multi-line body text, tall, and clearly in one
            # lateral half of the rect.  We use 52% (not 50%) to handle
            # slight centering offsets in dual-column layouts.
            if layer == "yolo_figure" and n_lines >= 3 and bh > rect_h * 0.25:
                # Block is entirely inside rect (or almost: allow 5pt tolerance
                # for blocks whose left edge is at the rect boundary)
                if bx0 >= rect.x0 - 5 and bx1 <= rect.x1 + 5:
                    # Left half: block's right edge is in the left 52% of rect
                    if bx1 < rect.x0 + rect_w * 0.52 and block_mid_x < rect_mid_x:
                        body_blocks_left.append(b)
                        continue
                    # Right half
                    if bx0 > rect.x0 + rect_w * 0.48 and block_mid_x > rect_mid_x:
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
        if trim_amount > 0 and trim_amount < rect_h * max_trim_frac:
            new_rect.y0 = max_body_bottom + 2
        elif -10 < trim_amount <= 0:
            # Body text is very close above — add gap to prevent pixel bleed
            new_rect.y0 = max_body_bottom + 5
    if body_blocks_bot:
        min_body_top = min(b["bbox"][1] for b in body_blocks_bot)
        trim_amount = new_rect.y1 - min_body_top
        if trim_amount > 0 and trim_amount < rect_h * max_trim_frac:
            new_rect.y1 = min_body_top - 2
        elif -10 < trim_amount <= 0:
            new_rect.y1 = min_body_top - 5
    if body_blocks_left:
        max_body_right = max(b["bbox"][2] for b in body_blocks_left)
        trim_amount = max_body_right - new_rect.x0
        if trim_amount > 0 and trim_amount < rect_w * max_trim_frac:
            # Body text right edge is INSIDE the rect — trim rect left edge
            # to just past the text
            new_rect.x0 = max_body_right + 2
        elif -12 < trim_amount <= 0:
            # Body text right edge is just OUTSIDE the rect (within 12pt) —
            # push rect left edge rightward past the text to create a gap.
            # Never move x0 leftward (that would expand the rect).
            new_x0 = max_body_right + 5
            if new_x0 > new_rect.x0:
                new_rect.x0 = new_x0
    if body_blocks_right:
        min_body_left = min(b["bbox"][0] for b in body_blocks_right)
        trim_amount = new_rect.x1 - min_body_left
        if trim_amount > 0 and trim_amount < rect_w * max_trim_frac:
            new_rect.x1 = min_body_left - 2
        elif -12 < trim_amount <= 0:
            new_x1 = min_body_left - 5
            if new_x1 < new_rect.x1:
                new_rect.x1 = new_x1
    return new_rect


def _absorb_axis_labels(
    page, rect: fitz.Rect, caption: str = "",
    search_margin: float = 25.0,
    max_label_chars: int = 40,
) -> fitz.Rect:
    """Expand rect to include axis labels / tick marks just outside the rect.

    Chart axis labels (e.g. "Score (%)", "0%", "10%", "% of computers") are
    text blocks that fall just outside the vector drawing cluster.  Without
    absorbing them the figure crop misses the axis labels.

    Criteria for a label block:
      - Short text (≤ max_label_chars characters)
      - Within search_margin points of the rect boundary
      - NOT a figure/table caption
    """
    blocks = page.get_text("dict")["blocks"]
    new_rect = fitz.Rect(rect)

    for b in blocks:
        if b["type"] != 0:
            continue
        bx0, by0, bx1, by1 = b["bbox"]
        text = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()

        # Skip captions
        if re.match(r"(?:Figure|Fig\.?|Table)\s+\d+", text, re.IGNORECASE):
            continue
        # Skip long text (body paragraphs)
        if len(text) > max_label_chars:
            continue
        # Skip if no text
        if not text:
            continue

        # Check if this block is just outside the current rect
        b_rect = fitz.Rect(bx0, by0, bx1, by1)

        # Already inside? Skip (already captured)
        if rect.contains(b_rect):
            continue

        # Check proximity: the block must be close to the rect boundary
        # and overlap significantly in one dimension
        gap_left = rect.x0 - bx1    # positive = block is to the left
        gap_right = bx0 - rect.x1   # positive = block is to the right
        gap_top = rect.y0 - by1     # positive = block is above
        gap_bottom = by0 - rect.y1  # positive = block is below

        # Vertical overlap (for left/right labels)
        v_overlap = min(by1, rect.y1) - max(by0, rect.y0)
        # Horizontal overlap (for top/bottom labels)
        h_overlap = min(bx1, rect.x1) - max(bx0, rect.x0)

        absorbed = False

        # Left axis labels (y-axis labels, tick marks)
        if 0 < gap_left < search_margin and v_overlap > 0:
            new_rect.x0 = min(new_rect.x0, bx0 - 2)
            absorbed = True
        # Right axis labels
        elif 0 < gap_right < search_margin and v_overlap > 0:
            new_rect.x1 = max(new_rect.x1, bx1 + 2)
            absorbed = True
        # Bottom axis labels (x-axis)
        elif 0 < gap_bottom < search_margin and h_overlap > 0:
            new_rect.y1 = max(new_rect.y1, by1 + 2)
            absorbed = True
        # Top labels (title above chart)
        elif 0 < gap_top < search_margin and h_overlap > 0:
            new_rect.y0 = min(new_rect.y0, by0 - 2)
            absorbed = True

    # Clamp to page
    new_rect = new_rect & page.rect
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
# Layer 4: Caption-guided figure detection (fallback for missed figures)
# ---------------------------------------------------------------------------

def _caption_guided_figures(doc, existing_items: list[dict]) -> list[dict]:
    """Detect figures by finding 'Figure N' captions and inferring figure bbox.

    Many PDFs (especially LaTeX-generated) embed figures as form XObjects or
    inline font-rendered graphics that Layers 1-3 miss entirely.  This layer
    scans for caption text blocks, then locates the non-text region adjacent to
    each caption as the figure.

    Only adds figures whose page+location is not already covered by existing
    detections (avoids duplicates with layers 1-3).
    """
    # Build a set of (page, approximate_y) already detected
    covered: list[tuple[int, fitz.Rect]] = [
        (it["page"], it["rect"]) for it in existing_items if it["layer"] != "table"
    ]

    new_items = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")["blocks"]
        pw, ph = page.rect.width, page.rect.height

        # Find all caption blocks on this page
        caption_blocks = []
        for b in blocks:
            if b["type"] != 0:
                continue
            text = " ".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
            # Strict caption: "Figure N:" or "Fig. N:" or "Figure N." followed by
            # description text.  Reject body sentences like "Figure 2 shows..."
            m = re.match(
                r"(?:Figure|Fig\.?)\s+(\d+)\s*[:.—–—–]",
                text, re.IGNORECASE,
            )
            if not m:
                # Also accept short standalone "Figure N" (no colon but very short)
                m = re.match(r"(?:Figure|Fig\.?)\s+(\d+)\s*$", text, re.IGNORECASE)
            if m:
                caption_blocks.append({
                    "text": text[:800],
                    "bbox": b["bbox"],
                    "fig_num": int(m.group(1)),
                })

        if not caption_blocks:
            continue

        # Build a list of all text block bboxes on this page (for gap finding)
        text_rects = []
        for b in blocks:
            if b["type"] != 0:
                continue
            bx0, by0, bx1, by1 = b["bbox"]
            if bx1 - bx0 < 10 or by1 - by0 < 5:
                continue
            text_rects.append(fitz.Rect(bx0, by0, bx1, by1))

        for cap in caption_blocks:
            cx0, cy0, cx1, cy1 = cap["bbox"]
            cap_rect = fitz.Rect(cx0, cy0, cx1, cy1)

            # Skip if an existing detection already covers this area
            # (but only if the existing detection is wide enough — a small
            # composite covering 1/4 of a full-width figure is NOT coverage)
            already_covered = False
            cap_width = cx1 - cx0  # caption width approximates figure width
            for (ep, er) in covered:
                if ep != page_num:
                    continue
                # Check if existing rect is near the caption
                near_caption = (abs(cy0 - er.y1) < 40 or abs(er.y0 - cy1) < 40 or
                                _rect_overlap_frac(cap_rect, er) > 0.3)
                if not near_caption:
                    continue
                # Also check if existing rect covers a reasonable width
                # (at least 60% of caption width → likely full figure)
                er_width = er.x1 - er.x0
                if er_width > cap_width * 0.6:
                    already_covered = True
                    break
            if already_covered:
                continue

            # Infer figure rect: the non-text vertical gap above (or below)
            # the caption, bounded by the column width
            #
            # Strategy: caption is usually below the figure.
            # Find the largest text-free vertical span above the caption,
            # bounded horizontally by the caption's column.

            # Determine column bounds (single or dual column)
            cap_mid_x = (cx0 + cx1) / 2
            if pw > 500:  # likely A4/letter
                # Guess column: left half or right half
                if cap_mid_x < pw * 0.52:
                    col_x0, col_x1 = pw * 0.04, pw * 0.49
                elif cap_mid_x > pw * 0.48:
                    col_x0, col_x1 = pw * 0.51, pw * 0.96
                else:
                    col_x0, col_x1 = pw * 0.04, pw * 0.96
            else:
                col_x0, col_x1 = pw * 0.04, pw * 0.96

            # Widen if caption itself is wider
            col_x0 = min(col_x0, cx0 - 5)
            col_x1 = max(col_x1, cx1 + 5)

            # Search ABOVE the caption for figure content
            fig_top = _find_figure_top_above_caption(
                cy0, col_x0, col_x1, text_rects, cap_rect, page_num, ph
            )
            fig_bottom = cy0 - 2  # just above caption

            fig_h = fig_bottom - fig_top
            if fig_h < 40:  # too small
                # Try BELOW the caption instead
                fig_top_below = cy1 + 2
                fig_bottom_below = _find_figure_bottom_below_caption(
                    cy1, col_x0, col_x1, text_rects, cap_rect, page_num, ph
                )
                fig_h_below = fig_bottom_below - fig_top_below
                if fig_h_below > fig_h and fig_h_below >= 40:
                    fig_top = fig_top_below
                    fig_bottom = fig_bottom_below
                    fig_h = fig_h_below

            if fig_h < 40:
                continue  # No usable figure region found

            fig_rect = fitz.Rect(col_x0, fig_top, col_x1, fig_bottom)

            # Sanity: don't accept near-full-page figures
            fig_area = (fig_rect.x1 - fig_rect.x0) * (fig_rect.y1 - fig_rect.y0)
            page_area = pw * ph
            if page_area > 0 and fig_area / page_area > 0.60:
                continue

            new_items.append({
                "layer": "caption_guided",
                "page": page_num,
                "rect": fig_rect,
                "caption": cap["text"],
                "fig_num": cap["fig_num"],
            })
            covered.append((page_num, fig_rect))

    logger.info("Caption-guided detection: %d new figures", len(new_items))
    return new_items


def _find_figure_top_above_caption(
    caption_y0: float, col_x0: float, col_x1: float,
    text_rects: list[fitz.Rect], cap_rect: fitz.Rect,
    page_num: int, page_height: float,
) -> float:
    """Find the top boundary of a figure region above the caption.

    Scans upward from the caption, looking for the first BODY text block
    (wide enough to be a paragraph, not an in-figure label) that is
    horizontally within the column bounds — that text's bottom edge
    is the figure's top boundary.
    """
    col_w = col_x1 - col_x0
    # Minimum width for a text block to count as a body paragraph boundary
    # (narrow blocks like "1 2 3" or "LLMs" are likely in-figure labels)
    min_body_width = col_w * 0.35

    # Collect body text blocks above caption, within the column
    above_texts = []
    for tr in text_rects:
        if tr.y1 > caption_y0 - 2:
            continue  # below or at caption level
        # Must overlap the column horizontally
        h_overlap = min(tr.x1, col_x1) - max(tr.x0, col_x0)
        if h_overlap < col_w * 0.15:
            continue
        # Skip the caption itself
        if _rect_iou(tr, cap_rect) > 0.5:
            continue
        # Skip narrow blocks (likely in-figure labels, not body text)
        block_width = tr.x1 - tr.x0
        if block_width < min_body_width:
            continue
        above_texts.append(tr)

    if above_texts:
        # Find the text block closest to (but above) the caption
        above_texts.sort(key=lambda r: r.y1, reverse=True)
        return above_texts[0].y1 + 2  # just below that text block
    else:
        # No text above in this column — use top margin
        return max(40, page_height * 0.05)


def _find_figure_bottom_below_caption(
    caption_y1: float, col_x0: float, col_x1: float,
    text_rects: list[fitz.Rect], cap_rect: fitz.Rect,
    page_num: int, page_height: float,
) -> float:
    """Find the bottom boundary of a figure region below the caption."""
    col_w = col_x1 - col_x0
    min_body_width = col_w * 0.35
    below_texts = []
    for tr in text_rects:
        if tr.y0 < caption_y1 + 2:
            continue
        h_overlap = min(tr.x1, col_x1) - max(tr.x0, col_x0)
        if h_overlap < col_w * 0.15:
            continue
        if _rect_iou(tr, cap_rect) > 0.5:
            continue
        # Skip narrow in-figure labels
        if tr.x1 - tr.x0 < min_body_width:
            continue
        below_texts.append(tr)

    if below_texts:
        below_texts.sort(key=lambda r: r.y0)
        return below_texts[0].y0 - 2
    else:
        return min(page_height - 40, page_height * 0.95)


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
    caption_guided = [it for it in figures if it["layer"] == "caption_guided"]
    yolo_figs = [it for it in figures if it["layer"] == "yolo_figure"]

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

    # Phase 2: standard dedup — sort by area (largest first, so the most
    # complete detection wins regardless of layer)
    ordered = yolo_figs + composites + surviving_rasters + vectors + caption_guided
    ordered.sort(key=lambda x: (
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
            layout_predictor: Deprecated (was for Surya). Ignored.
        """
        self.source_pack_dir = Path(source_pack_dir)
        self.figures_dir = self.source_pack_dir / "figures"
        self.tables_dir = self.source_pack_dir / "tables"
        self.screenshots_dir = self.source_pack_dir / "screenshots"

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

        # --- Detection phase: YOLO11 primary, heuristic fallback ---
        yolo_items = _detect_with_yolo(doc)
        use_yolo = len(yolo_items) > 0

        if use_yolo:
            yolo_figures = [it for it in yolo_items if it["layer"] != "table"]
            yolo_tables_raw = [it for it in yolo_items if it["layer"] == "table"]

            # Enrich YOLO table bboxes with structured data from find_tables()
            enriched_tables = _enrich_yolo_tables_with_structure(doc, yolo_tables_raw)

            all_items = yolo_figures + enriched_tables

            logger.info(
                "YOLO path: %d figures, %d tables",
                len(yolo_figures), len(enriched_tables),
            )
        else:
            logger.info("YOLO unavailable, using heuristic extraction")
            # Fallback: original 4-layer heuristic
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

            # Layer 4: Caption-guided detection — fills gaps missed by L1-L3
            caption_guided = _caption_guided_figures(doc, all_items)
            if caption_guided:
                all_items.extend(caption_guided)

        # Deduplicate
        deduped = _deduplicate(all_items)

        logger.info(
            "After dedup: %d items (yolo=%d, r=%d, c=%d, v=%d, cg=%d, t=%d)",
            len(deduped),
            sum(1 for x in deduped if x["layer"] == "yolo_figure"),
            sum(1 for x in deduped if x["layer"] == "raster"),
            sum(1 for x in deduped if x["layer"] == "composite"),
            sum(1 for x in deduped if x["layer"] == "vector"),
            sum(1 for x in deduped if x["layer"] == "caption_guided"),
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

            # --- Figure handling (raster / vector / composite / caption_guided) ---

            # Skip near-full-page images (likely page screenshots, not figures)
            fig_area = (rect.x1 - rect.x0) * (rect.y1 - rect.y0)
            page_area = page.rect.width * page.rect.height
            if page_area > 0 and fig_area / page_area > 0.70:
                logger.debug(
                    "Skipping near-full-page figure on p%d (%.0f%% of page)",
                    page_1indexed, fig_area / page_area * 100,
                )
                continue

            # Caption: use pre-found caption for caption_guided, else search
            if layer == "caption_guided":
                caption = item.get("caption", "")
            else:
                # Find caption on the UNPADDED rect first (before padding
                # moves the boundary past the caption text block)
                caption = _find_figure_caption(page, rect)

            if layer in ("vector", "composite"):
                # Minimal padding — avoid capturing adjacent body text
                pad_x = 8.0
                pad_top = 5.0
                pad_bot = 12.0
                rect = fitz.Rect(
                    max(0, rect.x0 - pad_x), max(0, rect.y0 - pad_top),
                    min(page.rect.x1, rect.x1 + pad_x),
                    min(page.rect.y1, rect.y1 + pad_bot),
                )

                # Absorb axis labels / tick marks that fall just outside
                # the vector cluster but belong to the figure (short text
                # blocks within ~25pt of the rect boundary)
                rect = _absorb_axis_labels(page, rect, caption)

            # YOLO figures: already well-bounded by ML, just absorb axis labels
            if layer == "yolo_figure":
                rect = _absorb_axis_labels(page, rect, caption)

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
            if layer in ("vector", "composite", "caption_guided", "yolo_figure"):
                rect = _trim_body_text(page, rect, caption, layer=layer)

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
            elif layer == "yolo_figure":
                label = f"fig{fig_idx}"
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
