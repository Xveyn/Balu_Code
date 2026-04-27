# JS/TS Indexing & Repo-Map Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `balu-code index` and the repo-map to support `.js`, `.ts`, `.jsx`, and `.tsx` files in addition to Python, using a new `plugin/services/parsers/` subpackage.

**Architecture:** A new `parsers/` subpackage holds all tree-sitter language parsers — `python.py` (moved from `repo_map_python.py`) and the new `js_ts.py`. Both `rag_chunker.py` and `repo_map.py` dispatch to the right parser based on file extension. The public interface of each parser is uniform: `parse_<lang>_file(source) → (imports, classes, functions)`.

**Tech Stack:** Python 3.12, tree-sitter 0.25, tree-sitter-python (existing), tree-sitter-javascript ≥ 0.23 (new), tree-sitter-typescript ≥ 0.23 (new), pytest-asyncio.

---

## File Map

| Action | Path |
|---|---|
| **Create** | `plugin/services/parsers/__init__.py` |
| **Create (move)** | `plugin/services/parsers/python.py` ← was `repo_map_python.py` |
| **Create** | `plugin/services/parsers/js_ts.py` |
| **Delete** | `plugin/services/repo_map_python.py` |
| **Modify** | `plugin/services/rag_chunker.py` — update import, add `chunk_js_ts_file` |
| **Modify** | `plugin/services/indexer.py` — `_iter_source_files()`, dispatch by ext |
| **Modify** | `plugin/services/repo_map.py` — update import, extend `walk_and_cache` |
| **Modify** | `plugin/pyproject.toml` — add two deps |
| **Modify** | `plugin/tests/test_repo_map_python.py` — update import path |
| **Modify** | `plugin/tests/test_repo_map_walker.py` — update import paths + add JS/TS tests |
| **Modify** | `plugin/tests/test_indexer.py` — add JS/TS tests |
| **Create** | `plugin/tests/test_parsers_js_ts.py` |
| **Create** | `plugin/tests/test_rag_chunker_js_ts.py` |

---

## Task 1: Add tree-sitter-javascript and tree-sitter-typescript dependencies

**Files:**
- Modify: `plugin/pyproject.toml`

- [ ] **Step 1: Add deps to pyproject.toml**

In `plugin/pyproject.toml`, add two lines to the `dependencies` array (after `"tree-sitter-python>=0.21"`):

```toml
[project]
name = "balu-code-plugin-dev"
version = "0.0.0"
description = "Dev-only metadata so pytest can import plugin/ and its tests."
requires-python = ">=3.11"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.6",
  "sqlite-vec>=0.1.9",
  "tiktoken>=0.6",
  "trafilatura>=1.12",
  "tree-sitter>=0.22",
  "tree-sitter-python>=0.21",
  "tree-sitter-javascript>=0.23",
  "tree-sitter-typescript>=0.23",
  "unidiff>=0.7",
  "fastapi>=0.110",
  "balu-code-shared",
]
```

- [ ] **Step 2: Install the new packages**

```bash
cd /home/sven/projects/plugins/Balu_Code
uv pip install tree-sitter-javascript tree-sitter-typescript
```

Expected: packages install without error.

- [ ] **Step 3: Verify the API names**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/python -c "
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser
print('JS ok:', tsjs.language())
print('TS ok:', tsts.language_typescript())
print('TSX ok:', tsts.language_tsx())
"
```

Expected: three lines printed without `AttributeError`. If `language_typescript` or `language_tsx` is wrong, run `.venv/bin/python -c "import tree_sitter_typescript as t; print(dir(t))"` to find the correct names and adjust Task 3's code accordingly.

- [ ] **Step 4: Commit**

```bash
git add plugin/pyproject.toml
git commit -m "chore(deps): add tree-sitter-javascript and tree-sitter-typescript"
```

---

## Task 2: Create parsers/ subpackage — move repo_map_python.py

This task is a pure rename/move. No logic changes. After this task all existing tests must still pass.

**Files:**
- Create: `plugin/services/parsers/__init__.py`
- Create: `plugin/services/parsers/python.py` (content of repo_map_python.py with one import changed)
- Delete: `plugin/services/repo_map_python.py`
- Modify: `plugin/services/rag_chunker.py` — import path
- Modify: `plugin/services/repo_map.py` — import path
- Modify: `plugin/tests/test_repo_map_python.py` — import path
- Modify: `plugin/tests/test_repo_map_walker.py` — import paths (3 occurrences)

- [ ] **Step 1: Create `plugin/services/parsers/python.py`**

Copy the full content of `plugin/services/repo_map_python.py` but change the relative import on line 18 from:

```python
from .repo_map_types import ClassSymbol, FunctionSymbol
```

to:

```python
from ..repo_map_types import ClassSymbol, FunctionSymbol
```

The complete file (for clarity):

```python
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
    """Build 'def name(params) -> ReturnType' from a function_definition node."""
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
    """Parse Python source bytes; return (imports, classes, top-level functions)."""
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
```

- [ ] **Step 2: Create `plugin/services/parsers/__init__.py`**

```python
from .python import get_parser, parse_python_file

__all__ = ["get_parser", "parse_python_file"]
```

(JS/TS exports are added in Task 3.)

- [ ] **Step 3: Delete `plugin/services/repo_map_python.py`**

```bash
rm /home/sven/projects/plugins/Balu_Code/plugin/services/repo_map_python.py
```

- [ ] **Step 4: Update import in `plugin/services/rag_chunker.py`**

Change line 19:
```python
# before
from .repo_map_python import get_parser
# after
from .parsers.python import get_parser
```

- [ ] **Step 5: Update import in `plugin/services/repo_map.py`**

Change line 23:
```python
# before
from .repo_map_python import parse_python_file
# after
from .parsers.python import parse_python_file
```

- [ ] **Step 6: Update import in `plugin/tests/test_repo_map_python.py`**

Change line 5:
```python
# before
from plugin.services.repo_map_python import parse_python_file
# after
from plugin.services.parsers.python import parse_python_file
```

- [ ] **Step 7: Update imports in `plugin/tests/test_repo_map_walker.py`**

There are three occurrences (lines 77, 105, 127 — exact line numbers may shift slightly). Search for `from plugin.services.repo_map_python import parse_python_file as real` and replace all three:

```python
# before
from plugin.services.repo_map_python import parse_python_file as real
# after
from plugin.services.parsers.python import parse_python_file as real
```

- [ ] **Step 8: Run full test suite — must pass**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/ -q
```

Expected: all existing tests pass. Zero failures.

- [ ] **Step 9: Commit**

```bash
git add plugin/services/parsers/ plugin/services/rag_chunker.py plugin/services/repo_map.py plugin/tests/test_repo_map_python.py plugin/tests/test_repo_map_walker.py
git rm plugin/services/repo_map_python.py
git commit -m "refactor(parsers): move repo_map_python into parsers/ subpackage"
```

---

## Task 3: Implement `plugin/services/parsers/js_ts.py` (TDD)

**Files:**
- Create: `plugin/tests/test_parsers_js_ts.py`
- Create: `plugin/services/parsers/js_ts.py`
- Modify: `plugin/services/parsers/__init__.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_parsers_js_ts.py`:

```python
"""Tests for parse_js_ts_file."""

from __future__ import annotations

import pytest

from plugin.services.parsers.js_ts import parse_js_ts_file
from plugin.services.repo_map_types import ClassSymbol, FunctionSymbol


def test_empty_source_returns_three_empty_lists():
    imports, classes, functions = parse_js_ts_file(b"", ".js")
    assert imports == []
    assert classes == []
    assert functions == []


def test_function_declaration():
    src = b"function greet(name) { return `Hello ${name}`; }"
    _, _, functions = parse_js_ts_file(src, ".js")
    assert len(functions) == 1
    assert functions[0].name == "greet"
    assert "greet" in functions[0].signature


def test_async_function_declaration():
    src = b"async function fetchData(url) { return await fetch(url); }"
    _, _, functions = parse_js_ts_file(src, ".js")
    assert len(functions) == 1
    assert "async" in functions[0].signature


def test_generator_function_declaration():
    src = b"function* range(n) { for (let i = 0; i < n; i++) yield i; }"
    _, _, functions = parse_js_ts_file(src, ".js")
    assert len(functions) == 1
    assert "function*" in functions[0].signature


def test_class_declaration():
    src = b"class Animal {\n  constructor(name) { this.name = name; }\n  speak() {}\n}"
    _, classes, _ = parse_js_ts_file(src, ".js")
    assert len(classes) == 1
    assert classes[0].name == "Animal"
    assert any("speak" in m for m in classes[0].methods)


def test_class_with_extends():
    src = b"class Dog extends Animal { bark() {} }"
    _, classes, _ = parse_js_ts_file(src, ".js")
    assert len(classes) == 1
    assert "Animal" in classes[0].bases


def test_export_wrapped_function():
    src = b"export function add(a, b) { return a + b; }"
    _, _, functions = parse_js_ts_file(src, ".js")
    assert len(functions) == 1
    assert functions[0].name == "add"


def test_export_default_class():
    src = b"export default class App { render() { return null; } }"
    _, classes, _ = parse_js_ts_file(src, ".jsx")
    assert len(classes) == 1
    assert classes[0].name == "App"


def test_arrow_function_const():
    src = b"const square = (x) => x * x;"
    _, _, functions = parse_js_ts_file(src, ".js")
    assert len(functions) == 1
    assert functions[0].name == "square"
    assert "square" in functions[0].signature


def test_const_plain_value_not_included():
    src = b"const API_URL = 'https://example.com';"
    _, _, functions = parse_js_ts_file(src, ".js")
    assert functions == []


def test_import_statement():
    src = b"import React from 'react';\nimport { useState } from 'react';"
    imports, _, _ = parse_js_ts_file(src, ".jsx")
    assert "react" in imports


def test_ts_interface():
    src = b"interface User {\n  id: number;\n  name: string;\n  greet(): void;\n}"
    _, classes, _ = parse_js_ts_file(src, ".ts")
    assert len(classes) == 1
    assert classes[0].name == "User"


def test_ts_type_alias():
    src = b"type UserId = string | number;"
    _, _, functions = parse_js_ts_file(src, ".ts")
    assert len(functions) == 1
    assert functions[0].name == "UserId"
    assert "type UserId" in functions[0].signature


def test_tsx_class_component():
    src = b"export default class App extends React.Component {\n  render() { return null; }\n}"
    _, classes, _ = parse_js_ts_file(src, ".tsx")
    assert len(classes) == 1
    assert classes[0].name == "App"
    assert classes[0].bases  # has at least one base


def test_unknown_extension_raises():
    with pytest.raises(ValueError, match="Unsupported extension"):
        parse_js_ts_file(b"", ".rb")


def test_syntax_error_does_not_raise():
    # tree-sitter is error-tolerant — should not raise on bad input
    src = b"function valid() {} ===INVALID==="
    imports, classes, functions = parse_js_ts_file(src, ".js")
    assert any(f.name == "valid" for f in functions)
```

- [ ] **Step 2: Run tests — must fail**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/test_parsers_js_ts.py -v
```

Expected: `ModuleNotFoundError: No module named 'plugin.services.parsers.js_ts'`

- [ ] **Step 3: Implement `plugin/services/parsers/js_ts.py`**

```python
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

    elif nt in ("function_declaration", "generator_function_declaration"):
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
    if not source:
        return [], [], []
    parser = _get_parser_for_ext(extension)
    try:
        tree = parser.parse(source)
    except Exception:
        return [], [], []

    imports: list[str] = []
    classes: list[ClassSymbol] = []
    functions: list[FunctionSymbol] = []

    for node in tree.root_node.children:
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
        if nt in _SYMBOL_NODE_TYPES:
            ranges.append((node.start_point[0] + 1, node.end_point[0] + 1))
        elif nt == "export_statement":
            ranges.append((node.start_point[0] + 1, node.end_point[0] + 1))
        elif nt == "lexical_declaration" and _lexical_has_function(node):
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
```

- [ ] **Step 4: Update `plugin/services/parsers/__init__.py`**

```python
from .python import get_parser, parse_python_file
from .js_ts import (
    get_js_parser,
    get_ts_parser,
    get_tsx_parser,
    parse_js_ts_file,
    extract_top_level_ranges_js_ts,
)

__all__ = [
    "get_parser",
    "parse_python_file",
    "get_js_parser",
    "get_ts_parser",
    "get_tsx_parser",
    "parse_js_ts_file",
    "extract_top_level_ranges_js_ts",
]
```

- [ ] **Step 5: Run tests — must pass**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/test_parsers_js_ts.py -v
```

Expected: all 16 tests pass.

- [ ] **Step 6: Run full suite — still green**

```bash
.venv/bin/pytest plugin/tests/ -q
```

Expected: zero failures.

- [ ] **Step 7: Commit**

```bash
git add plugin/services/parsers/js_ts.py plugin/services/parsers/__init__.py plugin/tests/test_parsers_js_ts.py
git commit -m "feat(parsers): add JS/TS/JSX/TSX parser module"
```

---

## Task 4: Add `chunk_js_ts_file` to `rag_chunker.py` (TDD)

**Files:**
- Create: `plugin/tests/test_rag_chunker_js_ts.py`
- Modify: `plugin/services/rag_chunker.py`

- [ ] **Step 1: Write the failing tests**

Create `plugin/tests/test_rag_chunker_js_ts.py`:

```python
"""Tests for chunk_js_ts_file."""

from __future__ import annotations

from plugin.services.rag_chunker import Chunk, chunk_js_ts_file


def test_empty_source_returns_empty():
    assert chunk_js_ts_file("a.js", b"", ".js") == []


def test_single_function_one_chunk():
    src = b"function foo() {\n  return 1;\n}\n"
    chunks = chunk_js_ts_file("a.js", src, ".js")
    assert len(chunks) == 1
    c = chunks[0]
    assert c.file_path == "a.js"
    assert c.start_line == 1
    assert "foo" in c.text


def test_ts_interface_one_chunk():
    src = b"interface Foo {\n  bar(): void;\n}\n"
    chunks = chunk_js_ts_file("a.ts", src, ".ts")
    assert len(chunks) == 1
    assert "interface Foo" in chunks[0].text


def test_export_wrapped_is_one_chunk():
    src = b"export function add(a, b) {\n  return a + b;\n}\n"
    chunks = chunk_js_ts_file("a.ts", src, ".ts")
    assert len(chunks) == 1


def test_gap_between_symbols_emitted():
    src = (
        b"function foo() { return 1; }\n"
        b"\n"
        b"// standalone comment\n"
        b"\n"
        b"function bar() { return 2; }\n"
    )
    chunks = chunk_js_ts_file("a.js", src, ".js")
    assert len(chunks) == 3
    assert any("foo" in c.text for c in chunks)
    assert any("bar" in c.text for c in chunks)
    assert any("standalone comment" in c.text for c in chunks)


def test_long_function_split_into_sliding_windows():
    body = b"".join(f"  const x{i} = {i};\n".encode() for i in range(90))
    src = b"function big() {\n" + body + b"}\n"
    chunks = chunk_js_ts_file("a.js", src, ".js", window_lines=40, overlap_lines=10)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.start_line >= 1


def test_no_symbols_whole_file_windows():
    # Pure const assignments — no function values, so no symbol ranges
    src = b"\n".join(f"const x{i} = {i};".encode() for i in range(60)) + b"\n"
    chunks = chunk_js_ts_file("a.js", src, ".js", window_lines=20, overlap_lines=5)
    assert len(chunks) >= 2


def test_tsx_function_component_one_chunk():
    src = b"export default function App() {\n  return <div>Hello</div>;\n}\n"
    chunks = chunk_js_ts_file("App.tsx", src, ".tsx")
    assert len(chunks) == 1
    assert "App" in chunks[0].text
```

- [ ] **Step 2: Run tests — must fail**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/test_rag_chunker_js_ts.py -v
```

Expected: `ImportError: cannot import name 'chunk_js_ts_file'`

- [ ] **Step 3: Add `chunk_js_ts_file` to `plugin/services/rag_chunker.py`**

At the top of the file, add to the existing imports:

```python
from .parsers.js_ts import extract_top_level_ranges_js_ts
```

Then add the new function after `chunk_python_file` (before `_extract_top_level_ranges`):

```python
def chunk_js_ts_file(
    file_path: str,
    source: bytes,
    extension: str,
    *,
    window_lines: int = 40,
    overlap_lines: int = 10,
    symbol_max_lines: int = 80,
) -> list[Chunk]:
    """Split a JS/TS/JSX/TSX file into chunks for embedding.

    Same algorithm as chunk_python_file — symbol boundaries first, sliding
    windows for long symbols and files with no recognisable symbols.
    """
    if not source:
        return []

    text = source.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    n_lines = len(lines)
    if n_lines == 0:
        return []

    ranges = extract_top_level_ranges_js_ts(source, extension)

    if not ranges:
        return list(_sliding_windows(file_path, lines, 1, n_lines, window_lines, overlap_lines))

    chunks: list[Chunk] = []
    cursor = 1

    for start, end in ranges:
        if cursor <= start - 1:
            chunks.append(_build_chunk(file_path, lines, cursor, start - 1))

        span = end - start + 1
        if span <= symbol_max_lines:
            chunks.append(_build_chunk(file_path, lines, start, end))
        else:
            chunks.extend(
                _sliding_windows(file_path, lines, start, end, window_lines, overlap_lines)
            )

        cursor = end + 1

    if cursor <= n_lines:
        chunks.append(_build_chunk(file_path, lines, cursor, n_lines))

    return chunks
```

Also update `__all__` at the bottom of `rag_chunker.py`:

```python
__all__ = ["Chunk", "chunk_python_file", "chunk_js_ts_file"]
```

- [ ] **Step 4: Run tests — must pass**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/test_rag_chunker_js_ts.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest plugin/tests/ -q
```

Expected: zero failures.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/rag_chunker.py plugin/tests/test_rag_chunker_js_ts.py
git commit -m "feat(chunker): add chunk_js_ts_file for JS/TS/JSX/TSX"
```

---

## Task 5: Extend indexer to walk JS/TS files (TDD)

**Files:**
- Modify: `plugin/tests/test_indexer.py`
- Modify: `plugin/services/indexer.py`

- [ ] **Step 1: Add failing tests to `plugin/tests/test_indexer.py`**

Append these four tests at the end of the file (the `_write` helper and `index` fixture are already defined there):

```python
async def test_indexes_js_file(tmp_path, index):
    _write(tmp_path, "app.js", "function hello() { return 'hi'; }\n")
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.status == JobStatus.DONE
    assert job.files_processed == 1
    assert "app.js" in await index.all_indexed_paths()


async def test_indexes_ts_file(tmp_path, index):
    _write(
        tmp_path,
        "utils.ts",
        "export function add(a: number, b: number): number { return a + b; }\n",
    )
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.files_processed == 1
    assert "utils.ts" in await index.all_indexed_paths()


async def test_indexes_tsx_file(tmp_path, index):
    _write(tmp_path, "App.tsx", "export default function App() { return null; }\n")
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.files_processed == 1
    assert "App.tsx" in await index.all_indexed_paths()


async def test_indexes_mixed_py_ts_directory(tmp_path, index):
    _write(tmp_path, "main.py", "def run(): pass\n")
    _write(tmp_path, "utils.ts", "export const PI = 3.14;\n")
    _write(tmp_path, "App.tsx", "export default function App() { return null; }\n")
    job = IndexJob(id="j1", project_id=1, status=JobStatus.QUEUED)
    await run_index_job(job, project_root=tmp_path, rag=index)
    assert job.files_processed == 3
    paths = await index.all_indexed_paths()
    assert {"main.py", "utils.ts", "App.tsx"} <= paths
```

- [ ] **Step 2: Run new tests — must fail**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/test_indexer.py::test_indexes_js_file plugin/tests/test_indexer.py::test_indexes_ts_file plugin/tests/test_indexer.py::test_indexes_tsx_file plugin/tests/test_indexer.py::test_indexes_mixed_py_ts_directory -v
```

Expected: all 4 fail (files_processed == 0 because only `.py` is walked).

- [ ] **Step 3: Update `plugin/services/indexer.py`**

Replace the entire file with:

```python
"""Indexing worker coroutine.

Called by ``IndexJobTracker.start_job`` with an ``IndexJob`` that the
worker mutates as it progresses. Walks the project root, compares each
source file's sha1 against the cached sha1 in ``RagIndex``, chunks +
embeds + upserts changed files, and drops stale cache rows for deleted
files.

Supported extensions: .py, .js, .ts, .jsx, .tsx
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .index_jobs import IndexJob, JobStatus
from .rag_chunker import chunk_js_ts_file, chunk_python_file
from .rag_index import RagIndex
from .repo_map import IGNORE_DIRS

_SOURCE_EXTENSIONS = frozenset({".py", ".js", ".ts", ".jsx", ".tsx"})


async def run_index_job(
    job: IndexJob,
    *,
    project_root: Path,
    rag: RagIndex,
) -> None:
    """Drive an indexing pass. Mutates ``job`` in place as it progresses."""
    job.status = JobStatus.RUNNING

    seen_paths: set[str] = set()
    files_to_process: list[tuple[str, bytes, str]] = []

    for fs_path, rel_posix in _iter_source_files(project_root):
        seen_paths.add(rel_posix)
        content_bytes = fs_path.read_bytes()
        sha1 = hashlib.sha1(content_bytes, usedforsecurity=False).hexdigest()
        cached = await rag.get_file_sha1(rel_posix)
        if cached == sha1:
            continue
        files_to_process.append((rel_posix, content_bytes, sha1))

    job.files_total = len(files_to_process)

    for rel_posix, content_bytes, sha1 in files_to_process:
        ext = Path(rel_posix).suffix
        if ext == ".py":
            chunks = chunk_python_file(rel_posix, content_bytes)
        else:
            chunks = chunk_js_ts_file(rel_posix, content_bytes, ext)
        await rag.upsert_file_chunks(rel_posix, sha1, chunks)
        job.files_processed += 1
        job.chunks_total += len(chunks)

    indexed = await rag.all_indexed_paths()
    for stale in indexed - seen_paths:
        await rag.delete_file_chunks(stale)

    job.status = JobStatus.DONE


def _iter_source_files(project_root: Path):
    """Yield (fs_path, rel_posix) for every supported source file under project_root."""
    for dirpath_str, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        dirpath = Path(dirpath_str)
        for fname in filenames:
            if Path(fname).suffix not in _SOURCE_EXTENSIONS:
                continue
            fs_path = dirpath / fname
            if not fs_path.is_file():
                continue
            rel_posix = fs_path.relative_to(project_root).as_posix()
            yield fs_path, rel_posix


__all__ = ["run_index_job"]
```

- [ ] **Step 4: Run new indexer tests — must pass**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/test_indexer.py -v
```

Expected: all tests pass including the four new ones.

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest plugin/tests/ -q
```

Expected: zero failures.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/indexer.py plugin/tests/test_indexer.py
git commit -m "feat(indexer): extend to JS/TS/JSX/TSX via _iter_source_files"
```

---

## Task 6: Extend repo-map walker to handle JS/TS files (TDD)

**Files:**
- Modify: `plugin/tests/test_repo_map_walker.py`
- Modify: `plugin/services/repo_map.py`

- [ ] **Step 1: Add failing tests to `plugin/tests/test_repo_map_walker.py`**

Append these three tests at the end of the file (the `store`, `project_id`, and `_write` fixtures/helpers are already defined there):

```python
def test_walks_js_ts_source_files(tmp_path, store, project_id):
    _write(tmp_path, "a.py", "def foo(): pass\n")
    _write(tmp_path, "app.js", "function greet() {}\n")
    _write(tmp_path, "utils.ts", "export type Id = string;\n")
    _write(tmp_path, "App.tsx", "export default function App() { return null; }\n")
    _write(tmp_path, "README.md", "ignored\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    paths = {f.path for f in rm.walk_and_cache()}
    assert paths == {"a.py", "app.js", "utils.ts", "App.tsx"}


def test_js_function_symbols_extracted(tmp_path, store, project_id):
    _write(tmp_path, "app.js", "function greet(name) { return name; }\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm.walk_and_cache()
    assert len(files) == 1
    f = files[0]
    assert f.path == "app.js"
    assert any(fn.name == "greet" for fn in f.functions)


def test_ts_interface_appears_as_class_symbol(tmp_path, store, project_id):
    _write(tmp_path, "types.ts", "interface User { id: number; name: string; }\n")
    rm = RepoMap(project_root=tmp_path, store=store, project_id=project_id)
    files = rm.walk_and_cache()
    assert len(files) == 1
    assert any(c.name == "User" for c in files[0].classes)
```

- [ ] **Step 2: Run new tests — must fail**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/test_repo_map_walker.py::test_walks_js_ts_source_files plugin/tests/test_repo_map_walker.py::test_js_function_symbols_extracted plugin/tests/test_repo_map_walker.py::test_ts_interface_appears_as_class_symbol -v
```

Expected: `test_walks_js_ts_source_files` fails (only `a.py` is returned, not the JS/TS files).

- [ ] **Step 3: Update `plugin/services/repo_map.py`**

Change the import at line 23 and add the JS/TS import:

```python
# before
from .repo_map_python import parse_python_file
# after
from .parsers.python import parse_python_file
from .parsers.js_ts import parse_js_ts_file
```

Add the source extensions constant after the `IGNORE_DIRS` definition:

```python
_SOURCE_EXTENSIONS = frozenset({".py", ".js", ".ts", ".jsx", ".tsx"})
```

In `walk_and_cache`, replace the extension check and parser dispatch. Find the block:

```python
for fname in filenames:
    if not fname.endswith(".py"):
        continue
```

Replace with:

```python
for fname in filenames:
    ext = Path(fname).suffix
    if ext not in _SOURCE_EXTENSIONS:
        continue
```

Then find the parse dispatch (the two branches that call `parse_python_file` or use cached symbols). The cached branch stays unchanged. The uncached parse branch changes from:

```python
imports, classes, functions = parse_python_file(content_bytes)
```

to:

```python
if ext == ".py":
    imports, classes, functions = parse_python_file(content_bytes)
else:
    imports, classes, functions = parse_js_ts_file(content_bytes, ext)
```

Note: `ext` is computed from `fname` above, so it's in scope. The full updated `walk_and_cache` loop body for the uncached branch should look like:

```python
else:
    # Content changed or not cached — parse.
    if ext == ".py":
        imports, classes, functions = parse_python_file(content_bytes)
    else:
        imports, classes, functions = parse_js_ts_file(content_bytes, ext)
    self._store.upsert_repo_map_entry(
        project_id=self._project_id,
        file_path=rel_posix,
        mtime=mtime,
        sha1=sha1,
        symbols_json=_serialize_symbols(imports, classes, functions),
    )
```

Also add `Path` to the places where `fname` is used if `Path` is not already imported from `pathlib` — it is already imported at the top of `repo_map.py`.

- [ ] **Step 4: Run new repo-map tests — must pass**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/test_repo_map_walker.py -v
```

Expected: all tests pass, including the three new ones.

- [ ] **Step 5: Run full suite — final green**

```bash
.venv/bin/pytest plugin/tests/ -q
```

Expected: zero failures, all tests pass.

- [ ] **Step 6: Commit**

```bash
git add plugin/services/repo_map.py plugin/tests/test_repo_map_walker.py
git commit -m "feat(repo-map): extend walk_and_cache to JS/TS/JSX/TSX files"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run complete test suite one last time**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/pytest plugin/tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests pass, green output.

- [ ] **Step 2: Verify no stale references to the old module path**

```bash
grep -r "repo_map_python" /home/sven/projects/plugins/Balu_Code/plugin/ --include="*.py" | grep -v "__pycache__"
```

Expected: only comments in `repo_map_types.py` (the docstring). No live imports.

- [ ] **Step 3: Check ruff**

```bash
cd /home/sven/projects/plugins/Balu_Code
.venv/bin/ruff check plugin/services/parsers/ plugin/services/rag_chunker.py plugin/services/indexer.py plugin/services/repo_map.py
```

Expected: no errors.
