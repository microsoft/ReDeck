"""Rendered typography contracts anchored to the immutable original slide."""

import math


ROLE_FLOORS = {"title": 32, "heading": 24, "sidebar_heading": 24, "body": 16,
               "label": 12, "note": 11, "citation": 10, "unknown": 16,
               "table_cell": 12, "supporting_copy": 12, "panel_heading": 14, "svg_label": 10}
REVIEW_RATIO = 0.88
SCALE_TOLERANCE = 0.02


def _texts(validity):
    return {item["selector"]: item for item in validity.get("text_geometry", [])}


def _role(item):
    role = item.get("typography", {}).get("role", "unknown")
    return role if role in ROLE_FLOORS else "unknown"


def _axes(item):
    return {axis: float(item.get("font_px", 0)) * float(item.get("font_scale", {}).get(axis, 1))
            for axis in ("x", "y")}


def typography_constraints(original, current=None):
    current_texts = _texts(current or original)
    constraints = []
    for selector, item in _texts(original).items():
        role = _role(item)
        axes = _axes(item)
        if not all(math.isfinite(value) and value > 0 for value in axes.values()):
            continue
        rendered = current_texts.get(selector, item)
        geometry = rendered.get("typography", {})
        available = geometry.get("available_width_px", 0)
        word_width = geometry.get("max_word_width_px", 0)
        fit = rendered["font_px"] * available / word_width if available > 0 and word_width > 0 else None
        floor = min(ROLE_FLOORS[role], min(axes.values()))
        scale = min(float(rendered.get("font_scale", {}).get(axis, 1)) for axis in ("x", "y"))
        constraints.append({"selector": selector, "role": role, "original_px": item["font_px"],
                            "minimum_effective_px": floor,
                            "minimum_font_size_px_at_current_scale": math.ceil(floor / scale * 100) / 100 if scale > 0 else None,
                            "current_effective_px": _axes(rendered),
                            "current_px": rendered["font_px"], "available_width_px": available,
                            "max_word_width_px": word_width,
                            "proportional_fit_hint_px": round(fit, 2) if fit else None})
    return constraints


def typography_audit(original, candidate):
    originals, candidates = _texts(original), _texts(candidate)
    violations, changes, warnings = [], [], []
    constraints = {item["selector"]: item for item in typography_constraints(original)}
    label_origins = {}
    for selector, item in originals.items():
        owner = item.get("layout_parent_selector") or selector
        previous = label_origins.get(owner)
        if previous is None or constraints.get(selector, {}).get("minimum_effective_px", 0) > constraints.get(previous, {}).get("minimum_effective_px", 0):
            label_origins[owner] = selector
    matched = set()
    viewport_review = False
    for selector, after in candidates.items():
        origin = selector if selector in originals else label_origins.get(after.get("layout_parent_selector") or selector)
        before = originals.get(origin)
        if before is None:
            continue
        matched.add(selector)
        old_axes, new_axes = _axes(before), _axes(after)
        if origin not in constraints or not all(math.isfinite(value) and value > 0 for value in new_axes.values()):
            violations.append({"selector": selector, "reason": "Invalid rendered typography measurement"})
            continue
        contract = constraints[origin]
        floor = contract["minimum_effective_px"]
        reasons = []
        if any(value < floor - 1e-4 for value in new_axes.values()):
            reasons.append(f"Effective type below original-role floor {floor:g}px ({contract['role']})")
        old_scale, new_scale = before.get("font_scale", {}), after.get("font_scale", {})
        if any(new_scale.get(axis, 1) < old_scale.get(axis, 1) * (1 - SCALE_TOLERANCE) - 1e-6 for axis in ("x", "y")):
            ratios = {axis: new_scale.get(axis, 1) / old_scale.get(axis, 1) for axis in ("x", "y")}
            viewport_only = (before.get("viewport_only_scaling") and after.get("viewport_only_scaling")
                             and abs(ratios["x"] / ratios["y"] - 1) <= SCALE_TOLERANCE)
            if viewport_only:
                viewport_review = True
            else:
                reasons.append("New transform/zoom or non-uniform compression; use font-size and reflow instead")
        old_tracking = before.get("typography", {}).get("tracking_px", 0) / before["font_px"]
        new_tracking = after.get("typography", {}).get("tracking_px", 0) / after["font_px"]
        if new_tracking < min(-0.06, old_tracking) - 0.005:
            reasons.append("New excessive negative tracking compresses letterforms")
        entry = {"selector": selector, "original_selector": origin, "role": contract["role"], "before_px": before["font_px"],
                 "after_px": after["font_px"], "minimum_effective_px": floor,
                 "before_effective_px": old_axes, "after_effective_px": new_axes}
        if reasons:
            violations.append({**entry, "reason": "; ".join(reasons)})
        if any(abs(new_axes[axis] - old_axes[axis]) > 0.05 for axis in old_axes):
            changes.append(entry)
            if any(new_axes[axis] < old_axes[axis] * REVIEW_RATIO - 1e-6 for axis in old_axes):
                warnings.append({"selector": selector, "reason": "Substantial size reduction needs role/hierarchy review"})
    for selector, item in candidates.items():
        if selector not in matched and min(_axes(item).values()) < ROLE_FLOORS["unknown"]:
            violations.append({"selector": selector, "reason": "New unmatched text below conservative 16px floor"})
    body = [item for item in originals.values() if _role(item) in {"body", "unknown"}]
    reduced_body = [item for item in body if item["selector"] in candidates
                    and candidates[item["selector"]]["font_px"] < item["font_px"] * 0.95]
    if len(body) >= 2 and len(reduced_body) / len(body) >= 0.5:
        warnings.append({"reason": "Most body targets shrink; reject page-wide force fitting or loss of reading comfort"})
    if viewport_review:
        warnings.append({"reason": "SVG viewport resized uniformly; verify effective type, complete labels and diagram associations"})
    return {"violations": violations, "changes": changes, "warnings": warnings,
            "review_required": bool(warnings)}


def typography_policy_prompt():
    floors = ", ".join(f"{role}={size}px" for role, size in ROLE_FLOORS.items())
    return (
        "Typography policy: local font-size reduction is allowed, including reductions greater than 12%, "
        "when the ORIGINAL semantic role remains readable and the hierarchy becomes coherent. "
        f"1280x720 effective-size floors: {floors}. An originally smaller target may stay unchanged, not shrink further. "
        "Table cells and supporting copy in bounded panels have distinct ORIGINAL roles: modest local font-size reduction "
        "toward their floors is allowed before collapsing padding or changing the grid topology. These are lower limits, not targets. "
        "Layout-only SVG tspan lines inherit their original label's role and effective-size baseline. "
        "Floors are SCREEN pixels, not SVG user units: use minimum_font_size_px_at_current_scale for declarations. "
        "A 12-unit SVG font can render below 10px. Recalculate this limit when the SVG viewport changes; "
        "read the actual effective-size measurements before choosing a declaration. "
        "Roles and floors are frozen from ORIGINAL, never inferred from candidate relabeling. Unknown roles require conservative visual review. "
        "CSS maximum/median size ratios are audit signals, NOT hard preservation requirements. "
        "Large reductions and widespread body shrinking require explicit typography and composition approval. "
        "Do not use CSS transform/zoom, non-uniform scaling, excessive negative tracking, invisible text or page-wide shrinking to force fit. "
        "Uniform SVG viewport reflow is allowed only with all effective-size floors satisfied and explicit typography/composition approval. "
        "For oversized secondary headings first try font-size, proportional tracking, line-height and padding; "
        "then reallocate coupled tracks if the readable size cannot fit. Fit hints assume proportional tracking and are NOT proof of fit; render and inspect. "
        "Do not extend a background patch behind overflowing type instead of fixing its typography and containing region."
    )
