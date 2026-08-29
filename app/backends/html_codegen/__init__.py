"""Public HTML code-generation backend with lazy compatibility exports."""

__all__ = ["HtmlCodeGenCompiler"]


def __getattr__(name: str):
    if name == "HtmlCodeGenCompiler":
        from .html_codegen_compiler import HtmlCodeGenCompiler
        return HtmlCodeGenCompiler
    raise AttributeError(name)
