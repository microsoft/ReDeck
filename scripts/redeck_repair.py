#!/usr/bin/env python3
"""Compatibility alias for the unified repair controller."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from redeck_style.compat import run


if __name__ == "__main__":
    run("repair")
