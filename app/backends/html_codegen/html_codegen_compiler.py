"""Compatibility wrapper for the canonical HTML codegen compiler."""

from ..python_pptx.html_codegen_compiler import (
    HTML_CODEGEN_PROMPT_PATH,
    HTML_CODEGEN_PROMPT_VERSION,
    HTML_REPAIR_PROMPT_PATH,
    HtmlCodeGenCompiler,
)

__all__ = [
    "HTML_CODEGEN_PROMPT_PATH",
    "HTML_CODEGEN_PROMPT_VERSION",
    "HTML_REPAIR_PROMPT_PATH",
    "HtmlCodeGenCompiler",
]
