"""Image operations - base64 encoding, resizing, PNG handling."""

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image


def _pil_to_base64(img: Image.Image, max_size: int, fmt: str = "PNG") -> str:
    """Encode an in-memory image while preserving thin vector-rendered details."""
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        img = img.resize(
            (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    buffer = BytesIO()
    img.save(buffer, format=fmt)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def image_to_base64(image_path: str | Path, max_size: int = 1024) -> str:
    """Convert image to base64 data URL, optionally resizing."""
    img = Image.open(image_path)

    # Resize if larger than max_size
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    buffer = BytesIO()
    fmt = "PNG" if img.mode == "RGBA" else "JPEG"
    img.save(buffer, format=fmt)
    b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    mime = "image/png" if fmt == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def image_regions_to_base64(
    image_path: str | Path,
    regions: list[dict],
    viewport_size: tuple[int, int] = (1280, 720),
    max_size: int = 1920,
) -> list[str]:
    """Encode a full render, enlarged regions, and generic detail tile sheets.

    Region coordinates are expressed in the browser viewport coordinate system.
    This is intentionally content-agnostic: the caller decides which rendered
    regions deserve a closer VLM inspection.
    """
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        encoded = [_pil_to_base64(image.copy(), max_size=max_size)]
        scale_x = image.width / max(viewport_size[0], 1)
        scale_y = image.height / max(viewport_size[1], 1)

        for region in regions:
            x = float(region.get("x", 0))
            y = float(region.get("y", 0))
            width = float(region.get("width", 0))
            height = float(region.get("height", 0))
            if width <= 0 or height <= 0:
                continue
            padding = max(8.0, min(width, height) * 0.04)
            box = (
                max(0, int((x - padding) * scale_x)),
                max(0, int((y - padding) * scale_y)),
                min(image.width, int((x + width + padding) * scale_x)),
                min(image.height, int((y + height + padding) * scale_y)),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            crop = image.crop(box)
            # Small diagrams need enlargement for reliable path/marker inspection.
            if max(crop.size) < 1200:
                factor = min(3.0, 1200 / max(crop.size))
                crop = crop.resize(
                    (max(1, int(crop.width * factor)), max(1, int(crop.height * factor))),
                    Image.Resampling.LANCZOS,
                )
            encoded.append(_pil_to_base64(crop, max_size=max_size))

            # A 2x2 overlapping tile sheet exposes thin local geometry without
            # guessing which part of an arbitrary visual matters.
            tile_w = max(1, int(crop.width * 0.58))
            tile_h = max(1, int(crop.height * 0.58))
            tile_boxes = [
                (0, 0, tile_w, tile_h),
                (crop.width - tile_w, 0, crop.width, tile_h),
                (0, crop.height - tile_h, tile_w, crop.height),
                (crop.width - tile_w, crop.height - tile_h, crop.width, crop.height),
            ]
            cell_w, cell_h = 900, 600
            sheet = Image.new("RGB", (cell_w * 2, cell_h * 2), "white")
            for index, tile_box in enumerate(tile_boxes):
                tile = crop.crop(tile_box)
                scale = min(cell_w / tile.width, cell_h / tile.height)
                tile = tile.resize(
                    (max(1, int(tile.width * scale)), max(1, int(tile.height * scale))),
                    Image.Resampling.LANCZOS,
                )
                offset_x = (index % 2) * cell_w + (cell_w - tile.width) // 2
                offset_y = (index // 2) * cell_h + (cell_h - tile.height) // 2
                sheet.paste(tile, (offset_x, offset_y))
            encoded.append(_pil_to_base64(sheet, max_size=max_size))
        return encoded


def resize_image(
    input_path: str | Path,
    output_path: str | Path,
    max_size: int = 1920,
) -> None:
    """Resize image to fit within max_size, maintaining aspect ratio."""
    img = Image.open(input_path)
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    img.save(output_path)


def get_image_dimensions(image_path: str | Path) -> tuple[int, int]:
    """Get image dimensions (width, height)."""
    with Image.open(image_path) as img:
        return img.size


# ---------------------------------------------------------------------------
# PDF-specific image operations (require PyMuPDF)
# ---------------------------------------------------------------------------

def render_pdf_page(
    pdf_path: str | Path,
    page_num: int,
    output_path: str | Path,
    dpi: int = 200,
) -> str:
    """Render a single PDF page to PNG.

    Args:
        pdf_path: Path to PDF file.
        page_num: 0-indexed page number.
        output_path: Where to save the PNG.
        dpi: Resolution for rendering.

    Returns:
        The output path as string.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    page = doc[page_num]
    pix = page.get_pixmap(dpi=dpi)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out))
    doc.close()
    return str(out)


def crop_pdf_region(
    pdf_path: str | Path,
    page_num: int,
    bbox: tuple[float, float, float, float],
    output_path: str | Path,
    dpi: int = 300,
) -> str:
    """Crop and render a specific region of a PDF page.

    Args:
        pdf_path: Path to PDF file.
        page_num: 0-indexed page number.
        bbox: (x0, y0, x1, y1) in PDF points.
        output_path: Where to save the PNG.
        dpi: Resolution for rendering.

    Returns:
        The output path as string.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    page = doc[page_num]
    clip = fitz.Rect(*bbox)
    pix = page.get_pixmap(dpi=dpi, clip=clip)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out))
    doc.close()
    return str(out)


def extract_pdf_image(
    pdf_path: str | Path,
    xref: int,
    output_path: str | Path,
) -> tuple[str, int, int]:
    """Extract an embedded image from PDF by xref.

    Args:
        pdf_path: Path to PDF file.
        xref: Image cross-reference number.
        output_path: Where to save the image (extension will be adjusted).

    Returns:
        Tuple of (actual_output_path, width, height).
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    img_info = doc.extract_image(xref)
    doc.close()

    ext = img_info.get("ext", "png")
    img_bytes = img_info["image"]
    width = img_info.get("width", 0)
    height = img_info.get("height", 0)

    # Adjust extension
    out = Path(output_path)
    actual_path = out.with_suffix(f".{ext}")
    actual_path.parent.mkdir(parents=True, exist_ok=True)
    actual_path.write_bytes(img_bytes)

    return str(actual_path), width, height


def fit_image_in_bbox(
    img_width: int,
    img_height: int,
    bbox_width: int,
    bbox_height: int,
) -> tuple[int, int, int, int]:
    """Calculate aspect-ratio-preserving placement within a bounding box.

    All values in the same unit (EMU, px, etc.).

    Args:
        img_width: Original image width.
        img_height: Original image height.
        bbox_width: Available bounding box width.
        bbox_height: Available bounding box height.

    Returns:
        (left_offset, top_offset, fitted_width, fitted_height) for centered placement.
    """
    if img_width <= 0 or img_height <= 0:
        return (0, 0, bbox_width, bbox_height)

    aspect = img_width / img_height
    bbox_aspect = bbox_width / bbox_height

    if bbox_aspect > aspect:
        # Height-constrained
        fitted_h = bbox_height
        fitted_w = int(bbox_height * aspect)
    else:
        # Width-constrained
        fitted_w = bbox_width
        fitted_h = int(bbox_width / aspect)

    left_offset = (bbox_width - fitted_w) // 2
    top_offset = (bbox_height - fitted_h) // 2

    return (left_offset, top_offset, fitted_w, fitted_h)


def validate_image_file(path: str | Path) -> bool:
    """Check if a file is a valid, openable image."""
    try:
        with Image.open(str(path)) as img:
            img.verify()
        return True
    except Exception:
        return False
