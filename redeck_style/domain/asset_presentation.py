"""Explicit source presentation policy, independent of theme and density."""

ASSET_MODES = ("auto", "preserve", "table", "chart")


def validate_asset_policy(default_mode, overrides, assets):
    if default_mode not in ASSET_MODES:
        raise ValueError(f"Unsupported asset mode: {default_mode}")
    if not isinstance(overrides, dict):
        raise ValueError("Asset policy must be an object mapping asset IDs to modes")
    for asset_id, mode in overrides.items():
        if asset_id not in assets:
            raise ValueError(f"Unknown asset ID in asset policy: {asset_id}")
        if mode not in ASSET_MODES:
            raise ValueError(f"Unsupported asset mode for {asset_id}: {mode}")


def asset_presentation(slide, assets, default_mode="auto", overrides=None):
    overrides = overrides or {}
    asset_id = slide.get("assigned_figure_id") or ""
    asset = assets.get(asset_id)
    requested = overrides.get(asset_id, default_mode)
    mode = requested
    if not asset:
        mode = "none"
    elif asset.get("kind") != "table":
        if requested not in {"auto", "preserve"}:
            raise ValueError(f"Asset {asset_id}: {requested} requires an extracted table, not a figure; use preserve")
        mode = "preserve"
    elif requested in {"table", "chart"} and not asset.get("rows"):
        raise ValueError(f"Asset {asset_id}: {requested} requires extracted source rows; use preserve with a valid image")
    return {"asset_id": asset_id, "source_kind": asset.get("kind", "") if asset else "",
            "requested_mode": requested, "mode": mode,
            "policy_source": "asset-override" if asset_id in overrides else "default"}
