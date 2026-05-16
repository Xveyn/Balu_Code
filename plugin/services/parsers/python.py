"""Tree-sitter Python symbol extractor.

Returns (imports, classes, functions) tuples. ClassSymbol / FunctionSymbol
are imported from repo_map. On parse error returns three empty lists —
the file's stub still appears in the repo map but with no extracted
symbols, so the agent at least sees the path.
"""

from __future__ import annotations

import tree_sitter_python
from tree_sitter import Language, Parser

from ..repo_map import ClassSymbol, FunctionSymbol

_LANG = Language(tree_sitter_python.language())
_PARSER: Parser | None = None


def _get_parser() -> Parser:
    global _PARSER
    if _PARSER is None:
        _PARSER = Parser(_LANG)
    return _PARSER


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _render_function_signature(node, source: bytes) -> str:
    """Reconstruct 'def name(params) -> return_type' from a function_definition node.

    Supports async via the leading 'async' keyword; reads name + parameters
    + return_type children. If pieces are missing, falls back to whatever
    is available.
    """
    is_async = any(child.type == "async" for child in node.children)
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    return_node = node.child_by_field_name("return_type")

    name = _node_text(name_node, source) if name_node else "<anon>"
    params = _node_text(params_node, source) if params_node else "()"
    prefix = "async def" if is_async else "def"
    if return_node:
        return f"{prefix} {name}{params} -> {_node_text(return_node, source)}"
    return f"{prefix} {name}{params}"


def _extract_imports(root, source: bytes) -> list[str]:
    """Collect import targets at module level. Order = source order."""
    out: list[str] = []
    for child in root.children:
        if child.type == "import_statement":
            for n in child.named_children:
                if n.type == "dotted_name":
                    out.append(_node_text(n, source))
                elif n.type == "aliased_import":
                    name = n.child_by_field_name("name")
                    if name:
                        out.append(_node_text(name, source))
        elif child.type == "import_from_statement":
            mod = child.child_by_field_name("module_name")
            if mod:
                out.append(_node_text(mod, source))
    return out


def _extract_classes(root, source: bytes) -> list[ClassSymbol]:
    out: list[ClassSymbol] = []
    for child in root.children:
        if child.type != "class_definition":
            continue
        name_node = child.child_by_field_name("name")
        if not name_node:
            continue
        name = _node_text(name_node, source)
        bases: list[str] = []
        sup = child.child_by_field_name("superclasses")
        if sup:
            for arg in sup.named_children:
                bases.append(_node_text(arg, source))
        methods: list[str] = []
        body = child.child_by_field_name("body")
        if body:
            for stmt in body.children:
                # methods may sit inside decorated_definition wrappers
                target = stmt
                if stmt.type == "decorated_definition":
                    target = stmt.child_by_field_name("definition")
                if target and target.type == "function_definition":
                    methods.append(_render_function_signature(target, source))
        out.append(ClassSymbol(name=name, bases=bases, methods=methods))
    return out


def _extract_functions(root, source: bytes) -> list[FunctionSymbol]:
    out: list[FunctionSymbol] = []
    for child in root.children:
        target = child
        if child.type == "decorated_definition":
            target = child.child_by_field_name("definition")
        if target and target.type == "function_definition":
            name_node = target.child_by_field_name("name")
            if not name_node:
                continue
            out.append(
                FunctionSymbol(
                    name=_node_text(name_node, source),
                    signature=_render_function_signature(target, source),
                )
            )
    return out


def parse_python_file(
    source: bytes,
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    """Parse Python source bytes → (imports, classes, top-level functions)."""
    try:
        tree = _get_parser().parse(source)
    except Exception:
        return [], [], []
    root = tree.root_node
    if root is None:
        return [], [], []
    return (
        _extract_imports(root, source),
        _extract_classes(root, source),
        _extract_functions(root, source),
    )


__all__ = ["parse_python_file"]
