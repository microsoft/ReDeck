"""Hashing utilities for content tracking and reproducibility."""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def hash_file(path: str | Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def hash_string(s: str) -> str:
    """Compute SHA256 hash of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def hash_packet(data: Any) -> str:
    """Compute hash of a structured packet (dict or Pydantic model)."""
    if isinstance(data, BaseModel):
        s = data.model_dump_json(exclude_none=True)
    elif isinstance(data, dict):
        s = json.dumps(data, sort_keys=True, default=str)
    else:
        s = str(data)
    return hash_string(s)
