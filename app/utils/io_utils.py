"""IO utilities - JSON/JSONL reading and writing, directory management."""

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def ensure_dir(path: str | Path) -> Path:
    """Create directory if it doesn't exist, return Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(data: Any, path: str | Path, indent: int = 2) -> None:
    """Write data to JSON file. Supports Pydantic models and dicts."""
    p = Path(path)
    ensure_dir(p.parent)
    if isinstance(data, BaseModel):
        content = data.model_dump_json(indent=indent)
    else:
        content = json.dumps(data, indent=indent, ensure_ascii=False, default=str)
    p.write_text(content, encoding="utf-8")


def read_json(path: str | Path) -> Any:
    """Read and parse JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(items: list[Any], path: str | Path) -> None:
    """Write items to JSONL file. Each item can be a Pydantic model or dict."""
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as f:
        for item in items:
            if isinstance(item, BaseModel):
                line = item.model_dump_json()
            else:
                line = json.dumps(item, ensure_ascii=False, default=str)
            f.write(line + "\n")


def read_jsonl(path: str | Path) -> list[dict]:
    """Read JSONL file and return list of dicts."""
    items = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def append_jsonl(item: Any, path: str | Path) -> None:
    """Append a single item to JSONL file."""
    p = Path(path)
    ensure_dir(p.parent)
    if isinstance(item, BaseModel):
        line = item.model_dump_json()
    else:
        line = json.dumps(item, ensure_ascii=False, default=str)
    with p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_text(path: str | Path) -> str:
    """Read text file."""
    return Path(path).read_text(encoding="utf-8")


def write_text(content: str, path: str | Path) -> None:
    """Write text to file."""
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(content, encoding="utf-8")


def safe_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
