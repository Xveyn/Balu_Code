"""Tree-sitter-backed JS/TS/JSX/TSX source parser.

Three lazy Parser singletons:
  - JS  (tree-sitter-javascript)             → .js, .jsx
  - TS  (tree-sitter-typescript, typescript) → .ts
  - TSX (tree-sitter-typescript, tsx)        → .tsx
"""

from __future__ import annotations

import threading

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from ..repo_map_types import ClassSymbol, FunctionSymbol

_js_parser: Parser | None = None
_ts_parser: Parser | None = None
_tsx_parser: Parser | None = None
_lock = threading.Lock()

_JS_EXTENSIONS = frozenset({".js", ".jsx"})
_TS_EXTENSIONS = frozenset({".ts"})
_TSX_EXTENSIONS = frozenset({".tsx"})

_SYMBOL_NODE_TYPES = frozenset({
    "function_declaration",
    "generator_function_declaration",
    "class_declaration",
    "abstract_class_declaration",
    "interface_declaration",
    "type_alias_declaration",
})


def get_js_parser() -> Parser:
    global _js_parser
    if _js_parser is None:
        with _lock:
            if _js_parser is None:
                _js_parser = Parser(Language(tsjs.language()))
    return _js_parser


def get_ts_parser() -> Parser:
    global _ts_parser
    if _ts_parser is None:
        with _lock:
            if _ts_parser is None:
                _ts_parser = Parser(Language(tsts.language_typescript()))
    return _ts_parser


def get_tsx_parser() -> Parser:
    global _tsx_parser
    if _tsx_parser is None:
        with _lock:
            if _tsx_parser is None:
                _tsx_parser = Parser(Language(tsts.language_tsx()))
    return _tsx_parser


def _get_parser_for_ext(extension: str) -> Parser:
    if extension in _JS_EXTENSIONS:
        return get_js_parser()
    if extension in _TS_EXTENSIONS:
        return get_ts_parser()
    if extension in _TSX_EXTENSIONS:
        return get_tsx_parser()
    raise ValueError(f"Unsupported extension for JS/TS parser: {extension!r}")


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _extract_module_specifier(node, source: bytes) -> str | None:
    for child in node.children:
        if child.type == "string":
            raw = _node_text(child, source)
            return raw.strip("'\"` ")
    return None


def _method_sig(node, source: bytes) -> str:
    name_node = node.child_by_field_name("name") or node.child_by_field_name("property")
    params_node = node.child_by_field_name("parameters")
    name = _node_text(name_node, source) if name_node else "<anon>"
    params = _node_text(params_node, source) if params_node else "()"
    modifiers = [
        _node_text(c, source)
        for c in node.children
        if c.type in ("async", "static", "get", "set", "readonly")
    ]
    prefix = " ".join(modifiers) + " " if modifiers else ""
    return f"{prefix}{name}{params}"


def _build_class(node, source: bytes) -> ClassSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"

    bases: list[str] = []
    for child in node.children:
        if child.type == "class_heritage":
            for hc in child.children:
                if hc.type in ("identifier", "member_expression"):
                    bases.append(_node_text(hc, source))
                elif hc.type == "extends_clause":
                    # TypeScript wraps heritage in extends_clause
                    for hhc in hc.children:
                        if hhc.type in ("identifier", "member_expression"):
                            bases.append(_node_text(hhc, source))

    body_node = node.child_by_field_name("body")
    methods: list[str] = []
    if body_node is not None:
        for child in body_node.children:
            if child.type == "method_definition":
                methods.append(_method_sig(child, source))
            elif child.type == "public_field_definition":
                value = child.child_by_field_name("value")
                if value is not None and value.type == "arrow_function":
                    prop = child.child_by_field_name("name")
                    if prop is not None:
                        methods.append(_node_text(prop, source) + " = (...) => ...")

    return ClassSymbol(name=name, bases=bases, methods=methods)


def _build_interface(node, source: bytes) -> ClassSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"
    methods: list[str] = []
    body_node = node.child_by_field_name("body")
    if body_node is not None:
        for child in body_node.children:
            if child.type in ("method_signature", "call_signature", "construct_signature"):
                methods.append(_node_text(child, source).strip())
    return ClassSymbol(name=name, bases=[], methods=methods)


def _build_function(node, source: bytes) -> FunctionSymbol:
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    name = _node_text(name_node, source) if name_node else "<anon>"
    params = _node_text(params_node, source) if params_node else "()"
    is_async = any(c.type == "async" for c in node.children)
    is_gen = node.type == "generator_function_declaration"
    prefix = ("async " if is_async else "") + ("function* " if is_gen else "function ")
    return FunctionSymbol(name=name, signature=f"{prefix}{name}{params}")


def _build_arrow_from_declarator(declarator, source: bytes) -> FunctionSymbol | None:
    name_node = declarator.child_by_field_name("name")
    value_node = declarator.child_by_field_name("value")
    if name_node is None or value_node is None:
        return None
    name = _node_text(name_node, source)
    if value_node.type == "arrow_function":
        params_node = (
            value_node.child_by_field_name("parameters")
            or value_node.child_by_field_name("parameter")
        )
        params = _node_text(params_node, source) if params_node else "()"
        return FunctionSymbol(name=name, signature=f"const {name} = {params} => ...")
    if value_node.type in ("function", "generator_function"):
        params_node = value_node.child_by_field_name("parameters")
        params = _node_text(params_node, source) if params_node else "()"
        return FunctionSymbol(name=name, signature=f"const {name} = function{params}")
    return None


def _build_type_alias(node, source: bytes) -> FunctionSymbol:
    name_node = node.child_by_field_name("name")
    name = _node_text(name_node, source) if name_node else "<anon>"
    return FunctionSymbol(name=name, signature=f"type {name} = ...")


def _process_node(
    node,
    source: bytes,
    imports: list[str],
    classes: list[ClassSymbol],
    functions: list[FunctionSymbol],
) -> None:
    nt = node.type

    if nt == "import_statement":
        module = _extract_module_specifier(node, source)
        if module:
            imports.append(module)

    elif nt in ("function_declaration", "generator_function_declaration", "function_expression"):
        # function_expression can appear inside ERROR nodes on malformed input
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            functions.append(_build_function(node, source))

    elif nt in ("class_declaration", "abstract_class_declaration"):
        classes.append(_build_class(node, source))

    elif nt == "interface_declaration":
        classes.append(_build_interface(node, source))

    elif nt == "type_alias_declaration":
        functions.append(_build_type_alias(node, source))

    elif nt == "lexical_declaration":
        for child in node.children:
            if child.type == "variable_declarator":
                sym = _build_arrow_from_declarator(child, source)
                if sym is not None:
                    functions.append(sym)

    elif nt == "export_statement":
        for child in node.children:
            if child.type not in ("export", "default", "declare", "type", ";", "comment"):
                _process_node(child, source, imports, classes, functions)
                break


_RECOVERABLE_TYPES = frozenset({
    "function_declaration",
    "generator_function_declaration",
    "function_expression",
    "class_declaration",
    "abstract_class_declaration",
    "interface_declaration",
    "type_alias_declaration",
    "lexical_declaration",
    "export_statement",
    "import_statement",
})


def _recover_from_error(
    node,
    source: bytes,
    imports: list[str],
    classes: list[ClassSymbol],
    functions: list[FunctionSymbol],
) -> None:
    """Recursively walk an ERROR subtree and process any recoverable declarations."""
    for child in node.children:
        if child.type in _RECOVERABLE_TYPES:
            _process_node(child, source, imports, classes, functions)
        elif child.child_count > 0:
            _recover_from_error(child, source, imports, classes, functions)


def _lexical_has_function(node) -> bool:
    for child in node.children:
        if child.type == "variable_declarator":
            value = child.child_by_field_name("value")
            if value is not None and value.type in ("arrow_function", "function", "generator_function"):
                return True
    return False


def parse_js_ts_file(
    source: bytes,
    extension: str,
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
    """Parse JS/TS/JSX/TSX source; return (imports, classes, top-level functions).

    Raises ValueError for unsupported extensions. Never raises on malformed input.
    """
    # Validate extension before checking source emptiness so we always raise on bad ext.
    parser = _get_parser_for_ext(extension)
    if not source:
        return [], [], []
    try:
        tree = parser.parse(source)
    except Exception:
        return [], [], []

    imports: list[str] = []
    classes: list[ClassSymbol] = []
    functions: list[FunctionSymbol] = []

    for node in tree.root_node.children:
        if node.type == "ERROR":
            # tree-sitter may wrap content in an ERROR node for bad syntax;
            # walk the subtree recursively to recover any valid declarations.
            _recover_from_error(node, source, imports, classes, functions)
        else:
            _process_node(node, source, imports, classes, functions)

    return imports, classes, functions


def extract_top_level_ranges_js_ts(source: bytes, extension: str) -> list[tuple[int, int]]:
    """Return (start_line, end_line) 1-indexed inclusive pairs for top-level symbols."""
    if not source:
        return []
    parser = _get_parser_for_ext(extension)
    try:
        tree = parser.parse(source)
    except Exception:
        return []

    ranges: list[tuple[int, int]] = []

    for node in tree.root_node.children:
        nt = node.type
        if (
            nt in _SYMBOL_NODE_TYPES
            or nt == "export_statement"
            or (nt == "lexical_declaration" and _lexical_has_function(node))
        ):
            ranges.append((node.start_point[0] + 1, node.end_point[0] + 1))

    ranges.sort()
    return ranges


__all__ = [
    "get_js_parser",
    "get_ts_parser",
    "get_tsx_parser",
    "parse_js_ts_file",
    "extract_top_level_ranges_js_ts",
]
