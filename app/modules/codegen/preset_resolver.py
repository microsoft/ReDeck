"""Preset Layout Resolver — maps slide roles to recommended layout configurations.

Addresses the need for selecting layouts by narrative role.

Instead of 20 separate JSON files, this module provides a structured
lookup of layout presets keyed by narrative role. Each preset includes:
- Recommended layouts (ordered by preference)
- Default layout_params
- Content density guidance
- Style mood (for the codegen model)

The layout designer LLM uses this as additional context when deciding
which layout template to use.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LayoutPreset:
    """A preset layout configuration for a slide role."""
    role: str
    recommended_layouts: list[str]       # ordered by preference
    default_params: dict[str, Any] = field(default_factory=dict)
    max_bullet_count: int = 5
    max_content_blocks: int = 4
    style_mood: str = "professional"     # professional, impactful, dense, clean
    preferred_viz_type: str | None = None  # chart, table, image, flowchart, None
    description: str = ""


# ════════════════════════════════════════════════════════════════════
# PRESET CATALOG
# ════════════════════════════════════════════════════════════════════

PRESET_CATALOG: dict[str, LayoutPreset] = {
    "title": LayoutPreset(
        role="title",
        recommended_layouts=["A"],
        max_bullet_count=0,
        max_content_blocks=3,
        style_mood="impactful",
        description="Magazine-cover style. Dark background, large title, one key insight card.",
    ),
    "introduction": LayoutPreset(
        role="introduction",
        recommended_layouts=["C", "G", "I", "H"],
        default_params={"column_ratio": 0.45, "split_position": 0.45},
        max_bullet_count=4,
        max_content_blocks=3,
        style_mood="clean",
        description="High-level context setting. Prefer two-column with figure if available.",
    ),
    "motivation": LayoutPreset(
        role="motivation",
        recommended_layouts=["G", "C", "I"],
        default_params={"split_position": 0.4},
        max_bullet_count=4,
        max_content_blocks=3,
        style_mood="impactful",
        description="Why this work matters. Insight-driven layout preferred.",
    ),
    "background": LayoutPreset(
        role="background",
        recommended_layouts=["C", "F", "K", "H"],
        default_params={"column_ratio": 0.4, "sidebar_width": 2.5},
        max_bullet_count=4,
        max_content_blocks=3,
        style_mood="professional",
        description="Prior work context. Two-column or three-column comparison.",
    ),
    "related_work": LayoutPreset(
        role="related_work",
        recommended_layouts=["F", "C", "E"],
        max_bullet_count=4,
        max_content_blocks=4,
        style_mood="professional",
        preferred_viz_type="table",
        description="Compare approaches. Use columns or table for structure.",
    ),
    "method": LayoutPreset(
        role="method",
        recommended_layouts=["B", "H", "K", "C"],
        default_params={"column_ratio": 0.35, "sidebar_width": 2.5, "image_size": "large"},
        max_bullet_count=4,
        max_content_blocks=3,
        style_mood="clean",
        preferred_viz_type="image",
        description="Architecture/method. Prioritize figure (60-70% of slide). Keep text minimal.",
    ),
    "architecture": LayoutPreset(
        role="architecture",
        recommended_layouts=["B", "L", "H"],
        default_params={"image_size": "large", "column_ratio": 0.3},
        max_bullet_count=3,
        max_content_blocks=2,
        style_mood="clean",
        preferred_viz_type="image",
        description="Full diagram focus. Image should dominate the slide.",
    ),
    "training": LayoutPreset(
        role="training",
        recommended_layouts=["K", "C", "I"],
        default_params={"sidebar_width": 2.5, "split_position": 0.45},
        max_bullet_count=5,
        max_content_blocks=3,
        style_mood="professional",
        preferred_viz_type="flowchart",
        description="Training details. Pipeline sidebar or step-by-step flow.",
    ),
    "results": LayoutPreset(
        role="results",
        recommended_layouts=["D", "M", "E", "J"],
        default_params={"card_height": 1.8},
        max_bullet_count=3,
        max_content_blocks=4,
        style_mood="impactful",
        preferred_viz_type="chart",
        description="Lead with NUMBERS. Metric cards + supporting context.",
    ),
    "evaluation": LayoutPreset(
        role="evaluation",
        recommended_layouts=["E", "D", "M"],
        max_bullet_count=3,
        max_content_blocks=3,
        style_mood="dense",
        preferred_viz_type="table",
        description="Detailed evaluation. Tables for precise comparisons.",
    ),
    "comparison": LayoutPreset(
        role="comparison",
        recommended_layouts=["E", "F", "J"],
        max_bullet_count=4,
        max_content_blocks=4,
        style_mood="professional",
        preferred_viz_type="table",
        description="Structured comparison. Every cell must be filled.",
    ),
    "ablation": LayoutPreset(
        role="ablation",
        recommended_layouts=["E", "J", "M"],
        max_bullet_count=3,
        max_content_blocks=3,
        style_mood="dense",
        preferred_viz_type="table",
        description="Ablation study. Table with clear contribution of each component.",
    ),
    "analysis": LayoutPreset(
        role="analysis",
        recommended_layouts=["C", "M", "H"],
        default_params={"column_ratio": 0.5},
        max_bullet_count=4,
        max_content_blocks=3,
        style_mood="professional",
        preferred_viz_type="chart",
        description="Deep-dive analysis. Chart + text explanation side by side.",
    ),
    "discussion": LayoutPreset(
        role="discussion",
        recommended_layouts=["C", "G", "I"],
        default_params={"split_position": 0.4},
        max_bullet_count=4,
        max_content_blocks=3,
        style_mood="clean",
        description="Discussion of implications. Balanced text + key insights.",
    ),
    "limitation": LayoutPreset(
        role="limitation",
        recommended_layouts=["C", "F", "I"],
        max_bullet_count=4,
        max_content_blocks=3,
        style_mood="professional",
        description="Limitations and future work. Honest, balanced presentation.",
    ),
    "conclusion": LayoutPreset(
        role="conclusion",
        recommended_layouts=["G", "D", "I"],
        default_params={"split_position": 0.4},
        max_bullet_count=3,
        max_content_blocks=3,
        style_mood="impactful",
        description="Final takeaway. Large font key finding. MAX 3 supporting points.",
    ),
    "takeaway": LayoutPreset(
        role="takeaway",
        recommended_layouts=["G", "D"],
        max_bullet_count=3,
        max_content_blocks=2,
        style_mood="impactful",
        description="Key insight. Quote-style layout with minimal supporting text.",
    ),
    "future_work": LayoutPreset(
        role="future_work",
        recommended_layouts=["C", "I", "F"],
        max_bullet_count=4,
        max_content_blocks=3,
        style_mood="clean",
        description="Forward-looking. Clean layout, 3-4 clear directions.",
    ),
}

# Role aliases (normalize common variant names)
ROLE_ALIASES: dict[str, str] = {
    "title_slide": "title",
    "intro": "introduction",
    "overview": "introduction",
    "context": "background",
    "prior_work": "related_work",
    "approach": "method",
    "model": "architecture",
    "pipeline": "training",
    "performance": "results",
    "benchmark": "evaluation",
    "experiment": "evaluation",
    "ablation_study": "ablation",
    "deep_dive": "analysis",
    "insight": "takeaway",
    "summary": "conclusion",
    "closing": "conclusion",
    "limitations": "limitation",
    "future": "future_work",
    "next_steps": "future_work",
}


def resolve_preset(role: str) -> LayoutPreset | None:
    """Resolve a slide role to its layout preset.

    Handles role normalization via aliases.

    Args:
        role: Slide role string (e.g., "introduction", "results", "method")

    Returns:
        LayoutPreset or None if no preset matches
    """
    normalized = role.lower().strip().replace(" ", "_").replace("-", "_")
    # Check direct match
    if normalized in PRESET_CATALOG:
        return PRESET_CATALOG[normalized]
    # Check aliases
    if normalized in ROLE_ALIASES:
        return PRESET_CATALOG.get(ROLE_ALIASES[normalized])
    # Fuzzy: check if any preset role is a substring of the input
    for preset_role, preset in PRESET_CATALOG.items():
        if preset_role in normalized or normalized in preset_role:
            return preset
    return None


def format_preset_guidance(role: str, used_layouts: list[str] | None = None) -> str:
    """Format preset as guidance text for the layout designer LLM.

    Args:
        role: Slide role
        used_layouts: Layouts already used by previous slides (for diversity)

    Returns:
        Formatted guidance string, or empty string if no preset found
    """
    preset = resolve_preset(role)
    if not preset:
        return ""

    lines = [f"## Preset Guidance for role='{role}'"]
    lines.append(f"**Style mood**: {preset.style_mood}")
    lines.append(f"**Description**: {preset.description}")

    # Filter out already-used layouts for diversity
    available = preset.recommended_layouts
    if used_layouts:
        filtered = [l for l in available if l not in used_layouts]
        if filtered:
            available = filtered
            lines.append(f"**Recommended layouts** (avoiding repeats): {', '.join(available)}")
        else:
            lines.append(f"**Recommended layouts**: {', '.join(available)} (all have been used, pick least recent)")
    else:
        lines.append(f"**Recommended layouts**: {', '.join(available)}")

    lines.append(f"**Max bullets per list**: {preset.max_bullet_count}")
    lines.append(f"**Max content blocks**: {preset.max_content_blocks}")

    if preset.preferred_viz_type:
        lines.append(f"**Preferred visualization**: {preset.preferred_viz_type}")

    if preset.default_params:
        params_str = ", ".join(f"{k}={v}" for k, v in preset.default_params.items())
        lines.append(f"**Suggested params**: {params_str}")

    return "\n".join(lines)
