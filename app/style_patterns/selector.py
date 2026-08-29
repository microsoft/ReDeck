"""Select a design pattern for an entire deck based on paper content."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

_LIB_PATH = Path(__file__).parent / "library.json"
_PATTERNS: list[dict] | None = None


def _load() -> list[dict]:
    global _PATTERNS
    if _PATTERNS is None:
        _PATTERNS = json.loads(_LIB_PATH.read_text("utf-8"))
    return _PATTERNS


# Domain → preferred pattern dimensions (soft preferences, not hard filters)
DOMAIN_PREFS: dict[str, dict[str, list[str]]] = {
    "cs_ml": {"lum": ["dark", "medium"], "palette": ["blue-corporate", "gray-mono", "multi-vibrant"], "typo": ["sans-clean", "mono-tech"]},
    "bio_med": {"lum": ["light"], "palette": ["green-forest", "blue-corporate", "gray-mono"], "deco": ["border-frame", "shadow-cards"], "typo": ["serif-classic", "sans-clean"]},
    "finance": {"lum": ["light", "medium"], "palette": ["blue-corporate", "gray-mono"], "deco": ["border-frame", "shadow-cards"], "typo": ["serif-classic"]},
    "physics": {"lum": ["dark", "medium"], "palette": ["blue-corporate", "purple-violet"], "typo": ["sans-clean", "mono-tech"]},
    "social": {"lum": ["light"], "palette": ["earth-warm", "orange-sunset", "multi-vibrant"], "deco": ["shadow-cards"], "typo": ["mixed-editorial"]},
}

# Keywords to detect domain from paper title
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "cs_ml": ["neural", "network", "learning", "transformer", "llm", "model", "training", "benchmark", "diffusion", "agent", "reinforcement", "embedding", "attention", "generative", "prompt"],
    "bio_med": ["protein", "gene", "clinical", "drug", "cell", "brain", "medical", "health", "disease", "cancer", "molecular", "genomic", "therapy"],
    "finance": ["market", "portfolio", "trading", "financial", "investment", "risk", "stock", "bond", "capital", "bank", "economic", "earnings", "revenue", "income", "profit", "fiscal", "quarter", "dividend", "gdp", "inflation", "monetary", "outlook", "forecast"],
    "physics": ["quantum", "particle", "photon", "laser", "optical", "magnetic", "energy", "plasma", "cosmol", "gravity"],
    "social": ["social", "survey", "behavior", "community", "policy", "education", "language", "cultural", "demographic", "speech", "president", "government", "public", "nation", "citizen", "democracy"],
}


def _detect_domain(paper_title: str) -> str:
    """Detect paper domain from title keywords."""
    title_lower = paper_title.lower()
    scores: dict[str, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        scores[domain] = sum(1 for kw in keywords if kw in title_lower)
    best = max(scores, key=lambda d: scores[d])
    return best if scores[best] > 0 else "cs_ml"  # default


def _score_pattern(pattern: dict, prefs: dict[str, list[str]]) -> float:
    """Score how well a pattern matches domain preferences. Higher = better.

    Also applies a universal preference for clean, chart-friendly patterns:
    light/medium luminance, clean typography, minimal decoration.
    """
    dims = pattern.get("dims", {})
    score = 0.0

    # Domain-specific preferences
    for dim_key, preferred_values in prefs.items():
        actual = dims.get(dim_key, "")
        if actual in preferred_values:
            score += 1.0
        elif any(pv in actual for pv in preferred_values):
            score += 0.5

    # Universal preference: readable, visually rich, designed
    if dims.get("lum") in ("light", "medium", "dark"):
        score += 0.3  # all luminances fine
    if dims.get("typo") in ("sans-clean", "mono-tech", "mixed-editorial"):
        score += 0.4
    # PREFER patterns with decoration — they produce designed-looking slides
    if dims.get("deco") in ("shadow-cards", "accent-lines", "corner-shapes", "underline-titles"):
        score += 1.2
    elif dims.get("deco") in ("border-frame",):
        score += 0.5
    elif dims.get("deco") in ("none",):
        score -= 0.3  # plain patterns look generic
    # Prefer chart/data content types
    if dims.get("content") in ("chart-focus", "data-table", "comparison-columns", "metric-cards"):
        score += 0.8
    # Penalize overly sparse patterns
    if dims.get("content") in ("title-only", "hero-image"):
        score -= 0.5

    return score


def select_pattern_for_deck(
    paper_title: str,
    paper_domain: str | None = None,
    theme_id: str | None = None,
) -> dict:
    """Select one pattern for the entire deck. Deterministic per paper title.

    Uses paper title to detect domain → match against pattern dimensions.
    Same title always gets the same pattern (md5-seeded).
    """
    patterns = _load()
    domain = paper_domain or _detect_domain(paper_title)
    prefs = DOMAIN_PREFS.get(domain, {})

    # Score all patterns
    scored = [(p, _score_pattern(p, prefs)) for p in patterns]
    # Keep top 30% by score
    scored.sort(key=lambda x: -x[1])
    top_n = max(10, len(scored) // 3)
    candidates = [p for p, _ in scored[:top_n]]

    # Deterministic selection from candidates
    seed = int(hashlib.md5(paper_title.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return rng.choice(candidates)


def get_pattern_by_name(name: str) -> dict | None:
    """Get a specific pattern by id (e.g. 'seed_042') or index."""
    patterns = _load()
    # Try by id
    for p in patterns:
        if p.get("id") == name:
            return p
    # Try by index
    try:
        idx = int(name)
        if 0 <= idx < len(patterns):
            return patterns[idx]
    except ValueError:
        pass
    # Try by dim match (e.g. "neon_cyber" → look for matching desc/dims)
    name_lower = name.lower().replace("_", "-")
    for p in patterns:
        dims = p.get("dims", {})
        dim_str = " ".join(str(v) for v in dims.values()).lower()
        if name_lower in dim_str:
            return p
    return None
