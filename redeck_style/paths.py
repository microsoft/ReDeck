"""Portable locations for bundled resources and explicitly supplied inputs."""

import os
import warnings
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def resolve_probe_root(explicit=None):
    configured = explicit or os.environ.get("REDECK_PROBE_ROOT")
    if not configured and os.environ.get("REDECK_LEGACY_ROOT"):
        warnings.warn("REDECK_LEGACY_ROOT is deprecated; use REDECK_PROBE_ROOT.", FutureWarning, stacklevel=2)
        configured = os.environ["REDECK_LEGACY_ROOT"]
    return Path(configured or PACKAGE_ROOT).expanduser().resolve()


def resolve_cases_root(explicit=None):
    return Path(explicit or os.environ.get("REDECK_CASES_ROOT") or Path.cwd() / "cases").expanduser().resolve()
