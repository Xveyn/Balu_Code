"""Source-file symbol extractors. One module per language family."""

from __future__ import annotations

from ..repo_map import ClassSymbol, FunctionSymbol
from .js_ts import parse_js_ts_file
from .python import parse_python_file

_JS_TS_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})


def parse_file(
    source: bytes, extension: str
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    """Route to the right language-specific parser based on file extension.

    Unknown extension → three empty lists. Never raises on parse errors;
    individual parsers handle their own degraded output.
    """
    if extension == ".py":
        return parse_python_file(source)
    if extension in _JS_TS_EXTENSIONS:
        return parse_js_ts_file(source, extension)
    return [], [], []


__all__ = ["parse_file"]
