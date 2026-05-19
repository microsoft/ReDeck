"""Image operations - base64 encoding, resizing, PNG handling."""

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image


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
