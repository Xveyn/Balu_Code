"""Tree-sitter JS / JSX / TS / TSX symbol extractor.

Public surface: parse_js_ts_file(source, extension). Returns the same
three-tuple as parse_python_file so the parsers/__init__ dispatcher can
treat them uniformly.

Extension routing:
  .js, .jsx  → tree-sitter-javascript
  .ts        → tree-sitter-typescript (typescript variant)
  .tsx       → tree-sitter-typescript (tsx variant)
"""

from __future__ import annotations

import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser

from plugin.services.repo_map import ClassSymbol, FunctionSymbol

_JS_LANG = Language(tree_sitter_javascript.language())
_TS_LANG = Language(tree_sitter_typescript.language_typescript())
_TSX_LANG = Language(tree_sitter_typescript.language_tsx())

_PARSERS: dict[str, Parser] = {}


def _get_parser(extension: str) -> Parser | None:
    if extension in _PARSERS:
        return _PARSERS[extension]
    lang = {
        ".js": _JS_LANG,
        ".jsx": _JS_LANG,
        ".ts": _TS_LANG,
        ".tsx": _TSX_LANG,
    }.get(extension)
    if lang is None:
        return None
    _PARSERS[extension] = Parser(lang)
    return _PARSERS[extension]


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _strip_body(text: str) -> str:
    """Drop trailing '{ ... }' or ';' from a rendered head."""
    for sentinel in ("{", ";"):
        idx = text.find(sentinel)
        if idx != -1:
            return text[:idx].rstrip()
    return text.rstrip()


def _function_head(node, source: bytes) -> str:
    """Render the 'function name(...): R' head, stripping the body braces."""
    return _strip_body(_node_text(node, source))


def _method_head(node, source: bytes) -> str:
    """Render a method_definition or method_signature head."""
    return _strip_body(_node_text(node, source))


def _unwrap_export(node):
    """If node is an export_statement, return its declaration child; else node."""
    if node.type == "export_statement":
        decl = node.child_by_field_name("declaration")
        if decl is not None:
            return decl
        for c in node.named_children:
            return c
    return node


def _extract_imports(root, source: bytes) -> list[str]:
    out: list[str] = []
    for child in root.children:
        if child.type != "import_statement":
            continue
        src = child.child_by_field_name("source")
        if src is None:
            continue
        text = _node_text(src, source).strip()
        if len(text) >= 2 and text[0] in ("'", '"') and text[-1] == text[0]:
            text = text[1:-1]
        out.append(text)
    return out


def _extract_class(node, source: bytes) -> ClassSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"
    bases: list[str] = []
    heritage = None
    for c in node.children:
        if c.type == "class_heritage":
            heritage = c
            break
    if heritage:
        for clause in heritage.named_children:
            # extends_clause / implements_clause contain the actual type names
            if clause.type in ("extends_clause", "implements_clause"):
                for c in clause.named_children:
                    if c.type not in ("extends", "implements"):
                        bases.append(_node_text(c, source))
            else:
                bases.append(_node_text(clause, source))
    methods: list[str] = []
    body = node.child_by_field_name("body")
    if body:
        for stmt in body.children:
            if stmt.type in ("method_definition", "method_signature"):
                methods.append(_method_head(stmt, source))
            elif stmt.type == "public_field_definition":
                value = stmt.child_by_field_name("value")
                if value and value.type in ("arrow_function", "function"):
                    methods.append(_method_head(stmt, source))
    return ClassSymbol(name=name, bases=bases, methods=methods)


def _extract_interface(node, source: bytes) -> ClassSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"
    methods: list[str] = []
    body = node.child_by_field_name("body")
    if body:
        for stmt in body.children:
            if stmt.type in ("method_signature", "property_signature"):
                methods.append(_method_head(stmt, source))
    return ClassSymbol(name=name, bases=[], methods=methods)


def _extract_lexical_function(node, source: bytes) -> FunctionSymbol | None:
    """Return a FunctionSymbol for `const x = (...) => ...` or `const x = function ...`."""
    if node.type != "lexical_declaration":
        return None
    for c in node.named_children:
        if c.type != "variable_declarator":
            continue
        name_node = c.child_by_field_name("name")
        value = c.child_by_field_name("value")
        if name_node is None or value is None:
            continue
        if value.type in ("arrow_function", "function", "function_expression"):
            return FunctionSymbol(
                name=_node_text(name_node, source),
                signature=_strip_body(_node_text(node, source)),
            )
    return None


def _extract_type_alias(node, source: bytes) -> FunctionSymbol | None:
    """Surface `type Name = ...` as a FunctionSymbol so it appears in the map."""
    if node.type != "type_alias_declaration":
        return None
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return FunctionSymbol(
        name=_node_text(name_node, source),
        signature=_strip_body(_node_text(node, source)),
    )


def parse_js_ts_file(
    source: bytes, extension: str
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    parser = _get_parser(extension)
    if parser is None:
        return [], [], []
    try:
        tree = parser.parse(source)
    except Exception:
        return [], [], []
    root = tree.root_node
    if root is None:
        return [], [], []

    imports = _extract_imports(root, source)
    classes: list[ClassSymbol] = []
    functions: list[FunctionSymbol] = []

    for child in root.children:
        target = _unwrap_export(child)
        ntype = target.type
        if ntype == "function_declaration" or ntype == "generator_function_declaration":
            name_node = target.child_by_field_name("name")
            if name_node:
                functions.append(
                    FunctionSymbol(
                        name=_node_text(name_node, source),
                        signature=_function_head(target, source),
                    )
                )
        elif ntype == "class_declaration":
            classes.append(_extract_class(target, source))
        elif ntype == "interface_declaration":
            classes.append(_extract_interface(target, source))
        elif ntype == "type_alias_declaration":
            sym = _extract_type_alias(target, source)
            if sym:
                functions.append(sym)
        elif ntype == "lexical_declaration":
            sym = _extract_lexical_function(target, source)
            if sym:
                functions.append(sym)

    return imports, classes, functions


__all__ = ["parse_js_ts_file"]
