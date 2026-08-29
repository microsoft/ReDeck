"""Match deck theme to paper figure colors for visual harmony.

Extracts dominant colors from paper figures, then selects the
pre-defined ThemeColors palette that best harmonizes with them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.themes import ThemeColors

logger = logging.getLogger(__name__)


def _extract_figure_colors(figure_paths: list[Path], max_figures: int = 5) -> list[tuple[int, int, int]]:
    """Extract dominant non-gray colors from paper figures.

    Returns up to 5 dominant (R, G, B) tuples, excluding near-gray/white/black.
    """
    try:
        from PIL import Image
        import numpy as np
        from collections import Counter
    except ImportError:
        return []

    all_colors: Counter = Counter()

    for fig_path in figure_paths[:max_figures]:
        try:
            img = Image.open(fig_path).convert("RGB").resize((80, 80))
            pixels = np.array(img).reshape(-1, 3)
            # Quantize to 32-step bins
            quantized = (pixels // 32) * 32 + 16  # center of bin
            for c in quantized:
                all_colors[tuple(c.tolist())] += 1
        except Exception:
            continue

    if not all_colors:
        return []

    # Filter out near-gray, near-white, near-black
    def _is_chromatic(rgb: tuple[int, int, int]) -> bool:
        r, g, b = rgb
        # Skip near-white
        if r > 200 and g > 200 and b > 200:
            return False
        # Skip near-black
        if r < 40 and g < 40 and b < 40:
            return False
        # Skip near-gray (all channels within 25 of each other)
        if max(r, g, b) - min(r, g, b) < 30:
            return False
        return True

    chromatic = [(c, n) for c, n in all_colors.most_common(30) if _is_chromatic(c)]
    return [c for c, _ in chromatic[:5]]


def _color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """Simple Euclidean distance in RGB space."""
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def select_theme_by_figures(
    figure_paths: list[Path],
    available_themes: dict[str, "ThemeColors"] | None = None,
) -> str | None:
    """Select the best-matching theme based on figure colors.

    Returns the theme name, or None if no good match (fallback to default selection).
    """
    from app.themes import THEME_REGISTRY

    # Only match against curated themes (better visual harmony)
    themes = {k: v for k, v in (available_themes or THEME_REGISTRY).items()
              if getattr(v, 'style_family', '') in ('demo_curated', 'demo_curated_dark', '')}
    if not themes:
        return None

    figure_colors = _extract_figure_colors(figure_paths)
    if not figure_colors:
        return None

    logger.info("Figure dominant colors: %s", [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in figure_colors[:3]])

    # Score each theme: how well do its primary/accent/secondary match figure colors?
    best_theme = None
    best_score = float("inf")

    for name, theme in themes.items():
        primary = theme.primary_color
        accent = theme.accent
        secondary = theme.secondary_color

        # Find minimum distance from any figure color to theme colors
        min_distances = []
        for fig_color in figure_colors[:3]:
            d_primary = _color_distance(fig_color, primary)
            d_accent = _color_distance(fig_color, accent)
            d_secondary = _color_distance(fig_color, secondary)
            min_distances.append(min(d_primary, d_accent, d_secondary))

        # Average of best matches (lower = more harmonious)
        score = sum(min_distances) / len(min_distances) if min_distances else 999

        if score < best_score:
            best_score = score
            best_theme = name

    if best_theme and best_score < 200:  # reasonable match threshold
        logger.info("Theme matched by figure colors: %s (score=%.1f)", best_theme, best_score)
        return best_theme

    logger.info("No strong figure-color match (best=%.1f), using default selection", best_score)
    return None
