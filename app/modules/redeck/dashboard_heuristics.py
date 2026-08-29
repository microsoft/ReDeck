"""Dashboard heuristic functions extracted from AgentRepair.

These are standalone versions of the 23 dashboard-related methods.
AgentRepair retains thin wrappers that delegate here.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_repair import AgentState, PlanStep

from .spatial_state import ContentBlock
from .repair_utils import dom_parent_path


def _agent_repair_cls():
    """Lazy import to avoid circular dependency."""
    from .agent_repair import AgentRepair
    return AgentRepair


def looks_like_table_dashboard_pressure(state: AgentState) -> bool:
    """Detect dense table/card dashboard pressure without visual thresholds."""
    return looks_like_table_dashboard_pressure_from(
        str(getattr(state, "current_code", "") or ""),
        set(getattr(state, "issue_types", set()) or set()),
    )


def looks_like_table_dashboard_pressure_from(
    code: str,
    issue_types: set[str],
) -> bool:
    """Detect dense table or repeated-card dashboard pressure."""
    pressure_issue_types = {
        "text_overflow",
        "overlap",
        "density_imbalance",
        "layout_inappropriate",
        "alignment_inconsistency",
        "text_visual_imbalance",
    }
    if not (issue_types & pressure_issue_types):
        return False
    code = str(code or "").lower()
    has_table = "<table" in code or _agent_repair_cls()._mentions_class_or_selector(code, "table-wrap")
    class_counts = Counter(
        token
        for class_value in re.findall(
            r"class\s*=\s*['\"]([^'\"]+)['\"]",
            code,
        )
        for token in class_value.split()
    )
    has_repeated_card_grid = (
        class_counts.get("grid-card", 0) >= 2
        or (
            class_counts.get("card", 0) >= 3
            and any(
                _agent_repair_cls()._mentions_class_or_selector(code, name)
                for name in ("metric-list", "score", "findings", "kpi")
            )
        )
    )
    has_dashboard_rail = any(
        _agent_repair_cls()._mentions_class_or_selector(code, name)
        for name in ("hero", "ranking", "summary", "summary-box", "side", "mini")
    )
    return (has_table or has_repeated_card_grid) and has_dashboard_rail


def dashboard_measured_spatial_state(
    state: AgentState,
    *,
    allow_previous_revision: bool = False,
):
    """Return geometry that is known to describe the current revision."""
    layout_revision = getattr(state, "layout_revision", 0)
    last_verify_revision = getattr(state, "last_verify_revision", -1)
    if (
        (
            last_verify_revision == layout_revision
            or (
                allow_previous_revision
                and last_verify_revision == layout_revision - 1
            )
        )
        and getattr(state, "_last_html_state", None) is not None
    ):
        return state._last_html_state
    if layout_revision == 0 or (
        allow_previous_revision and layout_revision == 1
    ):
        return getattr(state, "initial_spatial_state", None)
    return None


def dashboard_descendant_extent_measurements(spatial_state) -> list[dict]:
    """Measure real descendant extents for dashboard-like containers."""
    blocks = list(getattr(spatial_state, "blocks", []) or [])
    if not blocks:
        return []

    def label(block) -> str:
        classes = tuple(getattr(block, "css_classes", ()) or ())
        if classes:
            return "." + ".".join(classes)
        return str(getattr(block, "css_selector", "") or block.var_name)

    repeated_card_ids: set[int] = set()
    card_groups: dict[tuple[str, str, tuple[str, ...]], list] = {}
    for block in blocks:
        classes = tuple(sorted(
            str(name).lower()
            for name in tuple(getattr(block, "css_classes", ()) or ())
        ))
        if not classes or not any(
            term in class_name
            for class_name in classes
            for term in ("card", "tile", "panel")
        ):
            continue
        key = (dom_parent_path(str(getattr(block, "dom_path", "") or "")), block.var_name, classes)
        card_groups.setdefault(key, []).append(block)
    for group in card_groups.values():
        if len(group) >= 2:
            repeated_card_ids.update(id(block) for block in group)

    extent_terms = (
        "summary", "mini", "hero", "ranking", "table-wrap", "notes",
        "rail", "side", "dashboard", "overview", "top-band", "header",
    )
    measurements: list[dict] = []
    for container in blocks:
        if id(container) in repeated_card_ids:
            continue
        classes = tuple(getattr(container, "css_classes", ()) or ())
        role = " ".join(str(name).lower() for name in classes)
        if not role or not any(term in role for term in extent_terms):
            continue
        path = str(getattr(container, "dom_path", "") or "")
        if not path:
            continue
        prefix = f"{path}/"
        members = [
            block for block in blocks
            if block is not container
            and str(getattr(block, "dom_path", "") or "").startswith(prefix)
        ]
        if not members:
            continue
        x, y, width, height = container.bbox_px
        parent_right = x + width
        parent_bottom = y + height
        descendant_left = min(member.bbox_px[0] for member in members)
        descendant_top = min(member.bbox_px[1] for member in members)
        descendant_right = max(
            member.bbox_px[0] + member.bbox_px[2] for member in members
        )
        descendant_bottom = max(
            member.bbox_px[1] + member.bbox_px[3] for member in members
        )
        lowest = max(
            members,
            key=lambda member: member.bbox_px[1] + member.bbox_px[3],
        )
        descendant_classes = sorted({
            str(name).lower()
            for member in members
            for name in tuple(getattr(member, "css_classes", ()) or ())
            if str(name).strip()
        })
        measurements.append({
            "container": container,
            "label": label(container),
            "classes": tuple(str(name).lower() for name in classes),
            "parent_box": (x, y, parent_right, parent_bottom),
            "descendant_box": (
                descendant_left, descendant_top,
                descendant_right, descendant_bottom,
            ),
            "vertical_delta": descendant_bottom - parent_bottom,
            "horizontal_delta": descendant_right - parent_right,
            "descendant_classes": tuple(descendant_classes),
            "lowest_label": label(lowest),
            "lowest_box": lowest.bbox_px,
        })
    return measurements


def dashboard_descendant_plan_note(
    steps: list[PlanStep],
    state: AgentState,
    planning_context: str = "",
) -> str:
    """Challenge plans that freeze an upstream band on parent-box evidence."""
    if not looks_like_table_dashboard_pressure(state):
        return ""
    spatial_state = dashboard_measured_spatial_state(state)
    measurements = [
        item for item in dashboard_descendant_extent_measurements(spatial_state)
        if item["vertical_delta"] > 0
    ]
    if not measurements:
        return ""

    combined = " ".join([
        str(planning_context or ""),
        *(str(getattr(step, "text", "") or "") for step in steps),
        *(str(getattr(step, "expected_outcome", "") or "") for step in steps),
    ]).lower()
    freezes_upstream = any(
        marker in combined
        for marker in (
            "rather than the frame", "frame is not", "frame isn't",
            "top band unchanged", "top-band unchanged",
            "keep the top band", "keep header/top band",
            "header/top band remain unchanged", "freeze the top",
            "freeze the header", "current leftover", "leftover height",
        )
    )
    lower_only = (
        any(term in combined for term in ("bottom", "lower", "card", "metric"))
        and any(term in combined for term in ("shrink", "compress", "tighten", "reduce"))
        and not any(
            term in combined
            for term in (
                "descendant", "child stack", "summary-row", "kpi rhythm",
                "top-band rhythm", "upper spacing", "whole-slide allocation",
                "whole slide allocation", "line wrapping",
            )
        )
    )
    if not (freezes_upstream or lower_only):
        return ""

    shown = "; ".join(
        f"{item['label']} descendants extend {item['vertical_delta']:+d}px "
        f"past the parent (lowest: {item['lowest_label']})"
        for item in measurements[:3]
    )
    return (
        "DESCENDANT-AWARE PLAN CHECK: the measured upper/dashboard boxes do "
        f"not fully describe their occupied height: {shown}. Do not conclude "
        "that the frame or upper band is unrelated, or freeze the current body "
        "start, from parent heights alone. Compare the maximum rendered child "
        "edge across upstream siblings with the next region's start. If the plan "
        "reclaims upstream space, name the child padding, line boxes, wrapping, "
        "margins, or repeated rhythm that will actually retreat in the same "
        "coherent edit. This is advisory evidence; it does not require changing "
        "the upper band or reject a lower-only repair when the child extents show "
        "that lower pressure is genuinely isolated."
    )


def dashboard_parent_descendant_patch_warning(
    state: AgentState,
    edit_blob: str,
) -> str:
    """Explain why reducing a parent box may not reclaim rendered space."""
    if not looks_like_table_dashboard_pressure(state):
        return ""
    spatial_state = dashboard_measured_spatial_state(
        state,
        allow_previous_revision=True,
    )
    measurements = [
        item for item in dashboard_descendant_extent_measurements(spatial_state)
        if item["vertical_delta"] > 0
    ]
    if not measurements:
        return ""

    blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", str(edit_blob or ""), re.DOTALL)
    affected: list[tuple[dict, bool]] = []
    for item in measurements:
        parent_classes = set(item["classes"])
        parent_height_changed = False
        child_rhythm_changed = False
        for selector, declarations in blocks:
            selector_low = selector.lower()
            declarations_low = declarations.lower()
            selector_classes = set(re.findall(r"\.([a-z_][\w-]*)", selector_low))
            if parent_classes & selector_classes and re.search(
                r"(?:^|;)\s*(?:height|min-height|max-height|grid-template-rows)\s*:",
                declarations_low,
            ):
                parent_height_changed = True
            if set(item["descendant_classes"]) & selector_classes and re.search(
                r"(?:^|;)\s*(?:height|min-height|max-height|padding(?:-[\w-]+)?|"
                r"margin(?:-[\w-]+)?|gap|row-gap|font-size|line-height|width|"
                r"grid-template-rows)\s*:",
                declarations_low,
            ):
                child_rhythm_changed = True
        if parent_height_changed:
            affected.append((item, child_rhythm_changed))

    if not affected:
        return ""
    shown = "; ".join(
        f"{item['label']} parent bottom={item['parent_box'][3]}px, "
        f"descendants bottom={item['descendant_box'][3]}px "
        f"(lowest: {item['lowest_label']})"
        for item, _ in affected[:3]
    )
    if any(changed for _, changed in affected):
        guidance = (
            "This patch also changes some descendant rhythm, so the coupled "
            "hypothesis may be valid. Do not count the declared parent-height "
            "difference as reclaimed budget until the next verify shows the "
            "actual descendant edge retreating and the downstream region starting "
            "below it. If the first verify is an intact intermediate calibration, "
            "use the new child extent to revise the same hypothesis rather than "
            "rolling back solely because the parent boxes now intersect."
        )
    else:
        guidance = (
            "The patch changes the parent allocation without changing the measured "
            "descendant roles that create its occupied extent. A shorter parent "
            "alone cannot reclaim that space; it can only let the following region "
            "move upward into still-rendered children. Recalibrate the actual child "
            "stack in the same coherent cluster, or keep the parent allocation."
        )
    return (
        "\n\nDESCENDANT-AWARE SPACE CHECK: before this edit, "
        f"{shown}. {guidance} This is non-blocking causal feedback."
    )


def dashboard_repeated_owner_budget_warning(
    state: AgentState,
    css: str,
) -> str:
    """Challenge owner-height guesses that are derived from footer avoidance.

    The warning is deliberately advisory. A shorter card can be correct when
    coupled role calibration genuinely reduces its rendered demand; the point
    is to make the next verify test that demand instead of treating a border
    ending above sparse footer text as proof of fit.
    """
    if not looks_like_table_dashboard_pressure(state):
        return ""

    spatial_state = dashboard_measured_spatial_state(
        state,
        allow_previous_revision=True,
    )
    blocks = list(getattr(spatial_state, "blocks", []) or [])
    cards = [
        block for block in blocks
        if "grid-card" in {
            str(name).lower()
            for name in tuple(getattr(block, "css_classes", ()) or ())
        }
        and str(getattr(block, "dom_path", "") or "")
    ]
    if len(cards) < 2:
        return ""

    proposed_heights: list[float] = []
    css_blocks = re.findall(r"([^{}]+)\{([^{}]*)\}", str(css or ""), re.DOTALL)
    touched_classes: set[str] = set()
    for selector, declarations in css_blocks:
        selector_classes = {
            name.lower()
            for name in re.findall(r"\.([a-z_][\w-]*)", selector.lower())
        }
        touched_classes.update(selector_classes)
        if "grid-card" not in selector_classes:
            continue
        for match in re.finditer(
            r"(?:^|;)\s*height\s*:\s*([0-9]+(?:\.[0-9]+)?)px\b",
            declarations.lower(),
        ):
            proposed_heights.append(float(match.group(1)))
    if not proposed_heights:
        return ""
    proposed_height = proposed_heights[-1]

    existing_heights = sorted(float(card.bbox_px[3]) for card in cards)
    current_height = existing_heights[len(existing_heights) // 2]
    if proposed_height >= current_height:
        return ""

    descendant_classes: set[str] = set()
    demand_excesses: list[float] = []
    for card in cards:
        path = str(card.dom_path)
        prefix = f"{path}/"
        descendants = [
            block for block in blocks
            if block is not card
            and str(getattr(block, "dom_path", "") or "").startswith(prefix)
        ]
        descendant_bottoms = [
            float(block.bbox_px[1] + block.bbox_px[3])
            for block in descendants
        ]
        for block in descendants:
            descendant_classes.update(
                str(name).lower()
                for name in tuple(getattr(block, "css_classes", ()) or ())
            )
        for element in getattr(spatial_state, "off_canvas_elements", []) or []:
            dom_path = str(element.get("domPath") or "")
            if not dom_path.startswith(prefix):
                continue
            descendant_bottoms.append(
                float(element.get("y") or 0) + float(element.get("h") or 0)
            )
            descendant_classes.update(
                str(element.get("classes") or "").lower().split()
            )
        if not descendant_bottoms:
            continue
        proposed_bottom = float(card.bbox_px[1]) + proposed_height
        demand_excesses.append(max(descendant_bottoms) - proposed_bottom)

    positive_excesses = [value for value in demand_excesses if value > 0]
    if not positive_excesses:
        return ""

    footer_tops: list[float] = []
    for block in blocks:
        role_blob = " ".join((
            str(getattr(block, "css_selector", "") or ""),
            *(str(name) for name in tuple(getattr(block, "css_classes", ()) or ())),
        )).lower()
        if any(term in role_blob for term in ("footer", "source", "credit", "footnote")):
            footer_tops.append(float(block.bbox_px[1]))
    footer_context = (
        f"The measured footer/source content begins near y={min(footer_tops):.0f}px; "
        if footer_tops
        else "Use the measured footer/source text bounds; "
    )
    child_calibration = bool(descendant_classes & touched_classes)
    calibration_context = (
        "The patch also changes descendant roles, so this can still be a valid "
        "coupled hypothesis if their rendered edges retreat. "
        if child_calibration
        else (
            "The patch does not change the descendant roles currently creating "
            "that demand, so the shorter owner alone cannot make them fit. "
        )
    )
    max_excess = max(positive_excesses)
    return (
        "\n\nREPEATED OWNER DEMAND CHECK: before this edit, the repeated "
        f"card owner is about {current_height:.0f}px high; the proposed "
        f"{proposed_height:.0f}px owner would still leave rendered descendants "
        f"extending about {max_excess:.0f}px past its edge at current demand. "
        f"{calibration_context}{footer_context}protect those visible elements "
        "from overlap and clipping, but do not treat the entire full-width area "
        "above them as forbidden. Derive the final owner allocation from the "
        "post-edit role demand and whole-slide budget, then verify the actual "
        "descendant edge. This is non-blocking causal feedback, not a minimum "
        "height or rollback gate."
    )


def dashboard_terminal_support_patch_warning(
    state: AgentState,
    css: str,
) -> str:
    """Explain when a CSS patch has not implemented its claimed two zones.

    This is deliberately advisory. It checks implementation semantics, not
    whether a visual strategy should pass or fail.
    """
    if not looks_like_table_dashboard_pressure(state):
        return ""
    code = str(getattr(state, "current_code", "") or "")
    if not (
        _agent_repair_cls()._mentions_class_or_selector(code, "grid-card")
        and _agent_repair_cls()._mentions_class_or_selector(code, "findings")
        and _agent_repair_cls()._mentions_class_or_selector(css, "grid-card")
    ):
        return ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(code, "html.parser")
        direct_terminal_support = any(
            card.find(class_="findings", recursive=False) is not None
            and len(card.find_all(recursive=False)) >= 4
            for card in soup.select(".grid-card")
        )
    except Exception:
        direct_terminal_support = False
    if not direct_terminal_support:
        return ""

    compact_css = re.sub(r"\s+", "", str(css or "").lower())
    compact_code = re.sub(r"\s+", "", code.lower())
    grid_card_blocks = "\n".join(re.findall(
        r"[^{}]*\.grid-card[^{}]*\{([^{}]*)\}",
        compact_css,
    ))
    claims_internal_grid = (
        "display:grid" in grid_card_blocks
        or "grid-template-rows:" in grid_card_blocks
    )
    claims_vertical_flex_stack = (
        "display:flex" in grid_card_blocks
        and "flex-direction:column" in grid_card_blocks
    )
    all_grid_card_blocks = "\n".join(re.findall(
        r"[^{}]*\.grid-card[^{}]*\{([^{}]*)\}",
        compact_code,
    ))
    all_findings_blocks = "\n".join(re.findall(
        r"[^{}]*\.findings(?![\w-])[^{}]*\{([^{}]*)\}",
        compact_code,
    ))
    anchors_support = any(
        token in all_findings_blocks
        for token in (
            "position:absolute", "position:fixed", "position:sticky",
        )
    )
    reserves_support = (
        "padding-bottom:" in all_grid_card_blocks
        or "grid-template-areas:" in all_grid_card_blocks
    )

    warnings: list[str] = []
    if claims_internal_grid and not (anchors_support and reserves_support):
        warnings.append(
            "TWO-ZONE IMPLEMENTATION CHECK: the current cards still have "
            "several unwrapped upper-role children followed by a direct "
            "terminal support child. Giving those direct children generic "
            "grid rows does not by itself create one upper zone plus one "
            "reserved support zone. If that is your intended strategy, make "
            "the allocation real. The existing terminal child can be anchored "
            "with genuine in-card reservation; add an upper wrapper only when "
            "the chosen reading path actually needs that semantic group. The patch remains "
            "applied; this is implementation feedback, not a rollback gate."
        )
    if claims_vertical_flex_stack and not (anchors_support and reserves_support):
        warnings.append(
            "TERMINAL SUPPORT ALLOCATION CHECK: the current cards still "
            "render several unwrapped upper-role children and the terminal "
            "support branch as one ordinary vertical flex stack. Giving an "
            "upper child `flex:1` or `min-height:0` does not reserve a "
            "separate terminal support zone when its descendants still "
            "consume or paint into that space. If reserve-and-anchor is the "
            "intended strategy, anchor the existing terminal child with real "
            "in-card reservation; introduce an upper wrapper only when the "
            "upper roles genuinely need regrouping. The "
            "patch remains applied; this is implementation feedback, not a "
            "rollback gate."
        )

    changes_peer_grid_to_multiple_rows = bool(re.search(
        r"\.bottom[^{}]*\{[^{}]*(?:grid-template-rows:|grid-template-columns:repeat\(2)",
        compact_css,
    ))
    if changes_peer_grid_to_multiple_rows:
        warnings.append(
            "MULTI-ROW PEER CAPACITY CHECK: this patch gives each complete "
            "peer a shorter row while retaining its identity, focal value, "
            "detail, and terminal support roles. Extra width may reduce "
            "wrapping, but it is not evidence of extra vertical capacity. "
            "Compare one peer's full rendered demand with its proposed row "
            "allocation before treating this topology as the stronger fit."
        )

    return "\n\n" + "\n\n".join(warnings) if warnings else ""


def dashboard_plan_implementation_warning(
    state: AgentState,
    *,
    action_text: str = "",
    cluster_complete: bool = True,
) -> str:
    """Flag when the active plan's support-allocation claim is not in code.

    This is advisory plan-execution feedback, not a layout rule. It only
    fires when the active plan explicitly chose a reserved/anchored support
    strategy and the edited DOM/CSS still represents one ordinary stack.
    """
    if not looks_like_table_dashboard_pressure(state):
        return ""

    open_steps = [
        step for step in getattr(state, "plan_steps", [])
        if getattr(step, "status", "pending") not in {"done", "skipped"}
    ]
    in_progress = [
        step for step in open_steps
        if getattr(step, "status", "pending") == "in_progress"
    ]
    active_steps = in_progress or open_steps[:1]
    plan_text = " ".join([
        str(action_text or ""),
        *(
            " ".join((
                str(getattr(step, "text", "") or ""),
                str(getattr(step, "expected_outcome", "") or ""),
                str(getattr(step, "verify_criterion", "") or ""),
            ))
            for step in active_steps
        ),
    ]).lower()
    support_terms = (
        "support", "finding", "takeaway", "terminal", "lower branch",
    )
    targets_terminal_support = (
        any(term in plan_text for term in support_terms)
        and any(
            term in plan_text
            for term in (
                "card", "comparison", "peer", "repeated", "profile",
            )
        )
    )
    chose_reserved_support = (
        targets_terminal_support
        and (
            any(
                term in plan_text
                for term in (
                    "anchor", "two-zone", "two zone", "support zone",
                    "support track", "terminal zone", "lower track",
                )
            )
            or bool(re.search(
                r"\breserv(?:e|ed|ing|ation)\s+(?:a\s+)?"
                r"(?:real\s+|genuine\s+|explicit\s+)?"
                r"(?:(?:in-card|internal|terminal|bottom|lower)\s+)?"
                r"(?:space|area|region|zone|track)",
                plan_text,
            ))
        )
    )
    chose_role_calibration = _agent_repair_cls()._names_role_demand_calibration(plan_text)
    action_low = str(action_text or "").lower()
    action_promises_copy_calibration = (
        any(
            term in action_low
            for term in (
                "support copy", "support-copy", "explanatory copy",
                "metric note", "metric-note", "finding", "takeaway",
            )
        )
        and any(
            term in action_low
            for term in (
                "compress", "shorten", "condense", "rewrite",
                "copy calibration", "wording",
            )
        )
    )
    chose_other_allocation = any(
        term in plan_text
        for term in (
            "upper wrapper", "support band", "shared band", "side rail",
            "side-rail", "internal split", "grid area", "grid-area",
            "two-column", "two column", "two-row", "two row", "2x2",
            "2×2", "regroup", "recompose", "detach", "content-sized",
        )
    ) or (
        any(term in plan_text for term in ("ordinary flow", "normal flow", "in-flow"))
        and any(term in plan_text for term in ("compress", "shorten", "condense"))
    ) or chose_role_calibration
    if not (chose_reserved_support or targets_terminal_support):
        return ""

    code = str(getattr(state, "current_code", "") or "")
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(code, "html.parser")
        support_role_terms = (
            "finding", "takeaway", "support", "insight",
            "conclusion", "recommendation",
        )
        upper_role_terms = (
            "upper", "main", "body", "content", "stack", "metrics",
        )
        support_classes: set[str] = set()
        upper_wrapper_classes: set[str] = set()
        has_direct_terminal_support = False
        has_upper_wrapper = False

        for card in soup.select(".grid-card"):
            children = [
                child for child in card.find_all(recursive=False)
                if getattr(child, "name", None)
            ]
            if not children:
                continue
            support_children = []
            for child in children:
                classes = {
                    str(name).lower()
                    for name in (child.get("class") or [])
                }
                if any(
                    term in class_name
                    for class_name in classes
                    for term in support_role_terms
                ):
                    support_children.append(child)
                    support_classes.update(classes)
            if not support_children:
                continue
            has_direct_terminal_support = True
            non_support = [
                child for child in children if child not in support_children
            ]
            for child in non_support:
                classes = {
                    str(name).lower()
                    for name in (child.get("class") or [])
                }
                wraps_upper_roles = len(child.find_all(recursive=False)) >= 2
                names_upper_role = any(
                    term in class_name
                    for class_name in classes
                    for term in upper_role_terms
                )
                if wraps_upper_roles and (
                    names_upper_role or len(non_support) == 1
                ):
                    has_upper_wrapper = True
                    upper_wrapper_classes.update(classes)
    except Exception:
        return ""

    if not has_direct_terminal_support:
        return ""

    compact_code = re.sub(r"\s+", "", code.lower())

    def declarations_for(classes: set[str]) -> str:
        blocks: list[str] = []
        for class_name in classes:
            blocks.extend(re.findall(
                rf"[^{{}}]*\.{re.escape(class_name)}(?![\w-])[^{{}}]*"
                r"\{([^{}]*)\}",
                compact_code,
            ))
        return "\n".join(blocks)

    card_blocks = "\n".join(re.findall(
        r"[^{}]*\.grid-card(?![\w-])[^{}]*\{([^{}]*)\}",
        compact_code,
    ))
    raw_card_blocks = "\n".join(re.findall(
        r"[^{}]*\.grid-card(?![\w-])[^{}]*\{([^{}]*)\}",
        code.lower(),
    ))
    support_blocks = declarations_for(support_classes)
    upper_blocks = declarations_for(upper_wrapper_classes)

    anchored_support = any(
        token in support_blocks
        for token in (
            "position:absolute", "position:fixed", "position:sticky",
        )
    )
    positioned_card = "position:relative" in card_blocks
    explicit_block_end_inset = any(
        token in card_blocks
        for token in ("padding-bottom:", "padding-block-end:")
    )
    asymmetric_padding_inset = False
    for shorthand in re.findall(r"(?:^|;)\s*padding\s*:([^;}]+)", raw_card_blocks):
        values = shorthand.split()
        if len(values) == 3 and values[2] != values[0]:
            asymmetric_padding_inset = True
        elif len(values) == 4 and values[2] != values[0]:
            asymmetric_padding_inset = True
    for shorthand in re.findall(
        r"(?:^|;)\s*padding-block\s*:([^;}]+)", raw_card_blocks,
    ):
        values = shorthand.split()
        if len(values) == 2 and values[1] != values[0]:
            asymmetric_padding_inset = True
    reserved_inset = explicit_block_end_inset or asymmetric_padding_inset
    anchored_reservation = (
        anchored_support and positioned_card and reserved_inset
    )

    grid_two_zone = (
        has_upper_wrapper
        and "display:grid" in card_blocks
        and any(
            token in card_blocks
            for token in ("grid-template-rows:", "grid-template-areas:")
        )
    )
    flex_two_zone = (
        has_upper_wrapper
        and "display:flex" in card_blocks
        and "flex-direction:column" in card_blocks
        and (
            "flex:" in upper_blocks
            or "flex-grow:" in upper_blocks
            or "margin-top:auto" in support_blocks
        )
    )
    if anchored_reservation or grid_two_zone or flex_two_zone:
        return ""

    # A concrete role/copy calibration is already a falsifiable ordinary-
    # flow hypothesis. Do not pressure the agent to invent wrappers or a
    # reserved-support topology merely because the DOM remains unchanged.
    if chose_role_calibration and not chose_reserved_support:
        if cluster_complete and action_promises_copy_calibration:
            try:
                from bs4 import BeautifulSoup

                support_copy_terms = (
                    "m-note", "finding", "takeaway", "support", "insight",
                    "callout", "conclusion", "recommendation",
                )

                def support_texts(source: str) -> tuple[str, ...]:
                    source_soup = BeautifulSoup(str(source or ""), "html.parser")
                    values: list[str] = []
                    for element in source_soup.find_all(class_=True):
                        classes = tuple(
                            str(name).lower()
                            for name in (element.get("class") or [])
                        )
                        if not any(
                            term in class_name
                            for class_name in classes
                            for term in support_copy_terms
                        ):
                            continue
                        if element.find_parent(class_=lambda value: value and any(
                            term in str(name).lower()
                            for name in (
                                value if isinstance(value, list)
                                else str(value).split()
                            )
                            for term in support_copy_terms
                        )):
                            continue
                        text = " ".join(element.get_text(" ", strip=True).split())
                        if text:
                            values.append(text)
                    return tuple(values)

                copy_is_still_original = (
                    support_texts(getattr(state, "original_code", ""))
                    == support_texts(getattr(state, "current_code", ""))
                )
            except Exception:
                copy_is_still_original = False
            if copy_is_still_original:
                return (
                    "\n\nCOUPLED-LEVER COMPLETION NOTE: this action's own "
                    "reasoning names authorized support-copy calibration as "
                    "part of the same fit hypothesis, but a CSS-only edit cannot "
                    "perform that wording change and the current support copy is "
                    "still the original wording. The CSS edit remains applied, "
                    "but the claimed hypothesis is not yet complete. Apply and "
                    "verify the transferable copy calibration before treating "
                    "residual pressure as evidence against this topology, or "
                    "explicitly revise the hypothesis to CSS-only. This is "
                    "advisory transaction feedback, not a required repair order "
                    "or rollback gate."
                )
        return ""

    if not chose_reserved_support and not chose_other_allocation:
        boundary = (
            "This completed checkpoint therefore tests only ordinary-flow "
            "compaction, not every same-topology allocation."
            if cluster_complete
            else (
                "The edit cluster is still open, so its allocation hypothesis "
                "can still be made explicit before the checkpoint is judged."
            )
        )
        return (
            "\n\nPLAN HYPOTHESIS SPECIFICITY NOTE: the active step says the "
            "repeated cards and terminal support should fit, but it does not "
            "identify how upper roles and the support branch are meant to share "
            "each card. The current DOM/CSS still represents one ordinary-flow "
            "stack. "
            f"{boundary} Before treating a failed verify as evidence that the "
            "comparison topology is infeasible, either complete this ordinary-flow "
            "hypothesis including any planned authorized copy calibration, or "
            "revise the plan to name another allocation family and implement it. "
            "Reserved support, semantic tracks, support bands, and larger reflows "
            "are possibilities, not requirements. The edit remains applied; this "
            "is advisory causal feedback, not a rollback or acceptance gate."
        )

    boundary = (
        "This completed checkpoint therefore has not tested the strategy "
        "described by the plan."
        if cluster_complete
        else (
            "The edit cluster is still open, so this may be an intentional "
            "intermediate state rather than a failed strategy."
        )
    )
    return (
        "\n\nPLAN-IMPLEMENTATION CONSISTENCY NOTE: the active repair "
        "hypothesis explicitly promises a distinct reserved or anchored "
        "terminal-support allocation, but the current cards still place the "
        "terminal support branch after several ordinary-flow upper children "
        "without an implemented upper/support allocation or an anchored branch "
        "with genuine in-card reservation. "
        f"{boundary} Complete the chosen hypothesis before using verification "
        "to conclude that the current comparison topology is infeasible, or "
        "revise the plan so its claimed strategy matches the implementation. "
        "The edit remains applied; this is advisory causal feedback, not a "
        "rollback or acceptance gate."
    )


def edit_cluster_execution_coverage_note(
    state: AgentState,
    *,
    before_code: str,
    after_code: str,
    action_text: str,
    cluster_complete: bool,
) -> str:
    """Report concrete action levers that a completed edit did not execute.

    The repair agent often states a useful coupled hypothesis but applies
    only its easiest subset, then misreads the resulting verification as a
    failure of the whole strategy. This check compares the action's own
    explicit promises with the code delta. It is intentionally advisory and
    strategy-neutral: it says which promised family is absent, not how that
    family must be implemented.
    """
    action_low = " ".join(str(action_text or "").lower().split())
    if not cluster_complete or not action_low or before_code == after_code:
        return ""

    # Structured repair reasoning often includes CURRENT/TARGET/CONFLICTS
    # descriptions for the whole issue set.  Coverage should judge what this
    # action says it will execute, not every unresolved role it mentions.
    coupled_moves = re.search(r"\bcoupled moves\s*:\s*", action_low)
    action_intent = (
        action_low[coupled_moves.end():]
        if coupled_moves
        else action_low
    )
    intent_clauses = tuple(
        clause.strip(" ,")
        for clause in re.split(r"[;\n]+", action_intent)
        if clause.strip(" ,")
    ) or (action_intent,)

    before_source = str(before_code or "")
    after_source = str(after_code or "")
    changed_fragments: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, before_source, after_source, autojunk=False,
    ).get_opcodes():
        if tag == "equal":
            continue
        changed_fragments.extend((before_source[i1:i2], after_source[j1:j2]))
    changed_blob = "\n".join(changed_fragments).lower()

    def has_any(text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    def family_is_negated_or_deferred(
        clause: str,
        targets: tuple[str, ...],
    ) -> bool:
        target_pattern = "(?:" + "|".join(
            re.escape(term) for term in targets
        ) + ")"
        return bool(
            re.search(
                rf"\b(?:no|without|not|avoid(?:ing)?|defer(?:red|ring)?)\b"
                rf".{{0,70}}{target_pattern}",
                clause,
            )
            or re.search(
                rf"{target_pattern}.{{0,70}}\b(?:later|next|separately|"
                r"unchanged|deferred|not involved)\b",
                clause,
            )
        )

    def promises_linked(
        targets: tuple[str, ...],
        actions: tuple[str, ...],
        *,
        max_gap: int = 100,
    ) -> bool:
        target_pattern = "(?:" + "|".join(
            re.escape(term) for term in targets
        ) + ")"
        action_pattern = "(?:" + "|".join(
            re.escape(term) for term in actions
        ) + ")"
        return any(
            not family_is_negated_or_deferred(clause, targets)
            and (
                re.search(
                    rf"{action_pattern}.{{0,{max_gap}}}{target_pattern}",
                    clause,
                )
                or re.search(
                    rf"{target_pattern}.{{0,{max_gap}}}{action_pattern}",
                    clause,
                )
            )
            for clause in intent_clauses
        )

    copy_targets = (
        "support copy", "support-copy", "explanatory copy", "wording",
        "metric note", "metric-note", "paragraph", "sentence",
        "takeaway", "finding", "caption", "description",
    )
    copy_actions = (
        "shorten", "compress", "condense", "rewrite", "trim",
        "simplify", "rephrase", "copy calibration",
    )
    promises_copy = promises_linked(copy_targets, copy_actions)

    upstream_targets = (
        "upstream", "top-band", "top band", "header", "title band",
        "summary", "overview band", "intro band", "frame space",
    )
    upstream_actions = (
        "reclaim", "reduce", "shrink", "lower", "trim", "reallocate",
        "release", "recover",
    )
    promises_upstream = promises_linked(
        upstream_targets, upstream_actions, max_gap=80,
    )

    terminal_targets = (
        "terminal support", "terminal branch", "lower branch", "findings",
        "finding", "takeaway", "support branch", "support region",
    )
    terminal_actions = (
        "allocate", "allocation", "anchor", "anchored", "reserve",
        "reserved", "ownership", "owner track", "dedicated",
        "two-part", "two part", "two-zone", "two zone",
        "attach", "attached", "bottom track", "lower track",
    )
    promises_terminal_allocation = promises_linked(
        terminal_targets, terminal_actions, max_gap=120,
    )

    topology_targets = (
        "reflow", "recompose", "restructure", "regroup", "topology",
        "matrix", "side rail", "side-rail", "two-column", "two column",
        "two-row", "two row", "2x2", "2×2", "stacked layout",
    )
    topology_actions = (
            "switch", "change", "convert", "reflow", "recompose",
            "restructure", "regroup", "move", "replace", "build",
            "create", "use", "turn into",
    )
    promises_topology = any(
        has_any(clause, topology_targets)
        and has_any(clause, topology_actions)
        and not family_is_negated_or_deferred(clause, topology_targets)
        for clause in intent_clauses
    )

    # Bare `.mini-chart` references usually mean frame-space CSS, not an
    # edit to chart/SVG internals.  Require an asset/internal target, or a
    # strong whole-chart replacement verb, before asking for media work.
    media_targets = (
        "svg", "viewbox", "image asset", "figure asset", "media asset",
        "svg label", "chart label", "axis label", "bar label",
        "image", "figure",
    )
    media_actions = (
        "repair", "wrap", "reposition", "crop", "replace", "redraw",
        "resize", "move", "edit", "revise",
    )
    promises_media = promises_linked(
        media_targets, media_actions, max_gap=100,
    ) or promises_linked(
        ("chart",),
        ("repair", "replace", "redraw", "crop", "rebuild", "regenerate"),
        max_gap=80,
    )

    def visible_text_counter(source: str) -> Counter:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(str(source or ""), "html.parser")
            values = []
            for node in soup.find_all(string=True):
                parent_name = str(getattr(node.parent, "name", "") or "").lower()
                if parent_name in {"style", "script", "noscript"}:
                    continue
                value = " ".join(str(node).split())
                if value:
                    values.append(value)
            return Counter(values)
        except Exception:
            return Counter()

    def css_rule_map(source: str) -> dict[str, tuple[str, ...]]:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(str(source or ""), "html.parser")
            css = "\n".join(
                style.get_text("\n") for style in soup.find_all("style")
            )
        except Exception:
            css = str(source or "")
        rules: dict[str, list[str]] = {}
        for selector, declarations in re.findall(
            r"([^{}]+)\{([^{}]*)\}", css, re.DOTALL,
        ):
            selector_norm = " ".join(selector.lower().split())
            declarations_norm = " ".join(declarations.lower().split())
            if selector_norm and declarations_norm:
                rules.setdefault(selector_norm, []).append(declarations_norm)
        return {
            selector: tuple(values)
            for selector, values in rules.items()
        }

    before_rules = css_rule_map(before_code)
    after_rules = css_rule_map(after_code)
    changed_rules = {
        selector: (
            before_rules.get(selector, ()),
            after_rules.get(selector, ()),
        )
        for selector in set(before_rules) | set(after_rules)
        if before_rules.get(selector, ()) != after_rules.get(selector, ())
    }

    def selector_names_role(selector: str, terms: tuple[str, ...]) -> bool:
        normalized = selector.replace("-", " ").replace("_", " ")
        return any(
            term.replace("-", " ").replace("_", " ") in normalized
            for term in terms
        )

    def changed_rule_has(
        selector_terms: tuple[str, ...],
        declaration_terms: tuple[str, ...] = (),
    ) -> bool:
        for selector, (before_values, after_values) in changed_rules.items():
            if not selector_names_role(selector, selector_terms):
                continue
            declarations = " ".join((*before_values, *after_values))
            if not declaration_terms or has_any(declarations, declaration_terms):
                return True
        return False

    def structure_signature(source: str) -> tuple:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(str(source or ""), "html.parser")
            signature = []
            for tag in soup.find_all(True):
                if str(tag.name).lower() in {"style", "script"}:
                    continue
                parent = tag.parent if getattr(tag.parent, "name", None) else None
                signature.append((
                    str(tag.name).lower(),
                    tuple(sorted(str(item) for item in (tag.get("class") or []))),
                    str(getattr(parent, "name", "") or "").lower(),
                    tuple(sorted(
                        str(item)
                        for item in ((parent.get("class") or []) if parent else [])
                    )),
                ))
            return tuple(signature)
        except Exception:
            return ()

    def media_signature(source: str) -> tuple:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(str(source or ""), "html.parser")
            return tuple(
                str(tag)
                for tag in soup.find_all(("svg", "img", "picture", "canvas"))
            )
        except Exception:
            return ()

    copy_changed = visible_text_counter(before_code) != visible_text_counter(after_code)

    upstream_changed = changed_rule_has(upstream_targets) or has_any(
        changed_blob, upstream_targets,
    )

    allocation_properties = (
        "display:grid", "display: grid", "display:flex", "display: flex",
        "grid-template", "grid-area", "flex-direction", "flex-grow",
        "margin-top:auto", "margin-top: auto", "align-self",
        "position:absolute", "position: absolute", "position:relative",
        "position: relative", "padding-bottom", "padding-block-end",
        "inset-block", "bottom:",
    )
    terminal_selector_terms = terminal_targets + (
        "insight", "conclusion", "recommendation",
    )
    owner_selector_terms = (
        "card", "panel", "tile", "cell", "profile", "peer", "comparison",
    )
    has_terminal_role = bool(re.search(
        r"class\s*=\s*['\"][^'\"]*(?:finding|takeaway|support|insight|conclusion)",
        after_source,
        re.IGNORECASE,
    ))
    terminal_allocation_changed = changed_rule_has(
        terminal_selector_terms, allocation_properties,
    ) or (
        has_terminal_role
        and changed_rule_has(owner_selector_terms, allocation_properties)
    )
    if not terminal_allocation_changed:
        terminal_allocation_changed = (
            structure_signature(before_code) != structure_signature(after_code)
            and has_any(changed_blob, terminal_selector_terms)
        )

    topology_properties = (
        "grid-template-columns", "grid-template-rows", "grid-template-areas",
        "flex-direction", "display:grid", "display: grid", "display:flex",
        "display: flex", "grid-area", "position:absolute", "position: absolute",
    )
    topology_changed = any(
        has_any(" ".join((*before_values, *after_values)), topology_properties)
        for before_values, after_values in changed_rules.values()
    ) or structure_signature(before_code) != structure_signature(after_code)

    media_changed = media_signature(before_code) != media_signature(after_code) or changed_rule_has(
        ("svg", "img", "image", "figure", "media"),
        (
            "object-fit", "object-position", "background-image", "width:",
            "height:", "transform:",
        ),
    )

    missing: list[str] = []
    if promises_copy and not copy_changed:
        missing.append("copy calibration")
    if promises_upstream and not upstream_changed:
        missing.append("upstream/frame-space reallocation")
    if promises_terminal_allocation and not terminal_allocation_changed:
        missing.append("terminal/support allocation or ownership")
    if promises_topology and not topology_changed:
        missing.append("topology/reflow")
    if promises_media and not media_changed:
        missing.append("local media/SVG work")
    if not missing:
        return ""

    return (
        "\n\nEDIT-CLUSTER COVERAGE NOTE: this completed action described a "
        "coupled repair hypothesis, but the actual code delta does not cover "
        + ", ".join(missing)
        + ". The applied edit remains available as an intermediate checkpoint. "
        "Before treating the next verification as evidence against the stated "
        "strategy, either execute the missing lever(s) in the same causal chain "
        "or explicitly narrow the hypothesis to what was actually changed. "
        "This is advisory execution feedback, not a repair-order rule, rollback "
        "gate, or acceptance gate."
    )


def dashboard_variable_track_patch_warning(
    state: AgentState,
    css: str,
) -> str:
    """Explain why equal fractional rows can hide variable text demand."""
    if not looks_like_table_dashboard_pressure(state):
        return ""

    equal_track_classes: set[str] = set()
    for selector, declarations in re.findall(
        r"([^{}]+)\{([^{}]*)\}", str(css or ""), re.DOTALL,
    ):
        declarations_low = re.sub(r"\s+", "", declarations.lower())
        forces_equal_fractional_rows = bool(
            re.search(
                r"grid-template-rows:(?:repeat\([^;]*(?:1fr|minmax\(0,1fr\))"
                r"|(?:1fr){2,})",
                declarations_low,
            )
            or re.search(
                r"grid-auto-rows:(?:minmax\(0,)?1fr",
                declarations_low,
            )
        )
        if not forces_equal_fractional_rows:
            continue
        equal_track_classes.update(
            name.lower()
            for name in re.findall(r"\.([a-z_][\w-]*)", selector.lower())
        )
    if not equal_track_classes:
        return ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            str(getattr(state, "current_code", "") or ""),
            "html.parser",
        )
        matched: list[str] = []
        for class_name in sorted(equal_track_classes):
            for container in soup.select(f".{class_name}"):
                text_children = [
                    child
                    for child in container.find_all(recursive=False)
                    if child.get_text(" ", strip=True)
                ]
                if len(text_children) >= 2:
                    matched.append(f".{class_name}")
                    break
    except Exception:
        matched = []
    if not matched:
        return ""

    shown = ", ".join(matched[:4])
    return (
        "\n\nVARIABLE-DEMAND TRACK CHECK: "
        f"{shown} contains repeated text-bearing children, while this patch "
        "forces them into equal fractional rows. Equal outer row boxes do not "
        "mean equal intrinsic text demand: a longer child can keep painting or "
        "wrapping into the next row even when the grid looks evenly allocated. "
        "If those peers have different line demand, keep their rows content-sized "
        "and compact the repeated rhythm, or group roles and allocate them from "
        "their measured descendant extents. Verify the child edges before "
        "abandoning the larger card-allocation strategy. The patch remains "
        "applied; this is implementation feedback, not a rollback gate."
    )


def dashboard_pending_coupled_compression_note(
    state: AgentState,
    spatial_state,
) -> str:
    """Flag a geometry checkpoint that precedes planned copy calibration.

    This is deliberately advisory. It prevents a valid repeated-card
    allocation from being judged against text demand that the active plan
    explicitly says will change, without forcing compression or a topology.
    """
    if not (
        getattr(state, "allow_support_copy_compression", False)
        and looks_like_table_dashboard_pressure(state)
    ):
        return ""

    pending_compression_steps = []
    for step in getattr(state, "plan_steps", []):
        if getattr(step, "status", "pending") in {"done", "skipped"}:
            continue
        text = " ".join((
            str(getattr(step, "text", "") or ""),
            str(getattr(step, "expected_outcome", "") or ""),
            str(getattr(step, "verify_criterion", "") or ""),
        )).lower()
        has_support_role = any(
            term in text
            for term in (
                "support", "finding", "takeaway", "explanatory copy",
            )
        )
        has_compression_action = any(
            term in text
            for term in (
                "compress_support_copy", "compress", "shorten", "condense",
            )
        )
        if has_support_role and has_compression_action:
            pending_compression_steps.append(step)
    if not pending_compression_steps:
        return ""

    try:
        from bs4 import BeautifulSoup

        support_terms = (
            "m-note", "finding", "takeaway", "support", "insight",
            "callout", "conclusion", "recommendation",
        )

        def support_texts(code: str) -> tuple[str, ...]:
            soup = BeautifulSoup(str(code or ""), "html.parser")
            texts: list[str] = []
            for element in soup.find_all(class_=True):
                classes = tuple(
                    str(name).lower() for name in (element.get("class") or [])
                )
                if any(
                    term in class_name
                    for class_name in classes
                    for term in support_terms
                ):
                    text = " ".join(element.get_text(" ", strip=True).split())
                    if text:
                        texts.append(text)
            return tuple(texts)

        current_soup = BeautifulSoup(
            str(getattr(state, "current_code", "") or ""),
            "html.parser",
        )
        has_explicit_allocation = any(
            any(
                term in str(name).lower()
                for name in (element.get("class") or [])
                for term in ("upper", "main", "body", "content")
            )
            for element in current_soup.find_all(class_=True)
        ) and any(
            any(
                term in str(name).lower()
                for name in (element.get("class") or [])
                for term in ("finding", "takeaway", "support")
            )
            for element in current_soup.find_all(class_=True)
        )
        copy_is_still_original = (
            support_texts(getattr(state, "original_code", ""))
            == support_texts(getattr(state, "current_code", ""))
        )
    except Exception:
        return ""

    if not (has_explicit_allocation and copy_is_still_original):
        return ""

    support_pressure = False
    for block in list(getattr(spatial_state, "blocks", []) or []):
        classes = tuple(
            str(name).lower()
            for name in (getattr(block, "css_classes", ()) or ())
        )
        if not any(
            term in class_name
            for class_name in classes
            for term in support_terms
        ):
            continue
        if (
            getattr(block, "is_clipped", False)
            or getattr(block, "is_overflowing", False)
            or block.block_id in set(getattr(spatial_state, "clipped_blocks", []) or [])
            or block.block_id in set(getattr(spatial_state, "overflow_blocks", []) or [])
            or getattr(block, "rendered_lines", 0) >= 2
        ):
            support_pressure = True
            break
    if not support_pressure:
        return ""

    return (
        "COUPLED HYPOTHESIS IS PROVISIONAL: the active plan combines layout "
        "allocation with authorized support-copy compression, but the current "
        "revision still uses the original support copy. This measurement therefore "
        "does not fully test the planned combined hypothesis. Before continuing, "
        "judge whether the current topology itself remains credible from the actual "
        "branch widths, wrapping, descendant extents, ownership, and neighboring "
        "regions. If the edit narrowed text-bearing roles, increased line demand, "
        "displaced pressure, or damaged hierarchy, revise or roll back that topology "
        "before compressing copy. If the owning region and reading path remain "
        "coherent and the residual is still driven by unchanged explanatory copy, "
        "complete the meaning-preserving copy and role-rhythm calibration as the "
        "same hypothesis, then verify it. A negative gap alone neither proves the "
        "topology can converge nor proves that it has failed."
    )


def dashboard_support_copy_checkpoint_note(
    state: AgentState,
    before_code: str,
    after_code: str,
    *,
    cluster_complete: bool,
) -> str:
    """Advise when reusable copy calibration is tied to a risky reflow.

    This is transaction guidance only. It does not force the text edit to
    remain, and it does not decide whether a later topology is appropriate.
    """
    if (
        not getattr(state, "allow_support_copy_compression", False)
        or not looks_like_table_dashboard_pressure(state)
        or not (_agent_repair_cls()._is_html_code(before_code) and _agent_repair_cls()._is_html_code(after_code))
    ):
        return ""

    try:
        from bs4 import BeautifulSoup

        support_terms = (
            "m-note", "finding", "takeaway", "support", "insight",
            "callout", "conclusion", "recommendation",
        )

        def support_texts(code: str) -> tuple[str, ...]:
            soup = BeautifulSoup(code, "html.parser")
            texts: list[str] = []
            for element in soup.find_all(class_=True):
                classes = tuple(
                    str(name).lower() for name in (element.get("class") or [])
                )
                if any(
                    term in class_name
                    for class_name in classes
                    for term in support_terms
                ):
                    text = " ".join(element.get_text(" ", strip=True).split())
                    if text:
                        texts.append(text)
            return tuple(texts)

        def structure_signature(code: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
            soup = BeautifulSoup(code, "html.parser")
            return tuple(
                (
                    str(element.name),
                    tuple(sorted(str(name) for name in (element.get("class") or []))),
                )
                for element in soup.find_all(True)
            )

        before_support = support_texts(before_code)
        after_support = support_texts(after_code)
        support_changed = (
            before_support != after_support
            and len(after_support) == len(before_support)
            and sum(map(len, after_support)) < sum(map(len, before_support))
        )
        structure_unchanged = (
            structure_signature(before_code) == structure_signature(after_code)
        )
        before_soup = BeautifulSoup(before_code, "html.parser")
        after_soup = BeautifulSoup(after_code, "html.parser")
        before_styles = tuple(
            style.get_text("\n", strip=True)
            for style in before_soup.find_all("style")
        )
        after_styles = tuple(
            style.get_text("\n", strip=True)
            for style in after_soup.find_all("style")
        )
        style_changed = before_styles != after_styles
    except Exception:
        return ""

    if not support_changed:
        return ""

    if style_changed or not structure_unchanged:
        return (
            "\n\nMIXED CHECKPOINT RECOVERY NOTE: this checkpoint combines "
            "authorized support-copy shortening with layout or structural "
            "changes. A cluster rollback will discard both. If verification "
            "shows that the geometry strategy is harmful but the wording "
            "calibration is transferable, preserve it with a forward edit or "
            "reapply it as a standalone checkpoint after rollback. Do not use "
            "the restored long-copy baseline as evidence that the peer topology "
            "is infeasible. Roles whose rendered lines did not retreat still "
            "need stronger proposition-level calibration. This is advisory "
            "transaction guidance, not a requirement to keep a bad edit."
        )

    if cluster_complete or not structure_unchanged:
        return ""

    return (
        "\n\nCHECKPOINT BOUNDARY NOTE: this unfinished batch changes only "
        "authorized support wording; the structural reflow has not happened "
        "yet. If this meaning-preserving calibration is useful under more than "
        "one plausible layout, it is an independent checkpoint rather than a "
        "dependent intermediate state. Verify and preserve it before opening "
        "the higher-risk topology experiment, or, if the cluster is already "
        "open, avoid a cluster-wide rollback that would discard the reusable "
        "calibration. Keep the batch coupled only when the wording is genuinely "
        "specific to the proposed topology. This is advisory transaction "
        "guidance, not a requirement to keep the text edit."
    )


def dashboard_coupled_cluster_guidance(
    code: str = "", *, preview_enabled: bool = False,
) -> str:
    evidence = (
        "the current render and spatial evidence"
        if preview_enabled
        else (
            "the current HTML/CSS, LAYOUT ANCHOR, RELATION MAP, SPACE MAP, "
            "and detector evidence"
        )
    )
    later_evidence = (
        "later render and spatial evidence"
        if preview_enabled
        else "later spatial evidence from the edited revision"
    )
    completion_evidence = (
        "verify_layout and the full render"
        if preview_enabled
        else "verify_layout and the current revision evidence"
    )
    return (
        "## Current Dashboard Strategy Cue\n"
        "Several table/card/note regions may be competing for the same body "
        "space. Treat that as a hypothesis to inspect, not as a mandatory "
        f"repair recipe. Use {evidence} to identify "
        "which parent tracks and child roles actually create the pressure.\n\n"
        "Before choosing an outer height, estimate one complete peer's rendered "
        "demand: identity, focal value, repeated detail, explanatory copy, and "
        "terminal support. Include title/top-band demand in the whole-slide budget, "
        "but protect footer/source text by its measured visible bounds rather than "
        "treating a sparse footer as a full-width exclusion band. Do not shrink an "
        "already overfull owner merely so its border ends above that imagined band.\n\n"
        "A hypothesis is incomplete when its stated cause was never tested. Do not "
        "reject a same-topology composition while upstream title/top-band descendants "
        "retain their original footprint, a distinct terminal child still lacks real "
        "ownership/allocation, or planned support-copy calibration remains unchanged, "
        "a no-op, or a synonym edit. Verify the completed combination before blaming "
        "the topology itself.\n\n"
        "Compare role-aware same-topology calibration, minimal reallocation of an "
        "existing terminal child, and regional/body reflow as equal candidates. If "
        "a card already has a distinct terminal child, give it a real in-card "
        "allocation before inventing a wrapper. Generic options include an anchored "
        "child with matching owner inset, an explicit owner track, or genuine flex "
        "allocation whose rendered branches stay within their shares. These are "
        "directions, not required selectors, coordinates, dimensions, or an ordered "
        "recipe. Add wrappers only when the upper roles genuinely need semantic "
        "grouping or ordinary flow cannot express the chosen reading path. No "
        "candidate is a required first step.\n\n"
        "Use descendant extents, line counts, and sibling geometry to test whether "
        "the edit changed real demand. Parent height, `flex-shrink`, or a grid "
        "declaration does not reclaim space until the rendered child edge retreats. "
        "Repeated padding, gaps, line-height, and wrapping have cumulative leverage; "
        "preserve the hierarchy between identity, data, explanation, and conclusion "
        "rather than shrinking all roles uniformly.\n\n"
        "When support-copy compression is authorized, shorten propositions rather "
        "than substituting synonyms. Diagnose metric explanations, terminal "
        "findings, and other support roles separately so the pressure-bearing role "
        "receives the real edit. Preserve facts, distinctions, values, labels, and "
        "conclusions, then judge success from role-specific wrapping, readable "
        "scale, and containment instead of edit count or changed-root coverage. A "
        "reusable copy calibration may be verified independently before a risky "
        "topology experiment.\n\n"
        "A topology change must improve one complete peer's usable allocation and "
        "reading path. Extra width may reduce wrapping but does not automatically "
        "add vertical capacity; detached support rows and multi-row peer grids can "
        "make the whole composition taller or weaken ownership. When a recent "
        "coherent checkpoint kept per-peer terminal support attached, compare any "
        "detached-row candidate against that checkpoint before declaring it "
        "stronger. If the new candidate does not improve the pressure-bearing "
        "role's line demand or readable scale, it has moved semantic ownership "
        "without solving the original density cause.\n\n"
        "A recoverable same-region intermediate state may need another direct "
        f"closure edit based on {later_evidence}. Roll back when content, media, "
        "hierarchy, or unrelated chrome is damaged, or when the current family has "
        "no credible readable closure path. After rollback, verify whether the "
        "restored checkpoint still contains the abandoned topology or earlier damage; "
        "roll back farther or replace that patch before branching when it does.\n\n"
        "Choose the actual selectors, edit scope, ordering, and scale from this "
        "slide's evidence. No named selector, font size, body height, or one-batch "
        f"trajectory is required. After a coherent attempt, use {completion_evidence} "
        "to decide whether the original conflict was resolved "
        "rather than merely displaced."
    )


def dashboard_measurement_context(spatial_text: str) -> str:
    """Make generic spatial diagnostics role-aware for dense dashboards.

    The base spatial formatter intentionally reports raw clipping extents and
    generic typography references. In a fixed-height dashboard those numbers
    are evidence, not prescriptions: growing a clipped table can steal the
    notes band, and repeated data cells can legitimately be smaller than body
    prose. Keep the measurements while removing the misleading command tone.
    """
    text = str(spatial_text or "")
    text = re.sub(
        r"\(height:(\d+)px\s*→\s*grow to\s*(\d+)px\)",
        (
            r"(parent height:\1px; clipped content reaches about \2px; "
            r"this is not a recommendation to grow the parent)"
        ),
        text,
    )
    text = text.replace(
        "⚠ SMALL FONT:",
        "ℹ COMPACT TEXT ROLE MEASUREMENT:",
    )
    text = text.replace(
        "below 14px body minimum",
        "below the generic 14px body reference",
    )
    text = text.replace(
        "below minimum:",
        "below generic reference sizes (inspection context):",
    )
    text = re.sub(
        r"\(heading min (\d+)px\)",
        r"(generic heading reference \1px)",
        text,
    )
    text = re.sub(
        r"\(body min (\d+)px\)",
        r"(generic body reference \1px)",
        text,
    )
    fit_cue = dashboard_fit_magnitude_cue(text)
    return (
        "DENSE DASHBOARD MEASUREMENT CONTEXT: clip-parent extents and generic "
        "font references below are measurements, not repair instructions. "
        "Do not grow a table parent when it would consume the notes/footer "
        "budget, and do not inflate compact repeated data/support roles solely "
        "to meet the generic 14px reference. Repeated rows/cards accumulate "
        "spacing and wrapping costs across the region; inspect that repeated "
        "rhythm before repeatedly shrinking one-time title/header/KPI anchors. "
        "Judge role hierarchy and the full fixed-height cluster.\n\n"
        + fit_cue
        + text
    )


def dashboard_decision_summary(
    state: AgentState,
    spatial_state,
) -> str:
    """Put the causal dashboard measurements ahead of the verbose maps.

    The detailed spatial formatter is useful for locating individual nodes,
    but it can bury the few relationships that decide whether a layout
    hypothesis was actually tested. This summary is descriptive evidence,
    not an acceptance gate or a required repair recipe.
    """
    setattr(state, "_dashboard_next_strategy_note", "")

    def semantic_blocks_for(measured_state) -> list[ContentBlock]:
        measured_blocks = list(getattr(measured_state, "blocks", []) or [])
        visible_paths = {
            block.dom_path for block in measured_blocks
            if getattr(block, "dom_path", "")
        }
        for index, element in enumerate(
            getattr(measured_state, "off_canvas_elements", []) or [], 1,
        ):
            dom_path = str(element.get("domPath") or "")
            if not dom_path or dom_path in visible_paths:
                continue
            classes = tuple(sorted({
                item.lower()
                for item in str(element.get("classes") or "").split()
                if item
            }))
            text_value = str(
                element.get("text") or element.get("fullText") or ""
            )
            measured_blocks.append(ContentBlock(
                block_id=f"decision_off_canvas_{index:02d}",
                var_name=str(element.get("tag") or "div"),
                shape_type="textbox" if text_value else "shape",
                css_selector=(
                    f"#{element['id']}" if element.get("id")
                    else f".{classes[0]}" if classes
                    else str(element.get("tag") or "div")
                ),
                css_classes=classes,
                dom_path=dom_path,
                bbox_px=(
                    int(element.get("x") or 0),
                    int(element.get("y") or 0),
                    int(element.get("w") or 0),
                    int(element.get("h") or 0),
                ),
                rendered_lines=int(element.get("renderedLines") or 0),
                text_lines=text_value.split("\n")[:10] if text_value else [],
            ))
        return measured_blocks

    blocks = list(getattr(spatial_state, "blocks", []) or [])
    if not blocks:
        return ""
    semantic_blocks = semantic_blocks_for(spatial_state)

    def class_tokens(block) -> tuple[str, ...]:
        return tuple(
            str(name).lower()
            for name in (getattr(block, "css_classes", ()) or ())
        )

    def descendants(container, source_blocks=None) -> list:
        source = source_blocks if source_blocks is not None else semantic_blocks
        prefix = f"{container.dom_path}/"
        return [
            block for block in source
            if block is not container
            and block.dom_path
            and block.dom_path.startswith(prefix)
        ]

    card_terms = ("card", "tile", "panel")
    card_groups: dict[tuple[str, str, tuple[str, ...]], list] = {}
    for block in blocks:
        classes = tuple(sorted(class_tokens(block)))
        if not classes or not any(
            term in class_name
            for class_name in classes
            for term in card_terms
        ):
            continue
        key = (dom_parent_path(block.dom_path), block.var_name, classes)
        card_groups.setdefault(key, []).append(block)

    repeated_groups = [group for group in card_groups.values() if len(group) >= 2]
    if not repeated_groups:
        return ""
    peers = max(
        repeated_groups,
        key=lambda group: (len(group), min(block.bbox_px[1] for block in group)),
    )
    peers = sorted(peers, key=lambda block: (block.bbox_px[1], block.bbox_px[0]))

    def clustered(values: list[int], tolerance: int = 6) -> list[list[int]]:
        groups: list[list[int]] = []
        for value in sorted(values):
            if not groups or value - groups[-1][-1] > tolerance:
                groups.append([value])
            else:
                groups[-1].append(value)
        return groups

    row_groups = clustered([block.bbox_px[1] for block in peers])
    column_groups = clustered([block.bbox_px[0] for block in peers])
    row_counts = [
        sum(abs(block.bbox_px[1] - row[0]) <= 6 for block in peers)
        for row in row_groups
    ]
    if len(row_groups) == 1:
        topology = f"one row with {len(peers)} peer columns"
    else:
        topology = (
            f"{len(row_groups)} rows with peer counts {row_counts}; "
            f"{len(column_groups)} observed column anchors"
        )

    owner_heights: list[int] = []
    demand_heights: list[int] = []
    demand_deltas: list[int] = []
    deepest_descendant_bottoms: list[int] = []
    peer_prefixes: list[str] = []
    for peer in peers:
        _, peer_y, _, peer_h = peer.bbox_px
        members = descendants(peer)
        deepest_bottom = max(
            (member.bbox_px[1] + member.bbox_px[3] for member in members),
            default=peer_y + peer_h,
        )
        owner_heights.append(peer_h)
        demand_heights.append(deepest_bottom - peer_y)
        demand_deltas.append(deepest_bottom - (peer_y + peer_h))
        deepest_descendant_bottoms.append(deepest_bottom)
        if peer.dom_path:
            peer_prefixes.append(f"{peer.dom_path}/")

    def range_text(values: list[int]) -> str:
        if not values:
            return "unknown"
        low, high = min(values), max(values)
        return f"{low}px" if low == high else f"{low}-{high}px"

    first_peer_top = min(block.bbox_px[1] for block in peers)
    footer_terms = ("footer", "footnote", "source", "credit")

    def is_footer(block) -> bool:
        role = " ".join((*class_tokens(block), str(block.var_name).lower()))
        text = " ".join(getattr(block, "text_lines", []) or []).strip().lower()
        return (
            any(term in role for term in footer_terms)
            or bool(re.match(r"^(?:source|sources|citation|credit)\s*:", text))
        )

    footer_tops = [
        block.bbox_px[1] for block in semantic_blocks if is_footer(block)
    ]
    footer_top = min(footer_tops) if footer_tops else None
    usable_peer_heights: list[int] = []
    owner_vs_usable_deltas: list[int] = []
    descendant_vs_footer_deltas: list[int] = []
    if footer_top is not None:
        for peer, deepest_bottom in zip(peers, deepest_descendant_bottoms):
            _, peer_y, _, peer_h = peer.bbox_px
            usable_height = footer_top - peer_y
            usable_peer_heights.append(usable_height)
            owner_vs_usable_deltas.append(peer_h - usable_height)
            descendant_vs_footer_deltas.append(deepest_bottom - footer_top)

    upstream_terms = (
        "header", "summary", "mini", "hero", "overview", "top-band",
        "top_band", "kpi", "chart",
    )
    upstream_roots = [
        block for block in semantic_blocks
        if block.bbox_px[1] < first_peer_top
        and not is_footer(block)
        and any(term in " ".join(class_tokens(block)) for term in upstream_terms)
        and not any(
            block.dom_path.startswith(prefix) for prefix in peer_prefixes
        )
    ]
    upstream_bottom = None
    if upstream_roots:
        upstream_bottom = max(
            member.bbox_px[1] + member.bbox_px[3]
            for root in upstream_roots
            for member in [root, *descendants(root)]
        )

    direct_terminal_count = 0
    total_dom_cards = 0
    support_classes: set[str] = set()
    support_terms = (
        "m-note", "finding", "takeaway", "support", "insight",
        "callout", "conclusion", "recommendation",
    )
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(str(getattr(state, "current_code", "") or ""), "html.parser")
        dom_cards = soup.select(".grid-card")
        total_dom_cards = len(dom_cards)
        for card in dom_cards:
            terminal_children = []
            for child in card.find_all(recursive=False):
                classes = {
                    str(name).lower() for name in (child.get("class") or [])
                }
                if any(
                    term in class_name
                    for class_name in classes
                    for term in support_terms
                ):
                    terminal_children.append(child)
                    support_classes.update(classes)
            if terminal_children:
                direct_terminal_count += 1
    except Exception:
        pass

    compact_code = re.sub(
        r"\s+", "", str(getattr(state, "current_code", "") or "").lower(),
    )

    def declarations_for(classes: set[str]) -> str:
        declarations: list[str] = []
        for class_name in classes:
            declarations.extend(re.findall(
                rf"[^{{}}]*\.{re.escape(class_name)}(?![\w-])[^{{}}]*"
                r"\{([^{}]*)\}",
                compact_code,
            ))
        return "\n".join(declarations)

    card_blocks = "\n".join(re.findall(
        r"[^{}]*\.grid-card(?![\w-])[^{}]*\{([^{}]*)\}",
        compact_code,
    ))
    support_blocks = declarations_for(support_classes)
    anchored_terminal = "position:absolute" in support_blocks
    positioned_owner = "position:relative" in card_blocks
    owner_reserves_bottom = any(
        token in card_blocks
        for token in ("padding-bottom:", "padding-block-end:")
    )
    if not owner_reserves_bottom:
        raw_code = str(getattr(state, "current_code", "") or "").lower()
        raw_card_blocks = "\n".join(re.findall(
            r"[^{}]*\.grid-card(?![\w-])[^{}]*\{([^{}]*)\}",
            raw_code,
        ))
        for shorthand in re.findall(
            r"(?:^|;)\s*padding\s*:([^;}]+)", raw_card_blocks,
        ):
            values = shorthand.split()
            if len(values) in {3, 4} and values[2] != values[0]:
                owner_reserves_bottom = True
                break
    anchored_reservation = (
        anchored_terminal and positioned_owner and owner_reserves_bottom
    )
    explicit_owner_track = (
        "display:grid" in card_blocks
        and "grid-template-rows:" in card_blocks
        and direct_terminal_count > 0
    )
    flex_terminal_allocation = (
        "display:flex" in card_blocks
        and "flex-direction:column" in card_blocks
        and direct_terminal_count > 0
        and any(
            token in support_blocks
            for token in ("margin-top:auto", "margin-block-start:auto")
        )
    )
    terminal_ownership = (
        anchored_reservation
        or explicit_owner_track
        or flex_terminal_allocation
    )

    def direct_branch(container_path: str, descendant_path: str) -> str:
        prefix = f"{container_path}/"
        if not descendant_path.startswith(prefix):
            return ""
        first = descendant_path[len(prefix):].split("/", 1)[0]
        return prefix + first

    terminal_support_terms = tuple(
        term for term in support_terms if term != "m-note"
    )
    terminal_gaps: list[int] = []
    terminal_owner_deltas: list[int] = []
    upper_branch_demands: list[int] = []
    terminal_branch_heights: list[int] = []
    for peer in peers:
        branches: dict[str, list[ContentBlock]] = {}
        for member in descendants(peer):
            branch = direct_branch(peer.dom_path, member.dom_path)
            if branch:
                branches.setdefault(branch, []).append(member)
        terminal_branches = {
            branch for branch, members in branches.items()
            if any(
                term in class_name
                for member in members
                for class_name in class_tokens(member)
                for term in terminal_support_terms
            )
        }
        if not terminal_branches:
            continue
        terminal_members = [
            member for branch in terminal_branches
            for member in branches.get(branch, [])
        ]
        upper_members = [
            member for branch, members in branches.items()
            if branch not in terminal_branches
            for member in members
        ]
        if not terminal_members or not upper_members:
            continue
        terminal_top = min(member.bbox_px[1] for member in terminal_members)
        terminal_bottom = max(
            member.bbox_px[1] + member.bbox_px[3]
            for member in terminal_members
        )
        upper_bottom = max(
            member.bbox_px[1] + member.bbox_px[3]
            for member in upper_members
        )
        _, peer_y, _, peer_h = peer.bbox_px
        terminal_gaps.append(terminal_top - upper_bottom)
        terminal_owner_deltas.append(terminal_bottom - (peer_y + peer_h))
        upper_branch_demands.append(upper_bottom - peer_y)
        terminal_branch_heights.append(terminal_bottom - terminal_top)

    def support_text_stats(code: str) -> tuple[int, tuple[str, ...]]:
        try:
            from bs4 import BeautifulSoup

            text_soup = BeautifulSoup(str(code or ""), "html.parser")
            texts: list[str] = []
            for element in text_soup.find_all(class_=True):
                classes = {
                    str(name).lower() for name in (element.get("class") or [])
                }
                if not any(
                    term in class_name
                    for class_name in classes
                    for term in support_terms
                ):
                    continue
                if element.find_parent(class_=lambda value: value and any(
                    term in str(name).lower()
                    for name in (
                        value if isinstance(value, list) else str(value).split()
                    )
                    for term in support_terms
                )):
                    continue
                text = " ".join(element.get_text(" ", strip=True).split())
                if text:
                    texts.append(text)
            words = sum(len(re.findall(r"\b[\w.+-]+\b", text)) for text in texts)
            return words, tuple(texts)
        except Exception:
            return 0, ()

    def support_rendered_lines(measured_state) -> int:
        measured_blocks = semantic_blocks_for(measured_state)
        roots = [
            block.dom_path for block in measured_blocks
            if block.dom_path and any(
                term in class_name
                for class_name in class_tokens(block)
                for term in support_terms
            )
        ]
        return sum(
            int(getattr(block, "rendered_lines", 0) or 0)
            for block in measured_blocks
            if any(
                block.dom_path == root or block.dom_path.startswith(f"{root}/")
                for root in roots
            )
        )

    def support_role(class_names: tuple[str, ...] | set[str]) -> str:
        names = tuple(str(name).lower() for name in class_names)
        if any(
            term in class_name
            for class_name in names
            for term in ("m-note", "metric-note", "metric_note")
        ):
            return "metric explanations"
        if any(
            term in class_name
            for class_name in names
            for term in (
                "finding", "takeaway", "conclusion",
                "recommendation", "insight", "callout",
            )
        ):
            return "terminal support"
        return "other support"

    def support_text_stats_by_role(code: str) -> dict[str, dict[str, object]]:
        try:
            from bs4 import BeautifulSoup

            text_soup = BeautifulSoup(str(code or ""), "html.parser")
            grouped: dict[str, list[str]] = {}
            for element in text_soup.find_all(class_=True):
                classes = {
                    str(name).lower() for name in (element.get("class") or [])
                }
                if not any(
                    term in class_name
                    for class_name in classes
                    for term in support_terms
                ):
                    continue
                if element.find_parent(class_=lambda value: value and any(
                    term in str(name).lower()
                    for name in (
                        value if isinstance(value, list) else str(value).split()
                    )
                    for term in support_terms
                )):
                    continue
                text = " ".join(element.get_text(" ", strip=True).split())
                if text:
                    grouped.setdefault(support_role(classes), []).append(text)
            result: dict[str, dict[str, object]] = {}
            for role, texts in grouped.items():
                result[role] = {
                    "words": sum(
                        len(re.findall(r"\b[\w.+-]+\b", text))
                        for text in texts
                    ),
                    "texts": tuple(texts),
                }
            return result
        except Exception:
            return {}

    def support_render_stats_by_role(measured_state) -> dict[str, dict[str, object]]:
        measured_blocks = semantic_blocks_for(measured_state)
        candidates = [
            block for block in measured_blocks
            if block.dom_path and any(
                term in class_name
                for class_name in class_tokens(block)
                for term in support_terms
            )
        ]
        candidate_paths = {block.dom_path for block in candidates}
        roots = [
            block for block in candidates
            if not any(
                block.dom_path.startswith(f"{other_path}/")
                for other_path in candidate_paths
                if other_path != block.dom_path
            )
        ]
        grouped: dict[str, dict[str, object]] = {}
        for root in roots:
            role = support_role(class_tokens(root))
            members = [
                block for block in measured_blocks
                if block.dom_path == root.dom_path
                or block.dom_path.startswith(f"{root.dom_path}/")
            ]
            root_lines = sum(
                int(getattr(block, "rendered_lines", 0) or 0)
                for block in members
            )
            font_sizes = [
                float(getattr(block, "font_size_px", 0) or 0)
                for block in members
                if float(getattr(block, "font_size_px", 0) or 0) > 0
                and (
                    int(getattr(block, "rendered_lines", 0) or 0) > 0
                    or int(getattr(block, "text_chars", 0) or 0) > 0
                )
            ]
            bucket = grouped.setdefault(role, {
                "lines": 0,
                "root_lines": [],
                "font_sizes": [],
                "roots": 0,
            })
            bucket["lines"] = int(bucket["lines"]) + root_lines
            cast_root_lines = bucket["root_lines"]
            cast_fonts = bucket["font_sizes"]
            if isinstance(cast_root_lines, list):
                cast_root_lines.append(root_lines)
            if isinstance(cast_fonts, list):
                cast_fonts.extend(font_sizes)
            bucket["roots"] = int(bucket["roots"]) + 1
        return grouped

    def compact_range(values: list[float] | list[int], suffix: str = "") -> str:
        if not values:
            return "not measured"
        low = min(values)
        high = max(values)
        if isinstance(low, float) or isinstance(high, float):
            low_text = f"{low:g}"
            high_text = f"{high:g}"
        else:
            low_text = str(low)
            high_text = str(high)
        if low == high:
            return f"{low_text}{suffix}"
        return f"{low_text}-{high_text}{suffix}"

    original_words, original_support = support_text_stats(
        getattr(state, "original_code", ""),
    )
    current_words, current_support = support_text_stats(
        getattr(state, "current_code", ""),
    )
    comparable_support_roots = min(len(original_support), len(current_support))
    changed_support_roots = sum(
        before != after
        for before, after in zip(original_support, current_support)
    )
    unchanged_support_roots = max(
        0,
        comparable_support_roots - changed_support_roots,
    )
    support_root_detail = (
        f"support roots changed {changed_support_roots}/{comparable_support_roots}; "
        f"unchanged {unchanged_support_roots}"
        if comparable_support_roots else "support roots not identified"
    )
    baseline_state = getattr(state, "_t0_html_state", None)
    baseline_lines = support_rendered_lines(baseline_state) if baseline_state else 0
    current_lines = support_rendered_lines(spatial_state)
    original_role_text = support_text_stats_by_role(
        getattr(state, "original_code", ""),
    )
    current_role_text = support_text_stats_by_role(
        getattr(state, "current_code", ""),
    )
    baseline_role_render = (
        support_render_stats_by_role(baseline_state)
        if baseline_state else {}
    )
    current_role_render = support_render_stats_by_role(spatial_state)
    support_role_rows: list[str] = []
    role_history_metrics: dict[str, dict[str, object]] = {}
    ineffective_role_calibrations: list[str] = []
    effective_role_calibrations: list[str] = []
    for role in (
        "metric explanations", "terminal support", "other support",
    ):
        original_role = original_role_text.get(role, {})
        current_role = current_role_text.get(role, {})
        baseline_render = baseline_role_render.get(role, {})
        current_render = current_role_render.get(role, {})
        if not (original_role or current_role or baseline_render or current_render):
            continue
        original_texts = tuple(original_role.get("texts", ()))
        current_texts = tuple(current_role.get("texts", ()))
        comparable = min(len(original_texts), len(current_texts))
        changed = sum(
            before != after
            for before, after in zip(original_texts, current_texts)
        )
        unchanged = max(0, comparable - changed)
        original_role_words = int(original_role.get("words", 0))
        current_role_words = int(current_role.get("words", 0))
        baseline_role_lines = int(baseline_render.get("lines", 0))
        current_role_lines = int(current_render.get("lines", 0))
        current_root_lines = list(current_render.get("root_lines", []))
        current_font_sizes = list(current_render.get("font_sizes", []))
        role_was_edited = changed > 0 or current_role_words != original_role_words
        role_words_reduced = current_role_words < original_role_words
        role_lines_measured = baseline_role_lines > 0 and current_role_lines > 0
        if role_was_edited and role_words_reduced and role_lines_measured:
            if current_role_lines < baseline_role_lines:
                calibration_status = "rendered demand reduced"
                effective_role_calibrations.append(role)
            else:
                calibration_status = (
                    "edited, but rendered line demand did not retreat"
                )
                ineffective_role_calibrations.append(role)
        elif role_was_edited and not role_words_reduced:
            calibration_status = "edited without shorter wording"
            ineffective_role_calibrations.append(role)
        elif not role_was_edited:
            calibration_status = "wording unchanged"
        else:
            calibration_status = "rendered demand not fully measured"
        support_role_rows.append(
            f"{role}: words {original_role_words}"
            f"->{current_role_words}; rendered lines "
            f"{baseline_role_lines}"
            f"->{current_role_lines}; roots changed "
            f"{changed}/{comparable}, unchanged {unchanged}; current per-root "
            f"lines {compact_range(current_root_lines)}; text scale "
            f"{compact_range(current_font_sizes, 'px')}; calibration "
            f"{calibration_status}"
        )
        role_history_metrics[role] = {
            "words": current_role_words,
            "lines": current_role_lines,
            "root_lines": current_root_lines,
            "font_sizes": current_font_sizes,
            "roots": int(current_render.get("roots", 0)),
            "calibration": calibration_status,
        }
    support_role_detail = (
        "; ".join(support_role_rows)
        if support_role_rows else "support roles not identified"
    )
    if current_support == original_support:
        copy_status = (
            f"no; wording is unchanged ({current_words} words); "
            f"{support_root_detail}"
        )
    elif ineffective_role_calibrations:
        unresolved_roles = ", ".join(ineffective_role_calibrations)
        copy_status = (
            f"partial; aggregate demand is {original_words}->{current_words} "
            f"words and {baseline_lines}->{current_lines} rendered lines, but "
            f"{unresolved_roles} changed without role-level line relief; "
            f"{support_root_detail}"
        )
    elif current_words < original_words and baseline_lines and current_lines < baseline_lines:
        copy_status = (
            f"yes; {original_words}->{current_words} words and "
            f"{baseline_lines}->{current_lines} rendered lines; "
            f"{support_root_detail}"
        )
    elif current_words < original_words:
        copy_status = (
            f"wording is shorter ({original_words}->{current_words} words), "
            f"but rendered line demand is {baseline_lines}->{current_lines}; "
            "material geometry relief is not yet demonstrated; "
            f"{support_root_detail}"
        )
    else:
        copy_status = (
            f"no clear reduction; {original_words}->{current_words} words and "
            f"{baseline_lines}->{current_lines} rendered lines; "
            f"{support_root_detail}"
        )

    budget_parts = [
        f"upstream deepest descendant bottom={upstream_bottom}px"
        if upstream_bottom is not None else "upstream descendant bottom=not identified",
        f"first peer top={first_peer_top}px",
        f"footer/source top={footer_top}px"
        if footer_top is not None else "footer/source top=not identified",
    ]
    usable_budget_detail = "not identified because no footer/source bound was measured"
    if usable_peer_heights:
        usable_budget_detail = (
            f"usable peer height {range_text(usable_peer_heights)}; "
            f"owner-vs-usable-height {range_text(owner_vs_usable_deltas)}; "
            f"deepest descendant bottom {range_text(deepest_descendant_bottoms)}; "
            "deepest-descendant-vs-footer/source "
            f"{range_text(descendant_vs_footer_deltas)}"
        )
    terminal_coverage = (
        f"{direct_terminal_count}/{total_dom_cards} cards"
        if total_dom_cards else "not identified"
    )
    if anchored_reservation:
        ownership_detail = "yes (anchored child + positioned owner + bottom inset)"
    elif explicit_owner_track:
        ownership_detail = "yes (direct terminal child in an explicit owner track)"
    elif flex_terminal_allocation:
        ownership_detail = "yes (direct terminal child receives terminal flex allocation)"
    elif anchored_terminal and not positioned_owner:
        ownership_detail = "no (terminal anchor exists, but its owner is not positioned)"
    elif anchored_terminal:
        ownership_detail = "no (terminal anchor exists, but the owner has no matching bottom inset)"
    else:
        ownership_detail = (
            "no (a direct terminal child exists, but no anchor, explicit track, "
            "or terminal flex allocation was identified)"
        )

    interpretation: list[str] = []
    if upstream_bottom is not None and upstream_bottom > first_peer_top:
        interpretation.append(
            "upstream content already enters the peer region, so repeated-card "
            "edits alone do not test the whole-canvas budget"
        )
    if owner_vs_usable_deltas and max(owner_vs_usable_deltas) > 0:
        interpretation.append(
            "at least one repeated owner is taller than its actual peer-to-footer "
            "budget; descendants fitting inside that oversized owner do not establish "
            "usable-canvas containment"
        )
    if descendant_vs_footer_deltas and max(descendant_vs_footer_deltas) > 0:
        interpretation.append(
            "at least one deepest peer descendant crosses the measured footer/source "
            "start, so outer canvas allocation remains unresolved"
        )
    if direct_terminal_count and not terminal_ownership:
        interpretation.append(
            "the DOM has terminal support children, but their rendered owner "
            "allocation has not been implemented"
        )
    if (
        terminal_ownership
        and terminal_gaps
        and min(terminal_gaps) < 0
        and terminal_owner_deltas
        and max(terminal_owner_deltas) <= 0
    ):
        interpretation.append(
            "terminal support is contained by its owners, while the upper stack "
            "still intersects that support; calibrate the upper allocation and "
            "whole-canvas budget before treating the peer organization as failed"
        )
    elif terminal_owner_deltas and max(terminal_owner_deltas) > 0:
        interpretation.append(
            "terminal support still extends beyond at least one owner, so its "
            "allocation is not yet closed"
        )
    if current_support == original_support:
        interpretation.append(
            "authorized support-copy demand remains untested because the wording is unchanged"
        )
    if ineffective_role_calibrations:
        unresolved_roles = ", ".join(ineffective_role_calibrations)
        interpretation.append(
            f"the {unresolved_roles} edits did not reduce their rendered line "
            "demand, so changed-root count and aggregate support reduction do "
            "not establish effective calibration of that role"
        )
    if not interpretation:
        interpretation.append(
            "judge the current family from these measured relations and the full render"
        )

    relation_detail = "not identified"
    if terminal_gaps and terminal_owner_deltas:
        relation_detail = (
            f"upper/support gap {range_text(terminal_gaps)}; "
            f"support-vs-owner-bottom {range_text(terminal_owner_deltas)}"
        )
    branch_demand_detail = "not identified"
    if upper_branch_demands and terminal_branch_heights:
        branch_demand_detail = (
            f"upper branch demand {range_text(upper_branch_demands)}; "
            f"terminal branch height {range_text(terminal_branch_heights)}"
        )

    incomplete_levers: list[str] = []
    if upstream_bottom is not None and upstream_bottom > first_peer_top:
        incomplete_levers.append("upstream allocation still enters the peer region")
    if direct_terminal_count and not terminal_ownership:
        incomplete_levers.append("terminal ownership is not implemented")
    if current_support == original_support:
        incomplete_levers.append("authorized support copy is unchanged")
    elif ineffective_role_calibrations:
        incomplete_levers.append(
            "role-level support calibration is ineffective for "
            + ", ".join(ineffective_role_calibrations)
        )
    elif unchanged_support_roots:
        incomplete_levers.append(
            f"support calibration is partial ({unchanged_support_roots} roots unchanged)"
        )
    hypothesis_status = (
        "current checkpoint leaves " + "; ".join(incomplete_levers)
        if incomplete_levers
        else "current checkpoint changed the named allocation levers; judge the measured result"
    )

    next_strategy_note = ""
    if len(row_groups) == 1 and incomplete_levers:
        branch_context = ""
        if upper_branch_demands and terminal_branch_heights:
            branch_context = (
                " The current peer measurements separate upper-role demand "
                f"({range_text(upper_branch_demands)}) from terminal-support "
                f"demand ({range_text(terminal_branch_heights)}); use those "
                "branches, their wrapping, and their ownership to judge the "
                "next edit instead of treating the deepest descendant as one "
                "indivisible block."
            )
        next_strategy_note = (
            "DASHBOARD NEXT-DECISION NOTE: the current one-row peer "
            "composition is still an incomplete hypothesis because "
            + "; ".join(incomplete_levers)
            + ". Residual overflow at this checkpoint therefore does not by "
            "itself show that the peer topology is infeasible. When a moderate "
            "same-peer revision remains credible, continue from this checkpoint "
            "by completing the missing allocation/copy/rhythm work rather than "
            "discarding it. If proposing a multi-row or matrix topology, compare "
            "the usable width and height of each complete peer with its actual "
            "role demand and expected wrapping; more total body width is not a "
            "reason to give every peer substantially less vertical room."
            + branch_context
            + " This is a high-salience strategy reminder, not a topology gate "
            "or a fixed repair recipe."
        )
    setattr(state, "_dashboard_next_strategy_note", next_strategy_note)

    history = getattr(state, "dashboard_verify_history", None)
    if history is None:
        history = []
        setattr(state, "dashboard_verify_history", history)
    prior_same_topology = [
        item for item in history
        if item.get("topology") == topology
    ]
    history_note = ""
    if prior_same_topology:
        previous = prior_same_topology[-1]
        history_note = (
            "  - Trajectory history: this peer organization was already measured "
            f"{len(prior_same_topology)} time(s); the latest prior owner/demand was "
            f"{previous.get('owner_height', 'unknown')}/{previous.get('demand_height', 'unknown')}. "
            "Reusing it is a materially new hypothesis only when usable allocation, "
            "semantic grouping, or rendered demand changes; a new plan label alone "
            "is not a different strategy.\n"
        )
    rollback_recovery_note = ""
    prior_shorter_support = next((
        item for item in reversed(prior_same_topology)
        if int(item.get("support_words", current_words) or current_words)
        < current_words
    ), None)
    if current_support == original_support and prior_shorter_support is not None:
        prior_roles = prior_shorter_support.get("support_role_metrics", {})
        role_snapshots: list[str] = []
        for role in ("metric explanations", "terminal support"):
            role_metrics = prior_roles.get(role, {})
            if not role_metrics:
                continue
            role_snapshots.append(
                f"{role} {int(role_metrics.get('words', 0))} words/"
                f"{int(role_metrics.get('lines', 0))} lines "
                f"({role_metrics.get('calibration', 'status not recorded')})"
            )
        rollback_recovery_note = (
            "  - Rollback recovery context: an earlier same-topology checkpoint "
            "had shorter support copy before geometry and copy were rolled back "
            "together"
            + (": " + "; ".join(role_snapshots) if role_snapshots else "")
            + ". The current original wording therefore does not test the "
            "authorized copy-calibrated hypothesis. Reapply transferable copy "
            "as a standalone checkpoint, strengthening any role whose rendered "
            "line demand had not retreated, before using this restored baseline "
            "as evidence against the peer topology.\n"
        )
    ownership_comparison_note = ""
    prior_attached = next((
        item for item in reversed(prior_same_topology)
        if int(item.get("direct_terminal_count", 0) or 0) > 0
    ), None)
    if direct_terminal_count == 0 and prior_attached is not None:
        prior_metric = (
            prior_attached.get("support_role_metrics", {})
            .get("metric explanations", {})
        )
        current_metric = role_history_metrics.get("metric explanations", {})
        prior_fonts = list(prior_metric.get("font_sizes", []))
        current_fonts = list(current_metric.get("font_sizes", []))
        ownership_comparison_note = (
            "  - Candidate ownership comparison: terminal support has moved from "
            "direct in-peer ownership to a detached region. Metric explanations "
            f"changed from {int(prior_metric.get('lines', 0))} to "
            f"{int(current_metric.get('lines', 0))} rendered lines and from "
            f"{compact_range(prior_fonts, 'px')} to "
            f"{compact_range(current_fonts, 'px')} text scale. A detached parallel "
            "support row is not stronger merely because it is contained; compare "
            "whether it materially improves readable hierarchy, wrapping, and "
            "peer-to-support ownership over the attached checkpoint.\n"
        )
    history.append({
        "topology": topology,
        "owner_height": range_text(owner_heights),
        "demand_height": range_text(demand_heights),
        "terminal_ownership": terminal_ownership,
        "direct_terminal_count": direct_terminal_count,
        "terminal_gap": range_text(terminal_gaps),
        "support_words": current_words,
        "support_copy_changed": current_support != original_support,
        "support_role_metrics": role_history_metrics,
    })

    return "\n".join([
        "DASHBOARD DECISION SUMMARY (causal measurements; not a pass/fail gate):",
        f"  - Peer organization: {topology}.",
        f"  - Hypothesis completeness: {hypothesis_status}.",
        (
            "  - Repeated owner demand: owner height "
            f"{range_text(owner_heights)}; deepest descendant demand "
            f"{range_text(demand_heights)}; descendant-vs-owner delta "
            f"{range_text(demand_deltas)}."
        ),
        "  - Whole-canvas sequence: " + "; ".join(budget_parts) + ".",
        "  - Usable peer-to-footer budget: " + usable_budget_detail + ".",
        f"  - Direct terminal child: {terminal_coverage}.",
        f"  - Terminal ownership implemented: {ownership_detail}.",
        f"  - Upper/terminal relation: {relation_detail}.",
        f"  - Upper/terminal branch demand: {branch_demand_detail}.",
        f"  - Support copy materially shortened: {copy_status}.",
        f"  - Support demand by role: {support_role_detail}.",
        history_note.rstrip(),
        rollback_recovery_note.rstrip(),
        ownership_comparison_note.rstrip(),
        "  - Decision cue: " + "; ".join(interpretation) + ".",
        (
            "  A topology is not disproved by a checkpoint that never tested "
            "the intended upstream allocation, terminal ownership, or changed "
            "copy demand. An alternate topology remains valid when its final "
            "geometry and semantic ownership are better."
        ),
    ]).replace("\n\n  - Decision cue:", "\n  - Decision cue:")


def dashboard_allocation_map(spatial_state) -> str:
    """Describe repeated-card allocation and container descendant extents.

    This is explanatory geometry for the repair agent, not a detector or
    acceptance gate. It exposes support regions that intersect their upper
    stack and parents whose descendants retain a larger rendered extent.
    """
    blocks = list(getattr(spatial_state, "blocks", []) or [])
    if not blocks:
        return ""

    # Ordinary blocks intentionally exclude elements that are completely
    # outside the canvas. Rehydrate only their semantic/geometry identity
    # for ownership diagnostics; these auxiliary blocks never enter the
    # overlap detector or occupancy map.
    visible_paths = {
        block.dom_path for block in blocks if getattr(block, "dom_path", "")
    }
    off_canvas_blocks: list[ContentBlock] = []
    for index, element in enumerate(
        getattr(spatial_state, "off_canvas_elements", []) or [], 1
    ):
        dom_path = str(element.get("domPath") or "")
        if not dom_path or dom_path in visible_paths:
            continue
        classes = str(element.get("classes") or "")
        class_tokens = tuple(sorted({
            item.lower() for item in classes.split() if item
        }))
        tag = str(element.get("tag") or "div")
        selector = (
            f"#{element['id']}" if element.get("id")
            else f".{class_tokens[0]}" if class_tokens
            else tag
        )
        text_value = str(element.get("text") or element.get("fullText") or "")
        off_canvas_blocks.append(ContentBlock(
            block_id=f"off_canvas_{index:02d}",
            var_name=tag,
            shape_type="shape" if not text_value else "textbox",
            css_selector=selector,
            css_classes=class_tokens,
            dom_path=dom_path,
            bbox_px=(
                int(element.get("x") or 0),
                int(element.get("y") or 0),
                int(element.get("w") or 0),
                int(element.get("h") or 0),
            ),
            rendered_lines=int(element.get("renderedLines") or 0),
            text_lines=text_value.split("\n")[:10] if text_value else [],
        ))
    semantic_blocks = blocks + off_canvas_blocks

    def class_label(block) -> str:
        classes = tuple(getattr(block, "css_classes", ()) or ())
        if classes:
            return "." + ".".join(classes)
        return str(getattr(block, "css_selector", "") or block.var_name)

    def descendants(container) -> list:
        prefix = f"{container.dom_path}/"
        return [
            block for block in semantic_blocks
            if block is not container
            and block.dom_path
            and block.dom_path.startswith(prefix)
        ]

    def direct_branch(container_path: str, descendant_path: str) -> str:
        prefix = f"{container_path}/"
        if not descendant_path.startswith(prefix):
            return ""
        first = descendant_path[len(prefix):].split("/", 1)[0]
        return prefix + first

    card_terms = ("card", "tile", "panel")
    support_terms = (
        "finding", "takeaway", "support", "insight", "callout",
        "conclusion", "recommendation",
    )
    name_terms = ("name", "card-title", "item-title", "profile-title")
    metric_note_terms = (
        "m-note", "metric-note", "metric_note", "explanation",
        "description", "detail", "subtext", "support-copy",
    )

    def member_matches(member, terms: tuple[str, ...]) -> bool:
        tokens = tuple(
            str(name).lower()
            for name in tuple(getattr(member, "css_classes", ()) or ())
        ) or (str(getattr(member, "css_selector", "") or "").lower(),)
        return any(term in token for token in tokens for term in terms)

    def member_preview(member, limit: int = 54) -> str:
        text = " ".join(getattr(member, "text_lines", []) or [])
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > limit:
            text = text[: limit - 1].rstrip() + "…"
        return text

    def member_measurement(member) -> str:
        mx, my, mw, mh = member.bbox_px
        lines_count = int(getattr(member, "rendered_lines", 0) or 0)
        preview = member_preview(member)
        detail = (
            f"{class_label(member)} bbox=({mx},{my}) {mw}x{mh}px"
            f", rendered lines={lines_count}"
        )
        if preview:
            detail += f', text="{preview}"'
        return detail

    def rectangles_intersect(first, second) -> bool:
        fx, fy, fw, fh = first.bbox_px
        sx, sy, sw, sh = second.bbox_px
        return (
            min(fx + fw, sx + sw) > max(fx, sx)
            and min(fy + fh, sy + sh) > max(fy, sy)
        )

    card_groups: dict[tuple[str, str, tuple[str, ...]], list] = {}
    for block in blocks:
        classes = tuple(getattr(block, "css_classes", ()) or ())
        normalized_classes = tuple(sorted(str(name).lower() for name in classes))
        if not normalized_classes:
            continue
        if not any(
            term in class_name
            for class_name in normalized_classes
            for term in card_terms
        ):
            continue
        key = (dom_parent_path(block.dom_path), block.var_name, normalized_classes)
        card_groups.setdefault(key, []).append(block)

    repeated_groups = [
        sorted(group, key=lambda block: block.bbox_px[0])
        for group in card_groups.values()
        if len(group) >= 2
    ]
    repeated_groups.sort(key=lambda group: (-len(group), group[0].bbox_px[1]))

    lines: list[str] = []
    if repeated_groups:
        lines.extend([
            "REPEATED CARD ALLOCATION MAP (measurement only; not a defect verdict):",
            "  upper/support gap is support top minus the lowest rendered upper-content edge; a negative value means those current rendered regions intersect.",
        ])
        for group_index, group in enumerate(repeated_groups[:3], 1):
            lines.append(
                f"  C{group_index}: {len(group)} repeated {class_label(group[0])} peers"
            )
            for card_index, card in enumerate(group[:6], 1):
                card_descendants = descendants(card)
                branches: dict[str, list] = {}
                for block in card_descendants:
                    branch = direct_branch(card.dom_path, block.dom_path)
                    if branch:
                        branches.setdefault(branch, []).append(block)

                support_branches = {
                    branch for branch, members in branches.items()
                    if any(
                        any(term in class_name.lower() for term in support_terms)
                        for member in members
                        for class_name in (
                            tuple(getattr(member, "css_classes", ()) or ())
                            or (str(getattr(member, "css_selector", "") or ""),)
                        )
                    )
                }
                support_members = [
                    member for branch in support_branches
                    for member in branches.get(branch, [])
                ]
                support_branch_roots = []
                for branch in support_branches:
                    members = branches.get(branch, [])
                    root = next(
                        (member for member in members if member.dom_path == branch),
                        None,
                    )
                    if root is None and members:
                        root = min(
                            members,
                            key=lambda member: (
                                member.dom_path.count("/"),
                                member.bbox_px[1],
                            ),
                        )
                    if root is not None:
                        support_branch_roots.append(root)
                upper_members = [
                    member for branch, members in branches.items()
                    if branch not in support_branches
                    for member in members
                ]

                upper_branch_groups = {
                    branch: members
                    for branch, members in branches.items()
                    if branch not in support_branches
                }
                if len(upper_branch_groups) == 1:
                    only_branch, only_members = next(iter(upper_branch_groups.items()))
                    branch_root = next(
                        (
                            member for member in only_members
                            if member.dom_path == only_branch
                        ),
                        None,
                    )
                    root_role = (
                        " ".join(
                            str(name).lower()
                            for name in tuple(
                                getattr(branch_root, "css_classes", ()) or ()
                            )
                        )
                        if branch_root is not None else ""
                    )
                    if any(
                        term in root_role
                        for term in ("main", "upper", "body", "content")
                    ):
                        nested_groups: dict[str, list] = {}
                        for member in only_members:
                            if member is branch_root:
                                continue
                            nested = direct_branch(only_branch, member.dom_path)
                            if nested:
                                nested_groups.setdefault(nested, []).append(member)
                        if nested_groups:
                            upper_branch_groups = nested_groups

                _, cy, _, ch = card.bbox_px
                card_bottom = cy + ch
                upper_bottom = max(
                    (member.bbox_px[1] + member.bbox_px[3] for member in upper_members),
                    default=cy,
                )
                deepest_upper = max(
                    upper_members,
                    key=lambda member: (
                        member.bbox_px[1] + member.bbox_px[3],
                        member.dom_path.count("/"),
                        bool(member_preview(member)),
                    ),
                    default=None,
                )
                metric_note_members = [
                    member for member in upper_members
                    if member_matches(member, metric_note_terms)
                ]
                name_block = next((
                    member for member in card_descendants
                    if any(
                        term == class_name.lower() or term in class_name.lower()
                        for class_name in tuple(getattr(member, "css_classes", ()) or ())
                        for term in name_terms
                    )
                ), None)
                label = (
                    " ".join(name_block.text_lines).strip()[:42]
                    if name_block is not None else ""
                ) or f"peer {card_index}"

                base = (
                    f'    - "{label}": card y={cy}..{card_bottom}px; '
                    f"upper content bottom={upper_bottom}px"
                )
                if support_members:
                    support_top = min(member.bbox_px[1] for member in support_members)
                    support_bottom = max(
                        member.bbox_px[1] + member.bbox_px[3]
                        for member in support_members
                    )
                    base += (
                        f"; support y={support_top}..{support_bottom}px; "
                        f"upper/support gap={support_top - upper_bottom:+d}px; "
                        f"support vs card bottom={support_bottom - card_bottom:+d}px"
                    )
                    if any(
                        member.block_id.startswith("off_canvas_")
                        for member in support_members
                    ):
                        base += "; support branch extends outside the canvas"
                else:
                    descendant_bottom = max(
                        (
                            member.bbox_px[1] + member.bbox_px[3]
                            for member in card_descendants
                        ),
                        default=card_bottom,
                    )
                    base += (
                        "; no explicit support/takeaway branch identified; "
                        f"descendant vs card bottom={descendant_bottom - card_bottom:+d}px"
                    )
                if name_block is not None:
                    nx, ny, nw, nh = name_block.bbox_px
                    line_info = (
                        f", rendered lines={name_block.rendered_lines}"
                        if name_block.rendered_lines > 0 else ""
                    )
                    base += f"; name bbox=({nx},{ny}) {nw}x{nh}px{line_info}"
                lines.append(base)

                if metric_note_members:
                    lines.append(
                        "      repeated upper support roles: "
                        + " | ".join(
                            member_measurement(member)
                            for member in sorted(
                                metric_note_members,
                                key=lambda member: (
                                    member.bbox_px[1], member.bbox_px[0]
                                ),
                            )[:8]
                        )
                    )
                if deepest_upper is not None:
                    lines.append(
                        "      deepest upper contributor: "
                        + member_measurement(deepest_upper)
                    )
                if support_branch_roots:
                    terminal_parts = []
                    for root in support_branch_roots[:4]:
                        branch_members = branches.get(root.dom_path, [root])
                        rendered_line_total = sum(
                            int(getattr(member, "rendered_lines", 0) or 0)
                            for member in branch_members
                            if member is root or not any(
                                other is not member
                                and other.dom_path.startswith(f"{member.dom_path}/")
                                for other in branch_members
                            )
                        )
                        _, root_y, _, root_h = root.bbox_px
                        root_bottom = root_y + root_h
                        terminal_parts.append(
                            f"{class_label(root)} direct-child=yes, "
                            f"box={root_y}..{root_bottom}px (height={root_h}px), "
                            f"rendered leaf lines={rendered_line_total}, "
                            f"bottom-vs-card={root_bottom - card_bottom:+d}px"
                        )
                    lines.append(
                        "      terminal ownership: " + " | ".join(terminal_parts)
                    )
                if support_members:
                    intersecting_upper = [
                        member for member in upper_members
                        if any(
                            rectangles_intersect(member, support)
                            for support in support_branch_roots or support_members
                        )
                    ]
                    if intersecting_upper:
                        lines.append(
                            "      exact upper/terminal intersections: "
                            + " | ".join(
                                member_measurement(member)
                                for member in sorted(
                                    intersecting_upper,
                                    key=lambda member: (
                                        -(member.bbox_px[1] + member.bbox_px[3]),
                                        -member.dom_path.count("/"),
                                    ),
                                )[:6]
                            )
                        )
                    else:
                        lines.append(
                            "      exact upper/terminal intersections: none in current rendered bboxes"
                        )

                branch_parts: list[str] = []
                for branch, members in list(upper_branch_groups.items())[:6]:
                    root = next(
                        (member for member in members if member.dom_path == branch),
                        None,
                    )
                    if root is None:
                        root = min(
                            members,
                            key=lambda member: (
                                member.dom_path.count("/"),
                                member.bbox_px[1],
                            ),
                        )
                    _, root_y, _, root_h = root.bbox_px
                    root_bottom = root_y + root_h
                    descendant_top = min(member.bbox_px[1] for member in members)
                    descendant_bottom = max(
                        member.bbox_px[1] + member.bbox_px[3]
                        for member in members
                    )
                    part = (
                        f"{class_label(root)} box={root_y}..{root_bottom}px, "
                        f"rendered={descendant_top}..{descendant_bottom}px"
                    )
                    if descendant_bottom > root_bottom:
                        part += f" ({descendant_bottom - root_bottom:+d}px past box)"

                    child_groups: dict[str, list] = {}
                    for member in members:
                        if member is root:
                            continue
                        child_branch = direct_branch(root.dom_path, member.dom_path)
                        if child_branch:
                            child_groups.setdefault(child_branch, []).append(member)
                    if len(child_groups) >= 2:
                        child_parts: list[str] = []
                        for child_branch, child_members in list(child_groups.items())[:4]:
                            child_root = next(
                                (
                                    member for member in child_members
                                    if member.dom_path == child_branch
                                ),
                                None,
                            )
                            if child_root is None:
                                child_root = min(
                                    child_members,
                                    key=lambda member: (
                                        member.dom_path.count("/"),
                                        member.bbox_px[1],
                                    ),
                                )
                            _, child_y, _, child_h = child_root.bbox_px
                            child_bottom = child_y + child_h
                            child_descendant_bottom = max(
                                member.bbox_px[1] + member.bbox_px[3]
                                for member in child_members
                            )
                            child_summary = (
                                f"{class_label(child_root)} {child_y}..{child_bottom}px"
                            )
                            if child_descendant_bottom > child_bottom:
                                child_summary += (
                                    f" -> descendants {child_descendant_bottom}px"
                                )
                            child_parts.append(child_summary)
                        part += "; children=[" + ", ".join(child_parts) + "]"
                    branch_parts.append(part)
                if branch_parts:
                    lines.append(
                        "      upper branch extents: " + " | ".join(branch_parts)
                    )
        lines.append(
            "  Use this map to test the current allocation hypothesis. It does not require anchoring, equal heights, or any fixed gap; it exposes when the rendered result contradicts the intended ownership of upper and support roles."
        )
        lines.append(
            "  Read the two relations separately. If the support branch is contained by its card but the upper/support gap is negative, the terminal allocation may already be working while the upper repeated stack still exceeds its share; diagnose and recalibrate that upper stack and the whole-slide body budget before declaring the strategy non-convergent. If support itself extends below the card, its reservation or owning-card allocation is not yet complete. A negative gap alone is not a rollback verdict."
        )
        lines.append(
            "  Strategy cue: when every peer has a terminal support branch, first compare a reserved in-card support zone (with the upper stack fitted above it) against changing the peer topology. A wider multi-row card is not automatically more spacious: justify a topology change from each peer's actual rendered allocation and wrapping, not from total body width."
        )

    repeated_ids = {id(block) for group in repeated_groups for block in group}
    extent_terms = (
        "summary", "mini", "hero", "ranking", "table-wrap", "notes",
        "rail", "side", "dashboard", "overview",
    )
    extent_rows: list[str] = []
    for container in blocks:
        if id(container) in repeated_ids:
            continue
        classes = tuple(getattr(container, "css_classes", ()) or ())
        role = " ".join(str(name).lower() for name in classes)
        if not role or not any(term in role for term in extent_terms):
            continue
        members = descendants(container)
        if not members:
            continue
        x, y, width, height = container.bbox_px
        parent_right = x + width
        parent_bottom = y + height
        descendant_right = max(
            member.bbox_px[0] + member.bbox_px[2] for member in members
        )
        descendant_top = min(member.bbox_px[1] for member in members)
        descendant_bottom = max(
            member.bbox_px[1] + member.bbox_px[3] for member in members
        )
        lowest_member = max(
            members,
            key=lambda member: member.bbox_px[1] + member.bbox_px[3],
        )
        extent_rows.append(
            f"  - {class_label(container)}: box right/bottom={parent_right}/{parent_bottom}px; "
            f"descendants reach={descendant_right}/{descendant_bottom}px; "
            f"delta={descendant_right - parent_right:+d}px horizontal, "
            f"{descendant_bottom - parent_bottom:+d}px vertical; "
            f"rendered child span y={descendant_top}..{descendant_bottom}px; "
            f"lowest contributor={class_label(lowest_member)}"
        )
    if extent_rows:
        if lines:
            lines.append("")
        lines.append(
            "CONTAINER DESCENDANT EXTENT MAP (measurement only; shrinking a parent does not shrink these rendered descendants):"
        )
        lines.extend(extent_rows[:8])
        lines.append(
            "  For vertical reallocation, compare the maximum rendered descendant bottom across upstream siblings with the next region's start. Declared parent heights are not reclaimed space until the child edge retreats too."
        )

    return "\n".join(lines)


def dashboard_fit_magnitude_cue(spatial_text: str) -> str:
    """Summarize owning-container height deficits without imposing a gate."""
    pattern = re.compile(
        r'❌ TEXT OVERFLOW: [^\n]*\[(?P<role>[^\]\n]+)\]\n'
        r'\s*scrollHeight: (?P<scroll>\d+)px \| clientHeight: '
        r'(?P<client>\d+)px \| overflow: (?P<overflow>\d+)px vertical',
    )
    container_terms = (
        "wrap", "content", "body", "table", "ranking", "summary",
        "notes", "side", "rail", "grid", "panel", "card", "list",
    )
    measurements: list[tuple[float, str, int, int, int]] = []
    seen: set[str] = set()
    for match in pattern.finditer(str(spatial_text or "")):
        role = match.group("role").strip()
        role_low = role.lower()
        if role_low in {".slide", "slide", "tr", "td", "th"}:
            continue
        if not any(term in role_low for term in container_terms):
            continue
        client = int(match.group("client"))
        scroll = int(match.group("scroll"))
        overflow = int(match.group("overflow"))
        if client <= 0 or overflow <= 0 or role in seen:
            continue
        seen.add(role)
        measurements.append((scroll / client, role, scroll, client, overflow))

    if not measurements:
        return ""
    measurements.sort(reverse=True)
    lines = [
        "FIT MAGNITUDE CUE (measurement only; not a target or gate):",
    ]
    for ratio, role, scroll, client, overflow in measurements[:5]:
        lines.append(
            f"- {role}: intrinsic content height {scroll}px inside {client}px "
            f"({overflow}px currently unallocated; about {ratio:.1f}x the allocation)."
        )
    lines.append(
        "Before choosing a small fit pass, ask whether the combined edits could "
        "plausibly absorb the reported order of deficit while preserving every "
        "role. A few pixels taken from one-time chrome cannot by themselves close "
        "a large repeated-content deficit; inspect cumulative row/card rhythm, "
        "wrapping, and the owning track. This does not freeze the current body "
        "start: a coherent repair may combine meaningful upstream space recovery "
        "with repeated-role calibration when neither is sufficient alone. The "
        "ratios describe the current state, not desired dimensions.\n\n"
    )
    return "\n".join(lines)


def dashboard_local_first_html_edit_message(
    edits: list[dict],
    state: AgentState,
) -> str | None:
    """Return a non-blocking strategy cue for dashboard scaffold edits."""
    if not _agent_repair_cls()._is_html_code(str(getattr(state, "current_code", "") or "")):
        return None
    if not looks_like_table_dashboard_pressure(state):
        return None

    blob = _agent_repair_cls()._html_edit_blob(edits)
    scaffold_names = ("slide", "header", "footer", "content", "title", "subtitle", "badge")
    touched_scaffold = [
        f".{name}" for name in scaffold_names
        if _agent_repair_cls()._mentions_class_or_selector(blob, name)
    ]
    if not touched_scaffold:
        return None
    shown = ", ".join(touched_scaffold[:5])
    return (
        "\n\nDASHBOARD STRATEGY CUE: this edit touches surrounding scaffold "
        f"({shown}). That is allowed. Confirm from current revision evidence that these "
        "regions causally constrain the named body failure, and check after the "
        "edit that hierarchy and unrelated chrome did not regress. There is no "
        "required local-first ordering; choose local calibration or reflow from "
        "the evidence and verify the resulting hypothesis."
    )


def dashboard_table_outer_frame_warning_from_edits(
    edits: list[dict],
    state: AgentState,
) -> str:
    """Offer a non-blocking causal check for table-frame edits."""
    code = str(getattr(state, "current_code", "") or "")
    if not _agent_repair_cls()._is_html_code(code):
        return ""
    if not looks_like_table_dashboard_pressure(state):
        return ""

    blob = _agent_repair_cls()._html_edit_blob(edits)
    touches_table_frame = (
        _agent_repair_cls()._mentions_class_or_selector(blob, "table-wrap")
        or bool(re.search(r"(?<![\w-])table\s*[,{.#:>]", blob))
    )
    changes_outer_fit = bool(
        re.search(r"\b(?:height|max-height|min-height|overflow)\s*:", blob)
    )
    selector_chunks = re.findall(
        r"(?m)(?:^|})\s*([^{}]+)\{",
        blob,
    )
    touches_cell_selector = any(
        re.search(
            r"(?<![\w-])(?:thead|tbody|tr|th|td)(?![\w-])",
            selector,
        )
        for selector in selector_chunks
    )
    touches_rhythm_prop = any(
        prop in blob
        for prop in ("font-size", "line-height", "padding", "border-spacing")
    )
    if touches_table_frame and changes_outer_fit and not (
        touches_cell_selector and touches_rhythm_prop
    ):
        return (
            "\n\nDASHBOARD TABLE CAUSAL CHECK: this edit changes the outer "
            "table region without changing its internal row/cell rhythm. "
            "That may be correct, but verify whether the original failure was "
            "caused by the frame, the internal rhythm, or a sibling region. "
            "Use the next revision's spatial state, plus preview when enabled, to choose the next direction; "
            "do not assume either the frame or the rows must change."
        )
    return ""


def dashboard_coupled_cluster_warning_from_edits(
    edits: list[dict],
    state: AgentState,
) -> str:
    """Offer a non-blocking shared-pressure hypothesis for table-only edits."""
    code = str(getattr(state, "current_code", "") or "")
    if not _agent_repair_cls()._is_html_code(code):
        return ""
    if not looks_like_table_dashboard_pressure(state):
        return ""

    blob = _agent_repair_cls()._html_edit_blob(edits)
    touches_table = (
        _agent_repair_cls()._mentions_class_or_selector(blob, "table-wrap")
        or bool(re.search(r"(?<![\w-])table\s*[,{.#:>]", blob))
        or any(token in blob for token in ("thead", "tbody", " td", " th"))
    )
    if not touches_table:
        return ""

    touches_notes = any(
        _agent_repair_cls()._mentions_class_or_selector(blob, name)
        for name in ("notes", "mini")
    )
    touches_right_rail = any(
        _agent_repair_cls()._mentions_class_or_selector(blob, name)
        for name in (
            "side", "hero", "ranking", "pill", "summary",
            "summary-grid", "summary-box",
        )
    )
    if touches_notes or touches_right_rail:
        return ""

    return (
        "\n\nDASHBOARD SHARED-PRESSURE CHECK: this edit changes the table "
        "without nearby support regions. A clipped table can be local, or it "
        "can be one symptom of a shared body constraint. After verification, "
        "compare the table and its siblings and decide which explanation fits "
        "the current revision evidence. Continue locally when the defect is isolated; "
        "consider track reallocation or reflow when pressure is shared."
    )


def dashboard_coupled_plan_notes(
    steps: list[PlanStep],
    state: AgentState,
    summary: str = "",
) -> list[str]:
    """Offer a direction cue when a plan may split shared dashboard pressure."""
    if not steps:
        return []

    step_texts = [str(getattr(step, "text", "") or "") for step in steps]
    combined = " ".join([str(summary or ""), *step_texts]).lower()
    textual_dashboard = (
        "dashboard" in combined
        and "table" in combined
        and any(term in combined for term in ("right rail", "right-rail", "ranking", "summary", "hero", "kpi"))
    )
    if not (looks_like_table_dashboard_pressure(state) or textual_dashboard):
        return []
    region_terms = {
        "table": ("table", "row", "cell", "thead", "tbody"),
        "notes": ("notes", "support card", "mini"),
        "rail": ("right rail", "right-rail", "ranking", "summary", "hero", "kpi"),
        "scaffold": ("header", "footer", "content track", "body track", "title"),
    }
    touched_by_step: list[set[str]] = []
    for text in step_texts:
        low = text.lower()
        touched_by_step.append({
            region
            for region, terms in region_terms.items()
            if any(term in low for term in terms)
        })

    notes: list[str] = []

    has_direct_terminal_support = False
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            str(getattr(state, "current_code", "") or ""),
            "html.parser",
        )
        for card in soup.select(".grid-card"):
            for child in card.find_all(recursive=False):
                classes = {
                    str(name).lower()
                    for name in (child.get("class") or [])
                }
                if any(
                    term in class_name
                    for class_name in classes
                    for term in ("finding", "takeaway", "support")
                ):
                    has_direct_terminal_support = True
                    break
            if has_direct_terminal_support:
                break
    except Exception:
        has_direct_terminal_support = False

    targets_repeated_support = (
        any(
            term in combined
            for term in ("card", "comparison", "peer", "repeated", "profile")
        )
        and any(
            term in combined
            for term in ("support", "finding", "takeaway")
        )
    )
    names_allocation_hypothesis = any(
        term in combined
        for term in (
            "anchor", "upper wrapper", "support track",
            "support zone", "support band", "shared band", "side rail",
            "side-rail", "internal split", "grid area", "grid-area",
            "ordinary flow", "normal flow", "in-flow", "two-column",
            "two column", "two-row", "two row", "2x2", "2×2",
            "regroup", "recompose", "detach", "content-sized",
        )
    ) or bool(re.search(
        r"\breserv(?:e|ed|ing|ation)\b",
        combined,
    )) or _agent_repair_cls()._names_role_demand_calibration(combined)
    if (
        has_direct_terminal_support
        and targets_repeated_support
        and not names_allocation_hypothesis
    ):
        compression_clause = ""
        if getattr(state, "allow_support_copy_compression", False):
            mentions_compression = any(
                term in combined
                for term in ("compress", "shorten", "condense")
            )
            if not mentions_compression:
                compression_clause = (
                    " The issue also authorizes meaning-preserving support-copy "
                    "compression, but the plan does not say whether that calibration "
                    "belongs to this same hypothesis; decide that before judging "
                    "unchanged copy against the proposed allocation."
                )
        notes.append(
            "The repeated-card step states a fit outcome but not a falsifiable "
            "role-allocation hypothesis. Before editing, name whether this attempt "
            "tests role/copy demand within the current flow, a minimal allocation "
            "for the existing terminal child, or a justified topology change. "
            "These are equal options, not a required sequence. A target card height "
            "or broad typography shrink does not identify where the terminal support "
            "branch gets its space; "
            "do not use a failed verify to reject the whole comparison topology "
            "unless the chosen allocation was actually implemented."
            + compression_clause
        )

    active = [regions for regions in touched_by_step if regions]
    if len(active) >= 2:
        combined_regions = set().union(*active)
        split_shared_regions = (
            bool({"table", "notes", "rail"} & combined_regions)
            and not any(
                len(regions & {"table", "notes", "rail"}) >= 2
                for regions in active
            )
        )
        if split_shared_regions:
            notes.append(
                "The plan handles dashboard regions in separate steps. Before editing, "
                "use the render and spatial state to decide whether those regions are "
                "independent defects or symptoms of one shared constraint. If they are "
                "independent, a serial plan is appropriate. If they share pressure, keep "
                "one causal hypothesis across the sequence and verify that each step "
                "creates space rather than merely moving the conflict. Treat a locally "
                "improved subregion as provisional while changing neighboring regions can "
                "still alter its available space; do not freeze its geometry merely because "
                "one local symptom disappeared. This is a strategy cue, not a requirement "
                "to merge the steps or use a fixed topology."
            )
    return notes


def is_recoverable_dashboard_dominant_compression(
    state: AgentState,
    compression_reason: str,
) -> bool:
    """Allow a local focal-scale correction before rejecting a whole batch.

    The final dispatcher still applies the full compression gate. Inside the
    repair loop, a dense dashboard checkpoint may contain useful table/card
    calibration plus one over-shrunk hero. That should prompt a direct hero
    correction, not destroy the whole coupled checkpoint.
    """
    return (
        looks_like_table_dashboard_pressure(state)
        and str(compression_reason or "").startswith("dominant font shrank")
    )
