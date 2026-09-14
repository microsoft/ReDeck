"""Evidence budgets independent of theme, material family and repair policy."""

DENSITY_MODES = ("balanced", "evidence-rich")


def density_policy(mode, role):
    if mode not in DENSITY_MODES:
        raise ValueError(f"Unknown information density: {mode}")
    rich = mode == "evidence-rich" and role != "title"
    return {
        "mode": mode,
        "rich_content": rich,
        "support_candidates": 1 if role == "title" else 4 if rich else 2,
        "maximum_source_details": 0 if role == "title" else 3 if rich else 1,
        "target_source_details": 0 if role == "title" else 2 if rich else 0,
        "table_row_limit": 8 if rich else 6,
        "content_coverage": "62-78%" if rich else "50-72%",
        "negative_space": "12-22%" if rich else "18-32%",
    }
