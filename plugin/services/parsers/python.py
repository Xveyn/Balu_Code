"""Tree-sitter-backed Python source parser.

Returns the three lists ``RepoMap`` consumes: imports (module names as
written), classes (with bases + method signatures), top-level functions
(with signatures). Decorated definitions are unwrapped — the decorator
itself is not surfaced.

The tree-sitter ``Parser`` is built once per process (lazy) and reused.
"""

from __future__ import annotations

import threading

import tree_sitter_python as tsp
from tree_sitter import Language, Parser

from ..repo_map_types import ClassSymbol, FunctionSymbol

_parser: Parser | None = None
_parser_lock = threading.Lock()


def get_parser() -> Parser:
    global _parser
    if _parser is None:
        with _parser_lock:
            if _parser is None:
                _parser = Parser(Language(tsp.language()))
    return _parser


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _signature(node, source: bytes) -> str:
    """Build 'def name(params) -> ReturnType' from a function_definition node.

    Handles async-def by checking for an ``async`` token among children.
    """
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    return_node = node.child_by_field_name("return_type")
    name = _node_text(name_node, source) if name_node else "<anon>"
    params = _node_text(params_node, source) if params_node else "()"
    is_async = any(c.type == "async" for c in node.children)
    prefix = "async def " if is_async else "def "
    sig = f"{prefix}{name}{params}"
    if return_node is not None:
        sig += f" -> {_node_text(return_node, source)}"
    return sig


def _extract_import(node, source: bytes) -> list[str]:
    """Handle 'import X', 'import X.Y', 'import X as Z', 'import X, Y'."""
    out: list[str] = []
    for child in node.children:
        if child.type == "dotted_name":
            out.append(_node_text(child, source))
        elif child.type == "aliased_import":
            inner = child.child_by_field_name("name")
            if inner is not None:
                out.append(_node_text(inner, source))
    return out


def _extract_import_from(node, source: bytes) -> list[str]:
    """Handle 'from X import Y', 'from .X import Y', 'from . import Y'.

    Returns the module name only (one entry per statement).
    """
    module_node = node.child_by_field_name("module_name")
    if module_node is None:
        return []
    return [_node_text(module_node, source)]


def _build_class(node, source: bytes) -> ClassSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"

    superclasses_node = node.child_by_field_name("superclasses")
    bases: list[str] = []
    if superclasses_node is not None:
        for child in superclasses_node.children:
            if child.type in ("identifier", "attribute"):
                bases.append(_node_text(child, source))

    body_node = node.child_by_field_name("body")
    methods: list[str] = []
    if body_node is not None:
        for child in body_node.children:
            if child.type == "function_definition":
                methods.append(_signature(child, source))
            elif child.type == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is not None and inner.type == "function_definition":
                    methods.append(_signature(inner, source))

    return ClassSymbol(name=name, bases=bases, methods=methods)


def _build_function(node, source: bytes) -> FunctionSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"
    return FunctionSymbol(name=name, signature=_signature(node, source))


def parse_python_file(
    source: bytes,
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    """Parse Python source bytes; return (imports, classes, top-level functions).

    Tree-sitter is error-tolerant — partial parses still yield whatever the
    parser successfully recognised. This function never raises on bad input.
    """
    parser = get_parser()
    try:
        tree = parser.parse(source)
    except Exception:
        return [], [], []

    imports: list[str] = []
    classes: list[ClassSymbol] = []
    functions: list[FunctionSymbol] = []

    for node in tree.root_node.children:
        nt = node.type
        if nt == "import_statement":
            imports.extend(_extract_import(node, source))
        elif nt == "import_from_statement":
            imports.extend(_extract_import_from(node, source))
        elif nt == "class_definition":
            classes.append(_build_class(node, source))
        elif nt == "function_definition":
            functions.append(_build_function(node, source))
        elif nt == "decorated_definition":
            inner = node.child_by_field_name("definition")
            if inner is None:
                continue
            if inner.type == "class_definition":
                classes.append(_build_class(inner, source))
            elif inner.type == "function_definition":
                functions.append(_build_function(inner, source))

    return imports, classes, functions


__all__ = ["get_parser", "parse_python_file"]
