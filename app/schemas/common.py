"""Common enums and base types shared across all schemas."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Status(str, Enum):
    OK = "ok"
    ERROR = "error"
    NEED_MORE_CONTEXT = "need_more_context"
    INFEASIBLE = "infeasible"


class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    NEEDS_VERIFY = "needs_verify"
    WONT_FIX = "wont_fix"
    DEFERRED = "deferred"  # issue is real but repair lacks source evidence to fix it


class RenderClass(str, Enum):
    APPROX_RENDER = "approx_render"
    REFERENCE_RENDER = "reference_render"
    DESKTOP_TRUTH_RENDER = "desktop_truth_render"


class EvalSplitLevel(str, Enum):
    MONOLITHIC = "monolithic"
    FAMILY = "family"
    FAMILY_PLUS_SLIDE = "family_plus_slide"


class RenderBackendType(str, Enum):
    LINUX_LO_PDF = "linux_lo_pdf"
    MAC_POWERPOINT_PDF = "mac_powerpoint_pdf"
    MAC_POWERPOINT_PNG = "mac_powerpoint_png"


class RepairAction(str, Enum):
    """Recommended repair action for an issue (set by Judge)."""
    KEEP = "KEEP"    # no repair needed / minor cosmetic
    PATCH = "PATCH"  # surgical text replacement only
    REGEN = "REGEN"  # structural code modification needed


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class BasePacket(BaseModel):
    """Base class for all structured packets."""

    class Config:
        extra = "allow"
