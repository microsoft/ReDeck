"""Sandboxed execution for generated Python slide code.

Provides a safe execution environment with:
- Whitelisted imports only
- Pre-loaded presentation-building symbols
- Post-execution geometry fixing
"""

import logging
import traceback
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_SHAPE

# Pre-import chart types so generated code doesn't need to
try:
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
except ImportError:
    CategoryChartData = None
    XL_CHART_TYPE = None

from . import code_transforms

logger = logging.getLogger(__name__)

# Whitelist of modules that generated code is allowed to import at runtime.
_SAFE_IMPORT_PREFIXES = ("pptx", "os", "os.path", "pathlib", "math", "json", "struct", "matplotlib", "tempfile", "lxml")


def _make_safe_import():
    """Return a restricted __import__ that only allows whitelisted modules."""
    _real_import = __import__

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Allow relative imports (level > 0) — they come from pptx internals
        if level > 0:
            return _real_import(name, globals, locals, fromlist, level)
        # Check absolute import against whitelist
        if any(name == prefix or name.startswith(prefix + ".")
               for prefix in _SAFE_IMPORT_PREFIXES):
            return _real_import(name, globals, locals, fromlist, level)
        raise ImportError(
            f"Import of '{name}' is not allowed in generated code. "
            f"Only these modules are permitted: {_SAFE_IMPORT_PREFIXES}"
        )

    return _safe_import


def execute_code(
    code: str,
    prs: Presentation,
    slide,
    image_dir: str,
) -> tuple[bool, str]:
    """Execute generated code safely.

    Applies code sanitization and image height-cap injection.

    Returns (success, error_message).
    """
    # Sanitize common LLM mistakes before execution
    code = code_transforms.sanitize_code(code)

    # Patch add_picture at the code level: inject height-cap logic
    code = code_transforms.inject_image_height_cap(code)

    # Build execution namespace with allowed imports
    safe_import = _make_safe_import()
    exec_globals = {
        "__builtins__": {
            "__import__": safe_import,
            "range": range,
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "bool": bool,
            "max": max,
            "min": min,
            "enumerate": enumerate,
            "zip": zip,
            "round": round,
            "abs": abs,
            "sorted": sorted,
            "sum": sum,
            "map": map,
            "filter": filter,
            "any": any,
            "all": all,
            "isinstance": isinstance,
            "hasattr": hasattr,
            "getattr": getattr,
            "print": print,
            "open": open,
            "type": type,
            "True": True,
            "False": False,
            "None": None,
            "Exception": Exception,
            "ValueError": ValueError,
            "TypeError": TypeError,
            "KeyError": KeyError,
            "IndexError": IndexError,
            "AttributeError": AttributeError,
            "FileNotFoundError": FileNotFoundError,
            "OSError": OSError,
            "RuntimeError": RuntimeError,
        },
        # python-pptx imports
        "Inches": Inches,
        "Pt": Pt,
        "Emu": Emu,
        "RGBColor": RGBColor,
        "PP_ALIGN": PP_ALIGN,
        "MSO_ANCHOR": MSO_ANCHOR,
        "MSO_AUTO_SIZE": MSO_AUTO_SIZE,
        "MSO_SHAPE": MSO_SHAPE,
        # Chart imports (pre-loaded so LLM doesn't need to import)
        "CategoryChartData": CategoryChartData,
        "XL_CHART_TYPE": XL_CHART_TYPE,
        # File system
        "Path": Path,
        "os": __import__("os"),
        # Utility modules for visualization patterns
        "math": __import__("math"),
        "json": __import__("json"),
    }

    try:
        exec(code, exec_globals)
        build_fn = exec_globals.get("build_slide")
        if not build_fn:
            return False, "Function 'build_slide' not found in generated code"

        build_fn(prs, slide, image_dir)
        return True, ""

    except Exception as e:
        tb = traceback.format_exc()
        tb_lines = tb.strip().split("\n")
        short_tb = "\n".join(tb_lines[-5:])
        return False, f"{type(e).__name__}: {e}\n{short_tb}"
