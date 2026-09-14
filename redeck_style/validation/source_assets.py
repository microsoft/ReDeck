"""Inspect assigned figure files before spending a generation request."""

from pathlib import Path

from PIL import Image

from redeck_style.domain.constraints import FRAGMENT_ASPECT_RATIO, FRAGMENT_LONG_EDGE, FRAGMENT_SHORT_EDGE


def inspect_source_figure(asset):
    result = {"path": asset.get("path", ""), "issues": []}
    path = Path(result["path"])
    if not result["path"] or not path.is_file():
        result["issues"].append("unavailable-image")
        return result
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except (OSError, ValueError, Image.DecompressionBombError):
        result["issues"].append("unreadable-image")
        return result
    result.update(intrinsic_width=width, intrinsic_height=height)
    short_edge, long_edge = min(width, height), max(width, height)
    if short_edge <= FRAGMENT_SHORT_EDGE and long_edge >= FRAGMENT_LONG_EDGE and long_edge / short_edge >= FRAGMENT_ASPECT_RATIO:
        result["issues"].append("suspected-extraction-fragment")
    declared = (int(asset.get("width") or 0), int(asset.get("height") or 0))
    if all(declared) and declared != (width, height):
        result["issues"].append("intrinsic-size-metadata-mismatch")
    return result


def audit_source_assets(slides, assets, presentations=None):
    results = []
    inspected = {}
    for slide in slides:
        asset_id = slide.get("assigned_figure_id")
        asset = assets.get(asset_id)
        mode = (presentations or {}).get(slide["slide_id"], {}).get("mode")
        if not asset or (asset.get("kind") != "figure" and mode != "preserve"):
            continue
        if asset_id not in inspected:
            inspected[asset_id] = inspect_source_figure(asset)
        inspection = inspected[asset_id]
        results.append({"slide_id": slide["slide_id"], "asset_id": asset_id, **inspection,
                        "status": "needs_source_review" if inspection["issues"] else "ready"})
    return results
