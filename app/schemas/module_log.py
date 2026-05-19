"""ModuleCallLog schema - logging for every module/LLM call."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ModuleCallLog(BaseModel):
    """Log entry for a single module call."""

    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    module: str
    prompt_version: str = ""
    model: str = ""
    input_packet_hash: str = ""
    output_path: str = ""
    status: str = "ok"
    error_type: str = ""
    error_message: str = ""
    timing_sec: float = 0.0
    token_usage: dict = Field(default_factory=dict)

    # Optional request/response trace.
    messages: list[dict[str, Any]] = Field(default_factory=list)
    response_text: str = ""
