"""SVG-specific helper functions extracted from AgentRepair.

Pure-logic utilities for SVG text measurement, canvas signature,
text identity, and overflow diagnostics.
"""

import re
import xml.etree.ElementTree as ET


def svg_local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def svg_visible_texts(svg: str) -> list[str]:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return []
    texts: list[str] = []
    for node in root.iter():
        if svg_local_tag(node.tag) != "text":
            continue
        label = re.sub(r"\s+", " ", "".join(node.itertext())).strip()
        if label:
            texts.append(label)
    return texts


def svg_text_identity(text: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", text.casefold())


def svg_canvas_signature(svg: str) -> tuple[str, str, str] | None:
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return None
    return (
        re.sub(r"\s+", " ", root.attrib.get("viewBox", "").strip()),
        root.attrib.get("width", "").strip(),
        root.attrib.get("height", "").strip(),
    )


def svg_text_width_estimate(text: str, font_size: float) -> float:
    """Approximate SVG text width well enough to catch clear local overflows."""
    width_em = 0.0
    for ch in text:
        if ch.isspace():
            width_em += 0.33
        elif ch in "-–—→←↔/\\|:.·":
            width_em += 0.35
        elif ch in "ilI1![](){}'`":
            width_em += 0.25
        elif ch in "mwMW@#%&":
            width_em += 0.82
        elif ord(ch) > 0x2E7F:
            width_em += 1.0
        elif ch.isupper():
            width_em += 0.62
        else:
            width_em += 0.54
    return width_em * font_size


def svg_attr_float(el: ET.Element, name: str, default: float | None = None) -> float | None:
    raw = el.attrib.get(name)
    if raw is None:
        return default
    match = re.match(r"\s*(-?\d+(?:\.\d+)?)", raw)
    if not match:
        return default
    return float(match.group(1))


def svg_tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def svg_text_fit_warning(svg: str) -> str | None:
    """Detect clear SVG text overflow against a sibling rect in the same group."""
    try:
        root = ET.fromstring(svg)
    except ET.ParseError:
        return None

    def iter_groups(el: ET.Element):
        if svg_tag(el) in {"svg", "g"}:
            yield el
        for child in list(el):
            yield from iter_groups(child)

    def text_lines(text_el: ET.Element) -> list[tuple[str, float, float, float, str]]:
        parent_font = svg_attr_float(text_el, "font-size", 14.0) or 14.0
        parent_x = svg_attr_float(text_el, "x", 0.0) or 0.0
        parent_y = svg_attr_float(text_el, "y", 0.0) or 0.0
        anchor = text_el.attrib.get("text-anchor", "start")
        tspans = [c for c in list(text_el) if svg_tag(c) == "tspan"]
        if tspans:
            lines = []
            for span in tspans:
                label = "".join(span.itertext()).strip()
                if not label:
                    continue
                lines.append((
                    label,
                    svg_attr_float(span, "x", parent_x) or parent_x,
                    svg_attr_float(span, "y", parent_y) or parent_y,
                    svg_attr_float(span, "font-size", parent_font) or parent_font,
                    span.attrib.get("text-anchor", anchor),
                ))
            return lines
        label = "".join(text_el.itertext()).strip()
        if not label:
            return []
        return [(label, parent_x, parent_y, parent_font, anchor)]

    for group in iter_groups(root):
        previous_rects: list[ET.Element] = []
        for child in list(group):
            tag = svg_tag(child)
            if tag == "rect":
                previous_rects.append(child)
                continue
            if tag != "text":
                continue
            for label, x, y, font_size, anchor in text_lines(child):
                candidates = []
                for rect in previous_rects:
                    rx = svg_attr_float(rect, "x", 0.0) or 0.0
                    ry = svg_attr_float(rect, "y", 0.0) or 0.0
                    rw = svg_attr_float(rect, "width")
                    rh = svg_attr_float(rect, "height")
                    if rw is None or rh is None:
                        continue
                    if rx - 1 <= x <= rx + rw + 1 and ry - font_size <= y <= ry + rh + font_size:
                        candidates.append((rx, ry, rw, rh))
                if not candidates:
                    continue
                rx, _ry, rw, _rh = min(candidates, key=lambda r: r[2] * r[3])
                est_width = svg_text_width_estimate(label, font_size)
                if anchor == "middle":
                    left, right = x - est_width / 2.0, x + est_width / 2.0
                elif anchor == "end":
                    left, right = x - est_width, x
                else:
                    left, right = x, x + est_width
                tolerance = max(2.0, font_size * 0.18)
                if left < rx - tolerance or right > rx + rw + tolerance:
                    return (
                        "SVG text likely overflows its containing rect: "
                        f"`{label}` estimated {est_width:.1f}px wide in a {rw:.1f}px rect. "
                        "Wrap compound labels with <tspan> lines, widen the shape, "
                        "or reduce font size without going below readable annotation size."
                    )
    return None


def format_svg_text_overflow_residual(spatial_state, issue_id: str) -> str:
    """Describe an external or inline SVG overflow with directional data."""
    svg_issue = next(
        (
            item for item in getattr(spatial_state, "svg_asset_issues", [])
            if item.get("id") == issue_id
        ),
        None,
    )
    if svg_issue is not None:
        overflow_parts = []
        for edge in ("top", "bottom", "left", "right"):
            amount = float(svg_issue.get(f"overflow_{edge}") or 0)
            if amount > 0:
                overflow_parts.append(f"{edge} {amount:g}px")
        direction = ", ".join(overflow_parts) or "past rect edge"
        return (
            "  • SVG_TEXT_OVERFLOW "
            f"{svg_issue.get('asset_name')}: "
            f"\"{svg_issue.get('label')}\" "
            f"({svg_issue.get('estimated_width')}px in "
            f"{svg_issue.get('available_width')}px rect; {direction})"
        )

    block = next(
        (
            item for item in getattr(spatial_state, "blocks", [])
            if item.block_id == issue_id and getattr(item, "is_svg_text", False)
        ),
        None,
    )
    if block is not None:
        label = " ".join(block.text_lines).strip() or issue_id
        x, y, width, height = block.bbox_px
        measurement_parts: list[str] = []
        normalized_label = re.sub(r"\s+", " ", label).strip().casefold()
        matching_metrics: list[tuple[float, dict, dict]] = []
        block_center = (x + width / 2.0, y + height / 2.0)
        for region in getattr(spatial_state, "svg_regions", []) or []:
            for metric in region.get("text_metrics", []) or []:
                metric_label = re.sub(
                    r"\s+", " ", str(metric.get("label") or ""),
                ).strip().casefold()
                if not metric_label or not (
                    metric_label == normalized_label
                    or metric_label in normalized_label
                    or normalized_label in metric_label
                ):
                    continue
                rendered_bbox = metric.get("label_bbox") or {}
                metric_center = (
                    float(rendered_bbox.get("x") or 0)
                    + float(rendered_bbox.get("width") or 0) / 2.0,
                    float(rendered_bbox.get("y") or 0)
                    + float(rendered_bbox.get("height") or 0) / 2.0,
                )
                distance = (
                    (metric_center[0] - block_center[0]) ** 2
                    + (metric_center[1] - block_center[1]) ** 2
                )
                matching_metrics.append((distance, region, metric))

        if matching_metrics:
            _, region, metric = min(matching_metrics, key=lambda item: item[0])
            view_box = region.get("view_box") or {}
            if view_box:
                measurement_parts.append(
                    "SVG viewBox "
                    f"({view_box.get('x')},{view_box.get('y')},"
                    f"{view_box.get('width')}x{view_box.get('height')})"
                )
            svg_bbox = metric.get("svg_bbox") or {}
            if svg_bbox:
                measurement_parts.append(
                    "label SVG bbox "
                    f"({svg_bbox.get('x')},{svg_bbox.get('y')},"
                    f"{svg_bbox.get('width')}x{svg_bbox.get('height')})"
                )
            edge_gaps = metric.get("viewbox_edge_gaps") or {}
            if edge_gaps:
                measurement_parts.append(
                    "viewBox edge gaps "
                    f"left={edge_gaps.get('left')}, top={edge_gaps.get('top')}, "
                    f"right={edge_gaps.get('right')}, bottom={edge_gaps.get('bottom')}"
                )
            nearest_rect = metric.get("nearest_rect") or {}
            rect_bbox = nearest_rect.get("bbox") or {}
            if nearest_rect and rect_bbox:
                measurement_parts.append(
                    "nearest rect bbox "
                    f"({rect_bbox.get('x')},{rect_bbox.get('y')},"
                    f"{rect_bbox.get('width')}x{rect_bbox.get('height')}), "
                    f"rendered gap={nearest_rect.get('distance_px')}px"
                )
            nearest_line = metric.get("nearest_line") or {}
            endpoints = nearest_line.get("endpoints") or {}
            if nearest_line and endpoints:
                measurement_parts.append(
                    "nearest line endpoints "
                    f"({endpoints.get('x1')},{endpoints.get('y1')})→"
                    f"({endpoints.get('x2')},{endpoints.get('y2')}), "
                    f"rendered gap={nearest_line.get('distance_px')}px"
                )

        base = (
            f"  • SVG_TEXT_OVERFLOW {issue_id}: \"{label}\"; "
            f"vertical {block.overflow_bottom_px}px, "
            f"horizontal {block.overflow_right_px}px; "
            f"bbox ({x},{y},{width}x{height})"
        )
        if measurement_parts:
            base += "; " + "; ".join(measurement_parts)
        return base
    return f"  • SVG_TEXT_OVERFLOW {issue_id}"


def extract_svg_text_overflow_findings(compact: str) -> str:
    """Return only deterministic inline/external SVG text-fit details."""
    lines = compact.splitlines()
    findings: list[str] = []
    i = 0
    markers = ("SVG TEXT OVERFLOW", "SVG ASSET TEXT OVERFLOW")
    while i < len(lines):
        line = lines[i]
        if not any(marker in line for marker in markers):
            i += 1
            continue
        findings.append(line)
        i += 1
        while i < len(lines):
            continuation = lines[i]
            stripped = continuation.strip()
            if not stripped:
                break
            if continuation.startswith(("❌ ", "⚠️ ", "📐")):
                break
            if stripped.startswith(("RELATION MAP", "SPACE MAP", "──")):
                break
            findings.append(continuation)
            i += 1
        continue
    return "\n".join(findings).strip()
