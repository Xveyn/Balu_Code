# Repo-Map (OpenCode-Reboot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject a token-budgeted, tree-sitter-driven structural map of the user's project into every `/chat/v2/{project_id}` call so qwen2.5-coder starts each turn with file/symbol awareness — without spending Read/Grep/Glob round-trips on discovery.

**Architecture:** Add `plugin/services/parsers/{python,js_ts}.py` (tree-sitter symbol extractors) and `plugin/services/repo_map.py` (walker, mtime-cached against existing `repo_map_cache` table, alphabetical render with token-budget truncation). Wire the rendered envelope as a **prefix to the user-message text** in `routes.py:chat_v2()` since OpenCode v1.14.50 exposes no `system_prompt` field. Reuses the Phase-2 `repo_map_cache` schema and `ProjectStore` methods that already exist but were never populated. Spec: [`2026-05-16-repo-map-opencode-reboot-design.md`](../specs/2026-05-16-repo-map-opencode-reboot-design.md).

**Tech Stack:** Python 3.13, FastAPI, pytest, `tree-sitter>=0.22`, `tree-sitter-python>=0.21`, `tree-sitter-javascript>=0.23`, `tree-sitter-typescript>=0.23`, existing sqlite3-backed `ProjectStore`.

---

## File Structure

```
plugin/
├── config.py                                  [MODIFY: lower repo_map_budget default, add repo_map_enabled]
├── schemas.py                                 [MODIFY: add RepoMapResponse, extend ConfigUpdateRequest]
├── routes.py                                  [MODIFY: prepend repo-map to chat_v2; add debug routes]
├── plugin.json                                [MODIFY: python_requirements += 4 tree-sitter pkgs]
├── requirements.txt                           [MODIFY: same 4]
├── pyproject.toml                             [MODIFY: same 4]
├── prompts/                                   [DELETE — dead]
│   ├── system.md
│   └── tool_use.md
└── services/
    ├── parsers/
    │   ├── __init__.py                        [CREATE: parse_file() dispatcher]
    │   ├── python.py                          [CREATE: parse_python_file()]
    │   └── js_ts.py                           [CREATE: parse_js_ts_file()]
    └── repo_map.py                            [CREATE: RepoMap, render, dataclasses]

plugin/tests/
├── fixtures/
│   └── repo_map/                              [CREATE: sample source files per language]
├── test_parsers_python.py                     [CREATE]
├── test_parsers_js_ts.py                      [CREATE]
├── test_parsers_dispatch.py                   [CREATE]
├── test_repo_map_walk.py                      [CREATE]
├── test_repo_map_render.py                    [CREATE]
├── test_routes_chat_v2.py                     [MODIFY: assert envelope prepended]
├── test_routes_repo_map.py                    [CREATE: GET + POST rebuild]
└── test_config.py                             [MODIFY: new field defaults]
```

Each file has one responsibility:
- `parsers/python.py` and `parsers/js_ts.py` are pure source-bytes-in, symbol-tuples-out.
- `parsers/__init__.py` only dispatches by extension; no parsing logic.
- `repo_map.py` knows about walking, caching, and rendering — but not about parsing internals.
- `routes.py` knows about HTTP and how to wire the map into a prompt; it does not parse.

---

## Task 1: Add tree-sitter dependencies

**Files:**
- Modify: `plugin/plugin.json` (python_requirements)
- Modify: `plugin/requirements.txt`
- Modify: `plugin/pyproject.toml` (dependencies)

- [ ] **Step 1: Add tree-sitter to plugin.json**

Edit `plugin/plugin.json`. Find `"python_requirements": [...]` and replace with:

```json
  "python_requirements": [
    "httpx>=0.27",
    "pydantic>=2.6",
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.21",
    "tree-sitter-javascript>=0.23",
    "tree-sitter-typescript>=0.23"
  ],
```

- [ ] **Step 2: Add tree-sitter to requirements.txt**

Append these lines to `plugin/requirements.txt`:

```
tree-sitter>=0.22
tree-sitter-python>=0.21
tree-sitter-javascript>=0.23
tree-sitter-typescript>=0.23
```

- [ ] **Step 3: Add tree-sitter to pyproject.toml**

Open `plugin/pyproject.toml`, find the `dependencies = [...]` block, append:

```toml
    "tree-sitter>=0.22",
    "tree-sitter-python>=0.21",
    "tree-sitter-javascript>=0.23",
    "tree-sitter-typescript>=0.23",
```

- [ ] **Step 4: Install into the active venv**

Run: `pip install 'tree-sitter>=0.22' 'tree-sitter-python>=0.21' 'tree-sitter-javascript>=0.23' 'tree-sitter-typescript>=0.23'`

Expected: four packages install. Verify:

```bash
python -c "import tree_sitter, tree_sitter_python, tree_sitter_javascript, tree_sitter_typescript; print('ok')"
```

Expected output: `ok`

- [ ] **Step 5: Commit**

```bash
git add plugin/plugin.json plugin/requirements.txt plugin/pyproject.toml
git commit -m "deps(repo-map): add tree-sitter + python/js/ts grammars"
```

---

## Task 2: Python parser — failing test

**Files:**
- Create: `plugin/services/parsers/__init__.py` (empty placeholder for package import)
- Create: `plugin/tests/test_parsers_python.py`

- [ ] **Step 1: Create empty package init**

Create `plugin/services/parsers/__init__.py` with the single line:

```python
"""Source-file symbol extractors. One module per language family."""
```

- [ ] **Step 2: Write the first failing test**

Create `plugin/tests/test_parsers_python.py`:

```python
"""Tests for plugin/services/parsers/python.py."""

from __future__ import annotations

from plugin.services.parsers.python import parse_python_file


def test_parses_simple_function():
    source = b"def foo(x: int) -> str:\n    return str(x)\n"
    imports, classes, functions = parse_python_file(source)
    assert imports == []
    assert classes == []
    assert len(functions) == 1
    assert functions[0].name == "foo"
    assert functions[0].signature == "def foo(x: int) -> str"
```

- [ ] **Step 3: Run the test to confirm it fails**

Run: `cd /home/sven/projects/plugins/Balu_Code && pytest plugin/tests/test_parsers_python.py -v`

Expected: `ModuleNotFoundError: No module named 'plugin.services.parsers.python'`

---

## Task 3: Python parser — minimal implementation

**Files:**
- Create: `plugin/services/parsers/python.py`

- [ ] **Step 1: Implement parse_python_file**

Create `plugin/services/parsers/python.py`:

```python
"""Tree-sitter Python symbol extractor.

Returns (imports, classes, functions) tuples. ClassSymbol / FunctionSymbol
are imported from repo_map. On parse error returns three empty lists —
the file's stub still appears in the repo map but with no extracted
symbols, so the agent at least sees the path.
"""

from __future__ import annotations

import tree_sitter_python
from tree_sitter import Language, Parser

from plugin.services.repo_map import ClassSymbol, FunctionSymbol

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
```

This imports from `repo_map`, which we haven't built yet — the test fails differently after this step. We pre-stage the dataclasses next.

- [ ] **Step 2: Create the dataclass stubs in repo_map.py**

Create `plugin/services/repo_map.py` with just the dataclasses for now (full class lands in Task 8):

```python
"""Token-budgeted, tree-sitter-driven repo map for the chat hot path.

Walks a project's root_path, caches symbols per file in the existing
repo_map_cache table (Phase-2 schema), and renders a budget-aware
overview to prepend to OpenCode user messages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassSymbol:
    name: str
    bases: list[str]
    methods: list[str]


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    signature: str


@dataclass(frozen=True)
class FileSymbols:
    path: str
    lines: int
    imports: list[str]
    classes: list[ClassSymbol]
    functions: list[FunctionSymbol]


@dataclass(frozen=True)
class RenderedMap:
    text: str
    file_count: int
    truncated_files: list[str]
    total_bytes: int


class RepoMapError(Exception):
    """Base for repo-map errors."""


class ProjectRootNotAccessible(RepoMapError):
    """Raised when the project root does not exist or is not a directory."""


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMapError",
]
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `pytest plugin/tests/test_parsers_python.py -v`

Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add plugin/services/parsers/ plugin/services/repo_map.py plugin/tests/test_parsers_python.py
git commit -m "feat(repo-map): tree-sitter python symbol extractor"
```

---

## Task 4: Python parser — expand coverage

**Files:**
- Modify: `plugin/tests/test_parsers_python.py`

- [ ] **Step 1: Add tests for classes, imports, async, decorated, edge cases**

Append to `plugin/tests/test_parsers_python.py`:

```python
def test_parses_class_with_methods():
    source = b"""\
class Worker(Base):
    def step(self) -> None:
        pass

    async def run(self, n: int = 0) -> int:
        return n
"""
    _, classes, _ = parse_python_file(source)
    assert len(classes) == 1
    c = classes[0]
    assert c.name == "Worker"
    assert c.bases == ["Base"]
    assert c.methods == [
        "def step(self) -> None",
        "async def run(self, n: int = 0) -> int",
    ]


def test_parses_decorated_function():
    source = b"""\
@cached
def helper(x: int) -> str:
    return str(x)
"""
    _, _, functions = parse_python_file(source)
    assert len(functions) == 1
    assert functions[0].name == "helper"
    assert functions[0].signature == "def helper(x: int) -> str"


def test_parses_imports():
    source = b"""\
import os
import os.path as op
from pathlib import Path
from .rel import thing
"""
    imports, _, _ = parse_python_file(source)
    assert imports == ["os", "os.path", "pathlib", ".rel"]


def test_class_with_multiple_bases():
    source = b"class C(A, B, M.X):\n    pass\n"
    _, classes, _ = parse_python_file(source)
    assert classes[0].bases == ["A", "B", "M.X"]


def test_empty_file():
    imports, classes, functions = parse_python_file(b"")
    assert imports == []
    assert classes == []
    assert functions == []


def test_syntax_error_returns_partial():
    source = b"def broken(\n"
    imports, classes, functions = parse_python_file(source)
    assert imports == []
    # Parser may still emit a function symbol with partial signature — tolerate either
    assert isinstance(functions, list)
    assert isinstance(classes, list)


def test_decorated_method_inside_class():
    source = b"""\
class C:
    @property
    def name(self) -> str:
        return "x"
"""
    _, classes, _ = parse_python_file(source)
    assert classes[0].methods == ["def name(self) -> str"]
```

- [ ] **Step 2: Run the tests**

Run: `pytest plugin/tests/test_parsers_python.py -v`

Expected: 7 passed (the original + 6 new).

- [ ] **Step 3: Commit**

```bash
git add plugin/tests/test_parsers_python.py
git commit -m "test(repo-map): expand python parser coverage"
```

---

## Task 5: JS/TS parser — failing tests

**Files:**
- Create: `plugin/tests/test_parsers_js_ts.py`

- [ ] **Step 1: Write the test suite**

Create `plugin/tests/test_parsers_js_ts.py`:

```python
"""Tests for plugin/services/parsers/js_ts.py."""

from __future__ import annotations

from plugin.services.parsers.js_ts import parse_js_ts_file


def test_js_function_declaration():
    source = b"function hello(name) { return 'hi ' + name; }\n"
    imports, classes, functions = parse_js_ts_file(source, ".js")
    assert imports == []
    assert classes == []
    assert len(functions) == 1
    assert functions[0].name == "hello"
    assert functions[0].signature == "function hello(name)"


def test_ts_function_declaration():
    source = b"function add(a: number, b: number): number { return a + b; }\n"
    _, _, functions = parse_js_ts_file(source, ".ts")
    assert functions[0].name == "add"
    assert functions[0].signature == "function add(a: number, b: number): number"


def test_ts_class_with_methods():
    source = b"""\
class Worker extends Base {
    step(): void { }
    async run(n: number = 0): Promise<number> { return n; }
}
"""
    _, classes, _ = parse_js_ts_file(source, ".ts")
    assert len(classes) == 1
    c = classes[0]
    assert c.name == "Worker"
    assert c.bases == ["Base"]
    assert c.methods == [
        "step(): void",
        "async run(n: number = 0): Promise<number>",
    ]


def test_ts_interface_renders_as_class():
    source = b"""\
interface Handler {
    handle(input: string): Promise<void>;
    name: string;
}
"""
    _, classes, _ = parse_js_ts_file(source, ".ts")
    assert len(classes) == 1
    c = classes[0]
    assert c.name == "Handler"
    assert c.bases == []
    assert "handle(input: string): Promise<void>" in c.methods


def test_ts_type_alias_as_function():
    source = b"type ID = string | number;\n"
    _, _, functions = parse_js_ts_file(source, ".ts")
    assert any(f.name == "ID" for f in functions)


def test_js_arrow_const():
    source = b"const greet = (n) => 'hi ' + n;\n"
    _, _, functions = parse_js_ts_file(source, ".js")
    assert any(f.name == "greet" for f in functions)


def test_js_import_collects_module():
    source = b"""\
import fs from 'fs';
import { join } from 'node:path';
"""
    imports, _, _ = parse_js_ts_file(source, ".js")
    assert imports == ["fs", "node:path"]


def test_export_function_unwrapped():
    source = b"export function hi() { }\n"
    _, _, functions = parse_js_ts_file(source, ".ts")
    assert functions[0].name == "hi"


def test_empty_file_js():
    imports, classes, functions = parse_js_ts_file(b"", ".js")
    assert imports == []
    assert classes == []
    assert functions == []


def test_unknown_extension_returns_empty():
    imports, classes, functions = parse_js_ts_file(b"x = 1\n", ".xyz")
    assert imports == []
    assert classes == []
    assert functions == []
```

- [ ] **Step 2: Run the suite to confirm it fails**

Run: `pytest plugin/tests/test_parsers_js_ts.py -v`

Expected: `ModuleNotFoundError: No module named 'plugin.services.parsers.js_ts'`

---

## Task 6: JS/TS parser — implementation

**Files:**
- Create: `plugin/services/parsers/js_ts.py`

- [ ] **Step 1: Implement parse_js_ts_file**

Create `plugin/services/parsers/js_ts.py`:

```python
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
        for c in heritage.named_children:
            bases.append(_node_text(c, source))
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
```

- [ ] **Step 2: Run the JS/TS suite**

Run: `pytest plugin/tests/test_parsers_js_ts.py -v`

Expected: 10 passed.

- [ ] **Step 3: Commit**

```bash
git add plugin/services/parsers/js_ts.py plugin/tests/test_parsers_js_ts.py
git commit -m "feat(repo-map): tree-sitter js/ts symbol extractor"
```

---

## Task 7: Parser dispatch

**Files:**
- Modify: `plugin/services/parsers/__init__.py`
- Create: `plugin/tests/test_parsers_dispatch.py`

- [ ] **Step 1: Write the dispatcher tests**

Create `plugin/tests/test_parsers_dispatch.py`:

```python
"""Tests for parsers/__init__.py dispatcher."""

from __future__ import annotations

from plugin.services.parsers import parse_file


def test_dispatches_python():
    _, _, functions = parse_file(b"def x(): pass\n", ".py")
    assert functions[0].name == "x"


def test_dispatches_typescript():
    _, _, functions = parse_file(b"function y(): void { }\n", ".ts")
    assert functions[0].name == "y"


def test_dispatches_javascript():
    _, _, functions = parse_file(b"function z() { }\n", ".js")
    assert functions[0].name == "z"


def test_dispatches_jsx():
    _, _, functions = parse_file(b"function A() { return null; }\n", ".jsx")
    assert functions[0].name == "A"


def test_dispatches_tsx():
    _, _, functions = parse_file(
        b"function Comp(): JSX.Element { return null as any; }\n", ".tsx"
    )
    assert functions[0].name == "Comp"


def test_unknown_extension_returns_empty():
    assert parse_file(b"anything", ".rs") == ([], [], [])
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest plugin/tests/test_parsers_dispatch.py -v`

Expected: `ImportError: cannot import name 'parse_file' from 'plugin.services.parsers'`

- [ ] **Step 3: Implement the dispatcher**

Replace `plugin/services/parsers/__init__.py` with:

```python
"""Source-file symbol extractors. One module per language family."""

from __future__ import annotations

from plugin.services.parsers.js_ts import parse_js_ts_file
from plugin.services.parsers.python import parse_python_file
from plugin.services.repo_map import ClassSymbol, FunctionSymbol

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
```

- [ ] **Step 4: Run the dispatcher suite**

Run: `pytest plugin/tests/test_parsers_dispatch.py -v`

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin/services/parsers/__init__.py plugin/tests/test_parsers_dispatch.py
git commit -m "feat(repo-map): extension dispatcher for language parsers"
```

---

## Task 8: RepoMap walker — failing tests

**Files:**
- Create: `plugin/tests/test_repo_map_walk.py`

- [ ] **Step 1: Write walk + cache tests**

Create `plugin/tests/test_repo_map_walk.py`:

```python
"""Tests for plugin/services/repo_map.py RepoMap.walk_and_cache()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugin.services.project_store import ProjectStore
from plugin.services.repo_map import (
    FileSymbols,
    ProjectRootNotAccessible,
    RepoMap,
)


@pytest.fixture
def store(tmp_path):
    s = ProjectStore(tmp_path / "store.db")
    yield s
    s.close()


@pytest.fixture
def project(store, tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    p = store.create_project("p", str(root), None)
    return p, root


def test_walk_collects_python_files(store, project):
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    (root / "b.py").write_text("class C: pass\n")
    rm = RepoMap(root, store, project_id=project[0].id)
    files = rm.walk_and_cache()
    paths = sorted(f.path for f in files)
    assert paths == ["a.py", "b.py"]


def test_walk_collects_js_and_ts(store, project):
    _, root = project
    (root / "a.ts").write_text("function f() { }\n")
    (root / "b.js").write_text("function g() { }\n")
    (root / "c.tsx").write_text("function H() { return null as any; }\n")
    rm = RepoMap(root, store, project_id=project[0].id)
    files = rm.walk_and_cache()
    paths = sorted(f.path for f in files)
    assert paths == ["a.ts", "b.js", "c.tsx"]


def test_walk_ignores_node_modules(store, project):
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    nm = root / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "ignored.js").write_text("function x() { }\n")
    rm = RepoMap(root, store, project_id=project[0].id)
    files = rm.walk_and_cache()
    assert [f.path for f in files] == ["a.py"]


def test_walk_ignores_hidden_dirs(store, project):
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    (root / ".git").mkdir()
    (root / ".git" / "x.py").write_text("def x(): pass\n")
    rm = RepoMap(root, store, project_id=project[0].id)
    files = rm.walk_and_cache()
    assert [f.path for f in files] == ["a.py"]


def test_walk_populates_cache_first_run(store, project):
    pid = project[0].id
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    rm = RepoMap(root, store, project_id=pid)
    rm.walk_and_cache()
    rows = store.list_repo_map_entries(pid)
    assert len(rows) == 1
    assert rows[0].file_path == "a.py"
    payload = json.loads(rows[0].symbols_json)
    assert payload["v"] == 1
    assert payload["functions"][0]["name"] == "foo"


def test_walk_cache_hit_skips_parser(monkeypatch, store, project):
    pid = project[0].id
    _, root = project
    (root / "a.py").write_text("def foo(): pass\n")
    rm = RepoMap(root, store, project_id=pid)
    rm.walk_and_cache()

    from plugin.services.parsers import python as py_mod

    call_count = {"n": 0}
    real = py_mod.parse_python_file

    def counting(source):
        call_count["n"] += 1
        return real(source)

    monkeypatch.setattr(py_mod, "parse_python_file", counting)
    # Also patch the dispatcher which captured the original at import time
    from plugin.services import parsers as parsers_mod

    monkeypatch.setattr(parsers_mod, "parse_python_file", counting)

    rm.walk_and_cache()
    assert call_count["n"] == 0  # cache hit — no re-parse


def test_walk_reparses_after_content_change(store, project):
    pid = project[0].id
    _, root = project
    f = root / "a.py"
    f.write_text("def foo(): pass\n")
    rm = RepoMap(root, store, project_id=pid)
    rm.walk_and_cache()

    # Modify content + bump mtime
    import os

    f.write_text("def bar(): pass\n")
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 10))

    files = rm.walk_and_cache()
    assert files[0].functions[0].name == "bar"


def test_walk_drops_deleted_files_from_cache(store, project):
    pid = project[0].id
    _, root = project
    a = root / "a.py"
    b = root / "b.py"
    a.write_text("def x(): pass\n")
    b.write_text("def y(): pass\n")
    rm = RepoMap(root, store, project_id=pid)
    rm.walk_and_cache()
    assert len(store.list_repo_map_entries(pid)) == 2
    b.unlink()
    rm.walk_and_cache()
    rows = store.list_repo_map_entries(pid)
    assert [r.file_path for r in rows] == ["a.py"]


def test_walk_raises_when_root_missing(store, tmp_path):
    p = store.create_project("p", str(tmp_path / "does_not_exist"), None)
    rm = RepoMap(Path(p.root_path), store, project_id=p.id)
    with pytest.raises(ProjectRootNotAccessible):
        rm.walk_and_cache()


def test_walk_returns_empty_for_empty_project(store, project):
    _, root = project
    rm = RepoMap(root, store, project_id=project[0].id)
    assert rm.walk_and_cache() == []
```

- [ ] **Step 2: Run the suite to confirm failure**

Run: `pytest plugin/tests/test_repo_map_walk.py -v`

Expected: many failures — `RepoMap` class has no `__init__`, no `walk_and_cache`, etc.

---

## Task 9: RepoMap walker — implementation

**Files:**
- Modify: `plugin/services/repo_map.py`

- [ ] **Step 1: Extend repo_map.py with walk_and_cache**

Replace the contents of `plugin/services/repo_map.py` with:

```python
"""Token-budgeted, tree-sitter-driven repo map for the chat hot path.

Walks a project's root_path, caches symbols per file in the existing
repo_map_cache table (Phase-2 schema), and renders a budget-aware
overview to prepend to OpenCode user messages.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from plugin.services.project_store import ProjectStore

_SOURCE_EXTENSIONS = frozenset({".py", ".js", ".jsx", ".ts", ".tsx"})
_IGNORE_DIRS = frozenset(
    {
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".git",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        "out",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "htmlcov",
        ".tox",
        ".next",
        ".nuxt",
        ".turbo",
        "coverage",
    }
)
_IGNORE_SUFFIX_GLOBS = (".min.js", ".d.ts")
_PAYLOAD_VERSION = 1


@dataclass(frozen=True)
class ClassSymbol:
    name: str
    bases: list[str]
    methods: list[str]


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    signature: str


@dataclass(frozen=True)
class FileSymbols:
    path: str
    lines: int
    imports: list[str]
    classes: list[ClassSymbol]
    functions: list[FunctionSymbol]


@dataclass(frozen=True)
class RenderedMap:
    text: str
    file_count: int
    truncated_files: list[str]
    total_bytes: int


class RepoMapError(Exception):
    """Base for repo-map errors."""


class ProjectRootNotAccessible(RepoMapError):
    """Raised when the project root does not exist or is not a directory."""


def _is_source_file(name: str) -> bool:
    if any(name.endswith(s) for s in _IGNORE_SUFFIX_GLOBS):
        return False
    suffix = Path(name).suffix
    return suffix in _SOURCE_EXTENSIONS


def _iter_source_files(project_root: Path):
    """Yield (absolute_path, relpath_posix) for every supported source file."""
    stack: list[Path] = [project_root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (PermissionError, FileNotFoundError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _IGNORE_DIRS:
                    continue
                if entry.name.startswith(".") and entry.name not in {"."}:
                    continue
                stack.append(entry)
            elif entry.is_file() and _is_source_file(entry.name):
                rel = entry.relative_to(project_root).as_posix()
                yield entry, rel


def _serialize_symbols(
    lines: int,
    imports: list[str],
    classes: list[ClassSymbol],
    functions: list[FunctionSymbol],
) -> str:
    return json.dumps(
        {
            "v": _PAYLOAD_VERSION,
            "lines": lines,
            "imports": imports,
            "classes": [
                {"name": c.name, "bases": c.bases, "methods": c.methods}
                for c in classes
            ],
            "functions": [
                {"name": f.name, "signature": f.signature} for f in functions
            ],
        },
        separators=(",", ":"),
    )


def _deserialize_symbols(blob: str, relpath: str) -> FileSymbols:
    raw = json.loads(blob)
    return FileSymbols(
        path=relpath,
        lines=raw.get("lines", 0),
        imports=list(raw.get("imports", [])),
        classes=[
            ClassSymbol(name=c["name"], bases=list(c["bases"]), methods=list(c["methods"]))
            for c in raw.get("classes", [])
        ],
        functions=[
            FunctionSymbol(name=f["name"], signature=f["signature"])
            for f in raw.get("functions", [])
        ],
    )


class RepoMap:
    """Walks a project root, caches parsed symbols, renders a budget-aware map."""

    def __init__(self, project_root: Path, store: ProjectStore, project_id: int) -> None:
        self._root = project_root
        self._store = store
        self._pid = project_id

    def walk_and_cache(self) -> list[FileSymbols]:
        if not self._root.exists() or not self._root.is_dir():
            raise ProjectRootNotAccessible(str(self._root))

        # Index existing cache rows by file_path for O(1) lookup.
        existing = {r.file_path: r for r in self._store.list_repo_map_entries(self._pid)}

        from plugin.services.parsers import parse_file  # local import: avoid cycles

        visited: set[str] = set()
        results: list[FileSymbols] = []

        for fs_path, relpath in _iter_source_files(self._root):
            visited.add(relpath)
            try:
                mtime = fs_path.stat().st_mtime
            except OSError:
                continue

            cached = existing.get(relpath)
            if cached is not None and abs(cached.mtime - mtime) < 1e-6:
                results.append(_deserialize_symbols(cached.symbols_json, relpath))
                continue

            try:
                raw = fs_path.read_bytes()
            except OSError:
                continue

            sha1 = hashlib.sha1(raw).hexdigest()

            if cached is not None and cached.sha1 == sha1:
                # mtime touched without content change: refresh mtime, reuse symbols.
                self._store.upsert_repo_map_entry(
                    self._pid, relpath, mtime, sha1, cached.symbols_json
                )
                results.append(_deserialize_symbols(cached.symbols_json, relpath))
                continue

            extension = fs_path.suffix
            imports, classes, functions = parse_file(raw, extension)
            line_count = raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
            blob = _serialize_symbols(line_count, imports, classes, functions)
            self._store.upsert_repo_map_entry(self._pid, relpath, mtime, sha1, blob)
            results.append(
                FileSymbols(
                    path=relpath,
                    lines=line_count,
                    imports=imports,
                    classes=classes,
                    functions=functions,
                )
            )

        self._store.delete_repo_map_entries(self._pid, visited)
        return results

    @staticmethod
    def render(
        files: list[FileSymbols],
        *,
        budget_tokens: int = 2048,
        project_name: str = "",
    ) -> RenderedMap:
        # Implemented in Task 11.
        raise NotImplementedError


__all__ = [
    "ClassSymbol",
    "FileSymbols",
    "FunctionSymbol",
    "ProjectRootNotAccessible",
    "RenderedMap",
    "RepoMap",
    "RepoMapError",
]
```

- [ ] **Step 2: Run the walker tests**

Run: `pytest plugin/tests/test_repo_map_walk.py -v`

Expected: 10 passed.

- [ ] **Step 3: Run the entire suite to catch regressions**

Run: `pytest plugin/tests/ -v -x`

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add plugin/services/repo_map.py plugin/tests/test_repo_map_walk.py
git commit -m "feat(repo-map): walker + mtime/sha1 cache"
```

---

## Task 10: RepoMap.render — failing tests

**Files:**
- Create: `plugin/tests/test_repo_map_render.py`

- [ ] **Step 1: Write render tests**

Create `plugin/tests/test_repo_map_render.py`:

```python
"""Tests for plugin/services/repo_map.py RepoMap.render()."""

from __future__ import annotations

from plugin.services.repo_map import (
    ClassSymbol,
    FileSymbols,
    FunctionSymbol,
    RepoMap,
)


def _file(path: str, *, lines: int = 10, imports=None, classes=None, functions=None):
    return FileSymbols(
        path=path,
        lines=lines,
        imports=imports or [],
        classes=classes or [],
        functions=functions or [],
    )


def test_empty_files_returns_envelope_only():
    rendered = RepoMap.render([], budget_tokens=2048, project_name="x")
    assert rendered.file_count == 0
    assert rendered.truncated_files == []
    assert "<repo_map" in rendered.text
    assert 'project="x"' in rendered.text
    assert 'files="0"' in rendered.text
    assert "</repo_map>" in rendered.text


def test_single_file_renders_header_and_sections():
    files = [
        _file(
            "a.py",
            lines=42,
            imports=["os"],
            classes=[ClassSymbol(name="C", bases=["B"], methods=["def m(self) -> None"])],
            functions=[FunctionSymbol(name="f", signature="def f() -> int")],
        )
    ]
    rendered = RepoMap.render(files, budget_tokens=2048)
    assert rendered.file_count == 1
    assert "=== a.py (42 lines)" in rendered.text
    assert "imports: os" in rendered.text
    assert "classes:" in rendered.text
    assert "class C(B):" in rendered.text
    assert "def m(self) -> None" in rendered.text
    assert "functions:" in rendered.text
    assert "def f() -> int" in rendered.text


def test_files_sorted_alphabetically():
    files = [
        _file("z.py", functions=[FunctionSymbol(name="z", signature="def z()")]),
        _file("a.py", functions=[FunctionSymbol(name="a", signature="def a()")]),
        _file("m.py", functions=[FunctionSymbol(name="m", signature="def m()")]),
    ]
    rendered = RepoMap.render(files, budget_tokens=2048)
    a_idx = rendered.text.index("=== a.py")
    m_idx = rendered.text.index("=== m.py")
    z_idx = rendered.text.index("=== z.py")
    assert a_idx < m_idx < z_idx


def test_empty_sections_omitted():
    files = [_file("a.py", functions=[FunctionSymbol(name="x", signature="def x()")])]
    rendered = RepoMap.render(files, budget_tokens=2048)
    assert "imports:" not in rendered.text
    assert "classes:" not in rendered.text
    assert "functions:" in rendered.text


def test_class_without_bases_renders_plain():
    files = [_file("a.py", classes=[ClassSymbol(name="C", bases=[], methods=["def m()"])])]
    rendered = RepoMap.render(files, budget_tokens=2048)
    assert "class C:" in rendered.text


def test_budget_truncates_excess_files():
    # Build many small files so the budget is exceeded
    files = [
        _file(f"f{i:03d}.py", functions=[FunctionSymbol(name="g", signature="def g()")])
        for i in range(200)
    ]
    rendered = RepoMap.render(files, budget_tokens=64)  # very tight budget
    assert rendered.file_count < 200
    assert len(rendered.truncated_files) > 0
    # Truncated must be the tail (alphabetical)
    truncated_set = set(rendered.truncated_files)
    rendered_paths = [f"f{i:03d}.py" for i in range(rendered.file_count)]
    for p in rendered_paths:
        assert p not in truncated_set


def test_total_bytes_matches_text_length():
    files = [_file("a.py", functions=[FunctionSymbol(name="x", signature="def x()")])]
    rendered = RepoMap.render(files, budget_tokens=2048)
    assert rendered.total_bytes == len(rendered.text.encode("utf-8"))


def test_envelope_contains_metadata():
    files = [_file("a.py", functions=[FunctionSymbol(name="x", signature="def x()")])]
    rendered = RepoMap.render(files, budget_tokens=999, project_name="balu-code")
    assert 'project="balu-code"' in rendered.text
    assert 'budget="999"' in rendered.text
    assert 'files="1"' in rendered.text
    assert "generated=" in rendered.text
```

- [ ] **Step 2: Run the suite to confirm failure**

Run: `pytest plugin/tests/test_repo_map_render.py -v`

Expected: failures because `render()` raises `NotImplementedError`.

---

## Task 11: RepoMap.render — implementation

**Files:**
- Modify: `plugin/services/repo_map.py`

- [ ] **Step 1: Implement render()**

In `plugin/services/repo_map.py`, replace the `render` staticmethod body and add a helper. Find:

```python
    @staticmethod
    def render(
        files: list[FileSymbols],
        *,
        budget_tokens: int = 2048,
        project_name: str = "",
    ) -> RenderedMap:
        # Implemented in Task 11.
        raise NotImplementedError
```

Replace with:

```python
    @staticmethod
    def render(
        files: list[FileSymbols],
        *,
        budget_tokens: int = 2048,
        project_name: str = "",
    ) -> RenderedMap:
        """Render `files` into a token-budgeted <repo_map>…</repo_map> envelope.

        Files are sorted alphabetically by path. Each file block is appended
        in order while accumulated `len(text) // 4` stays under budget.
        Remaining files are dropped into truncated_files.
        """
        from datetime import UTC, datetime

        sorted_files = sorted(files, key=lambda f: f.path)
        included_blocks: list[str] = []
        truncated: list[str] = []

        body_budget = max(0, budget_tokens)
        accumulated_chars = 0
        char_budget = body_budget * 4

        for fs in sorted_files:
            block = _render_file_block(fs)
            block_chars = len(block)
            if truncated or (accumulated_chars + block_chars) > char_budget:
                truncated.append(fs.path)
                continue
            included_blocks.append(block)
            accumulated_chars += block_chars

        body = "\n".join(included_blocks)
        generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        open_tag = (
            f'<repo_map project="{project_name}" generated="{generated}" '
            f'budget="{body_budget}" files="{len(included_blocks)}">'
        )
        if body:
            text = f"{open_tag}\n{body}\n</repo_map>"
        else:
            text = f"{open_tag}\n</repo_map>"

        return RenderedMap(
            text=text,
            file_count=len(included_blocks),
            truncated_files=truncated,
            total_bytes=len(text.encode("utf-8")),
        )
```

Then add this module-level helper, placed above the `RepoMap` class definition:

```python
def _render_class_block(c: ClassSymbol) -> str:
    head = f"  class {c.name}({', '.join(c.bases)}):" if c.bases else f"  class {c.name}:"
    if not c.methods:
        return head
    method_lines = "\n".join(f"    {m}" for m in c.methods)
    return f"{head}\n{method_lines}"


def _render_file_block(fs: FileSymbols) -> str:
    lines: list[str] = [f"=== {fs.path} ({fs.lines} lines)"]
    if fs.imports:
        lines.append(f"imports: {', '.join(fs.imports)}")
    if fs.classes:
        lines.append("classes:")
        for c in fs.classes:
            lines.append(_render_class_block(c))
    if fs.functions:
        lines.append("functions:")
        for f in fs.functions:
            lines.append(f"  {f.signature}")
    return "\n".join(lines)
```

- [ ] **Step 2: Run the render tests**

Run: `pytest plugin/tests/test_repo_map_render.py -v`

Expected: 8 passed.

- [ ] **Step 3: Run the whole suite**

Run: `pytest plugin/tests/ -v`

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add plugin/services/repo_map.py plugin/tests/test_repo_map_render.py
git commit -m "feat(repo-map): budget-aware alphabetical renderer"
```

---

## Task 12: Config — add repo_map_enabled, lower default budget

**Files:**
- Modify: `plugin/config.py`
- Modify: `plugin/schemas.py` (ConfigUpdateRequest)
- Modify: `plugin/tests/test_config.py`

- [ ] **Step 1: Add config tests**

Append to `plugin/tests/test_config.py`:

```python
def test_repo_map_enabled_defaults_true():
    from plugin.config import BaluCodePluginConfig

    assert BaluCodePluginConfig().repo_map_enabled is True


def test_repo_map_budget_default_is_2048():
    from plugin.config import BaluCodePluginConfig

    assert BaluCodePluginConfig().repo_map_budget == 2048
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest plugin/tests/test_config.py -v -k "repo_map"`

Expected: 2 failures — `repo_map_enabled` missing, `repo_map_budget == 6144`.

- [ ] **Step 3: Update config**

In `plugin/config.py`, replace the line:

```python
    repo_map_budget: int = 6144
```

with:

```python
    repo_map_enabled: bool = True
    repo_map_budget: int = 2048
```

- [ ] **Step 4: Update ConfigUpdateRequest**

In `plugin/schemas.py`, inside `ConfigUpdateRequest`, find:

```python
    repo_map_budget: int | None = None
```

Replace with:

```python
    repo_map_enabled: bool | None = None
    repo_map_budget: int | None = None
```

- [ ] **Step 5: Run config tests**

Run: `pytest plugin/tests/test_config.py -v -k "repo_map"`

Expected: 2 passed.

- [ ] **Step 6: Run the whole suite**

Run: `pytest plugin/tests/ -v`

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add plugin/config.py plugin/schemas.py plugin/tests/test_config.py
git commit -m "feat(repo-map): config flag repo_map_enabled, default budget 2048"
```

---

## Task 13: Add RepoMapResponse schema

**Files:**
- Modify: `plugin/schemas.py`

- [ ] **Step 1: Append RepoMapResponse**

In `plugin/schemas.py`, after `RuntimeCredentialsResponse`, add:

```python
class RepoMapResponse(BaseModel):
    text: str
    file_count: int
    truncated_files: list[str]
    total_bytes: int
```

And add `"RepoMapResponse"` to the `__all__` list, preserving alphabetical order — insert between `"ProjectsResponse"` and `"RuntimeCredentialsResponse"`.

- [ ] **Step 2: Verify with a quick import**

Run: `python -c "from plugin.schemas import RepoMapResponse; print(RepoMapResponse(text='', file_count=0, truncated_files=[], total_bytes=0))"`

Expected: prints a serialized model — no ImportError.

- [ ] **Step 3: Commit**

```bash
git add plugin/schemas.py
git commit -m "feat(repo-map): RepoMapResponse schema"
```

---

## Task 14: chat_v2 — prepend the repo-map envelope

**Files:**
- Modify: `plugin/routes.py`
- Modify: `plugin/tests/test_routes_chat_v2.py`

- [ ] **Step 1: Add a test asserting the envelope is prepended**

Open `plugin/tests/test_routes_chat_v2.py` and locate the existing happy-path test (the one that uses `app_with_mocked_client`). Append a new test in the same file:

```python
def test_chat_v2_prepends_repo_map_envelope(monkeypatch, tmp_path):
    """The user-message text sent to opencode must start with a <repo_map> block."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock

    from plugin import deps
    from plugin.config import BaluCodePluginConfig
    from plugin.routes import build_router
    from plugin.services.audit import AuditLogger
    from plugin.services.ollama_client import OllamaClient
    from plugin.services.opencode_client import OpencodeClient
    from plugin.services.project_store import ProjectStore

    # Real project + a real source file so the walker has work
    root = tmp_path / "userproj"
    root.mkdir()
    (root / "hello.py").write_text("def hello(): return 1\n")

    store = ProjectStore(tmp_path / "store.db")
    project = store.create_project("p", str(root), None)
    store.set_opencode_session_id(project.id, "ses_test")

    audit = AuditLogger(tmp_path / "audit.db")
    config = BaluCodePluginConfig()
    deps.set_singletons(
        store=store,
        ollama=OllamaClient("http://127.0.0.1:11434"),
        plugin_config=config,
        audit_log=audit,
        data_dir=tmp_path,
    )

    fake_opencode = AsyncMock(spec=OpencodeClient)
    fake_opencode.prompt = AsyncMock(
        return_value={"info": {"id": "msg"}, "parts": [{"type": "text", "text": "ok"}]}
    )
    fake_opencode.create_session = AsyncMock(return_value="ses_test")
    deps.set_opencode(handle=None, client=fake_opencode)  # type: ignore[arg-type]

    app = FastAPI()
    app.include_router(build_router())

    # Auth bypass
    from app.api import deps as app_deps

    app.dependency_overrides[app_deps.get_current_user] = lambda: object()

    client = TestClient(app)
    resp = client.post(
        f"/chat/v2/{project.id}",
        json={"messages": [{"role": "user", "content": "list the files"}]},
    )
    assert resp.status_code == 200

    args, kwargs = fake_opencode.prompt.call_args
    sent_text = kwargs["text"] if "text" in kwargs else args[1]
    assert sent_text.startswith("<repo_map")
    assert "hello.py" in sent_text
    assert "<user_message>" in sent_text
    assert "list the files" in sent_text


def test_chat_v2_skips_map_when_disabled(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import AsyncMock

    from plugin import deps
    from plugin.config import BaluCodePluginConfig
    from plugin.routes import build_router
    from plugin.services.audit import AuditLogger
    from plugin.services.ollama_client import OllamaClient
    from plugin.services.opencode_client import OpencodeClient
    from plugin.services.project_store import ProjectStore

    root = tmp_path / "userproj"
    root.mkdir()
    (root / "hello.py").write_text("def hello(): return 1\n")

    store = ProjectStore(tmp_path / "store.db")
    project = store.create_project("p", str(root), None)
    store.set_opencode_session_id(project.id, "ses_test")

    audit = AuditLogger(tmp_path / "audit.db")
    config = BaluCodePluginConfig(repo_map_enabled=False)
    deps.set_singletons(
        store=store,
        ollama=OllamaClient("http://127.0.0.1:11434"),
        plugin_config=config,
        audit_log=audit,
        data_dir=tmp_path,
    )

    fake_opencode = AsyncMock(spec=OpencodeClient)
    fake_opencode.prompt = AsyncMock(
        return_value={"info": {"id": "msg"}, "parts": [{"type": "text", "text": "ok"}]}
    )
    fake_opencode.create_session = AsyncMock(return_value="ses_test")
    deps.set_opencode(handle=None, client=fake_opencode)  # type: ignore[arg-type]

    app = FastAPI()
    app.include_router(build_router())
    from app.api import deps as app_deps

    app.dependency_overrides[app_deps.get_current_user] = lambda: object()

    client = TestClient(app)
    resp = client.post(
        f"/chat/v2/{project.id}",
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200

    args, kwargs = fake_opencode.prompt.call_args
    sent_text = kwargs["text"] if "text" in kwargs else args[1]
    assert sent_text == "hi"  # raw user content, no envelope
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest plugin/tests/test_routes_chat_v2.py -v -k "repo_map or disabled"`

Expected: both tests fail — `sent_text` is `"list the files"` / `"hi"` without envelope.

- [ ] **Step 3: Wire the map into chat_v2**

In `plugin/routes.py`, change the import block. Find:

```python
from .services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)
```

Replace with:

```python
from .services.project_store import (
    DuplicateProjectError,
    Project,
    ProjectNotFoundError,
    ProjectStore,
)
from .services.repo_map import ProjectRootNotAccessible, RepoMap
```

Then locate the `chat_v2` handler (around line 252). Replace the section that starts with `# Extract last user message text` through the `result = await client.prompt(...)` call with:

```python
        # Extract last user message text
        last_user = next(
            (m for m in reversed(body.messages) if m.role == "user"),
            None,
        )
        if last_user is None:
            raise HTTPException(status_code=400, detail="messages must include a user message")

        model_str = body.model or f"ollama/{get_plugin_config().chat_model}"
        provider, model_id = _split_model(model_str)

        # Assemble prompt text: prepend the repo-map envelope (if enabled +
        # the project root exists) so opencode/qwen-coder starts each turn
        # with file/symbol awareness instead of having to grep.
        prompt_text = last_user.content
        config = get_plugin_config()
        if config.repo_map_enabled:
            store = get_project_store()
            try:
                project = await asyncio.to_thread(store.get_project, project_id)
                repo_map = RepoMap(Path(project.root_path), store, project_id)
                files = await asyncio.to_thread(repo_map.walk_and_cache)
                rendered = RepoMap.render(
                    files,
                    budget_tokens=config.repo_map_budget,
                    project_name=project.name,
                )
                prompt_text = (
                    f"{rendered.text}\n\n"
                    f"<user_message>\n{last_user.content}\n</user_message>"
                )
            except (ProjectNotFoundError, ProjectRootNotAccessible):
                # Silently degrade — chat still works without the map.
                prompt_text = last_user.content

        result = await client.prompt(
            session_id,
            text=prompt_text,
            model_provider=provider,
            model_id=model_id,
        )
```

- [ ] **Step 4: Run the new tests**

Run: `pytest plugin/tests/test_routes_chat_v2.py -v -k "repo_map or disabled"`

Expected: 2 passed.

- [ ] **Step 5: Run the full chat_v2 test file to catch regressions**

Run: `pytest plugin/tests/test_routes_chat_v2.py -v`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add plugin/routes.py plugin/tests/test_routes_chat_v2.py
git commit -m "feat(repo-map): prepend envelope to chat_v2 user message"
```

---

## Task 15: Debug routes — GET /repo_map + POST /repo_map/rebuild

**Files:**
- Modify: `plugin/routes.py`
- Create: `plugin/tests/test_routes_repo_map.py`

- [ ] **Step 1: Write the route tests**

Create `plugin/tests/test_routes_repo_map.py`:

```python
"""Tests for the repo-map debug routes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugin import deps
from plugin.config import BaluCodePluginConfig
from plugin.routes import build_router
from plugin.services.audit import AuditLogger
from plugin.services.ollama_client import OllamaClient
from plugin.services.project_store import ProjectStore


@pytest.fixture
def app_factory(tmp_path):
    def _factory(root: str | None = None):
        store = ProjectStore(tmp_path / "store.db")
        if root is None:
            project_root = tmp_path / "proj"
            project_root.mkdir()
            (project_root / "a.py").write_text("def x(): pass\n")
            root_str = str(project_root)
        else:
            root_str = root
        project = store.create_project("p", root_str, None)

        audit = AuditLogger(tmp_path / "audit.db")
        deps.set_singletons(
            store=store,
            ollama=OllamaClient("http://127.0.0.1:11434"),
            plugin_config=BaluCodePluginConfig(),
            audit_log=audit,
            data_dir=tmp_path,
        )

        app = FastAPI()
        app.include_router(build_router())
        from app.api import deps as app_deps

        app.dependency_overrides[app_deps.get_current_user] = lambda: object()
        return TestClient(app), project, store

    return _factory


def test_get_repo_map_returns_envelope(app_factory):
    client, project, _ = app_factory()
    resp = client.get(f"/projects/{project.id}/repo_map")
    assert resp.status_code == 200
    body = resp.json()
    assert "<repo_map" in body["text"]
    assert body["file_count"] == 1


def test_get_repo_map_honors_budget_query(app_factory):
    client, project, _ = app_factory()
    resp = client.get(f"/projects/{project.id}/repo_map?budget=99999")
    assert resp.status_code == 200
    assert 'budget="99999"' in resp.json()["text"]


def test_get_repo_map_404_for_unknown_project(app_factory):
    client, _, _ = app_factory()
    resp = client.get("/projects/9999/repo_map")
    assert resp.status_code == 404


def test_get_repo_map_422_for_inaccessible_root(app_factory, tmp_path):
    client, _, _ = app_factory(root=str(tmp_path / "does_not_exist"))
    # The factory created the project at id=1 — use it
    resp = client.get("/projects/1/repo_map")
    assert resp.status_code == 422


def test_post_repo_map_rebuild_clears_cache(app_factory):
    client, project, store = app_factory()
    # Populate cache first
    client.get(f"/projects/{project.id}/repo_map")
    assert len(store.list_repo_map_entries(project.id)) == 1

    resp = client.post(f"/projects/{project.id}/repo_map/rebuild")
    assert resp.status_code == 200
    # After rebuild + the call returns the freshly-walked map, cache is repopulated
    assert resp.json()["file_count"] == 1


def test_get_repo_map_401_when_unauthenticated(tmp_path):
    """When dependency_overrides are not set, get_current_user enforces auth."""
    store = ProjectStore(tmp_path / "store.db")
    project_root = tmp_path / "proj"
    project_root.mkdir()
    project = store.create_project("p", str(project_root), None)
    audit = AuditLogger(tmp_path / "audit.db")
    deps.set_singletons(
        store=store,
        ollama=OllamaClient("http://127.0.0.1:11434"),
        plugin_config=BaluCodePluginConfig(),
        audit_log=audit,
        data_dir=tmp_path,
    )
    app = FastAPI()
    app.include_router(build_router())
    client = TestClient(app)
    resp = client.get(f"/projects/{project.id}/repo_map")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest plugin/tests/test_routes_repo_map.py -v`

Expected: failures — routes don't exist yet (`404 Not Found` on all).

- [ ] **Step 3: Add the routes**

In `plugin/routes.py`, in the schemas import block. Find:

```python
from .schemas import (
    ApprovalSummary,
    ChatV2Request,
    ConfigUpdateRequest,
    DayStat,
    GpuInfo,
    LoadedModel,
    LogEntry,
    LogsResponse,
    ModelsResponse,
    ModelStat,
    OllamaSystemInfo,
    ProjectCreate,
    ProjectsResponse,
    RuntimeCredentialsResponse,
    RuntimeStatusResponse,
    StatsResponse,
    SystemResponse,
    ToolStat,
)
```

Add `RepoMapResponse` to this list (alphabetical):

```python
from .schemas import (
    ApprovalSummary,
    ChatV2Request,
    ConfigUpdateRequest,
    DayStat,
    GpuInfo,
    LoadedModel,
    LogEntry,
    LogsResponse,
    ModelsResponse,
    ModelStat,
    OllamaSystemInfo,
    ProjectCreate,
    ProjectsResponse,
    RepoMapResponse,
    RuntimeCredentialsResponse,
    RuntimeStatusResponse,
    StatsResponse,
    SystemResponse,
    ToolStat,
)
```

Then add two new route handlers. Place them after the existing `delete_project` route (around line 225, after the closing of `delete_project`'s `try/except` block) and before `list_models_route`:

```python
    @router.get(
        "/projects/{project_id}/repo_map",
        response_model=RepoMapResponse,
        tags=["balu_code"],
    )
    async def get_repo_map_route(
        project_id: int,
        budget: int = Query(default=2048, ge=64, le=32768),
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> RepoMapResponse:
        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc
        repo_map = RepoMap(Path(project.root_path), store, project_id)
        try:
            files = await asyncio.to_thread(repo_map.walk_and_cache)
        except ProjectRootNotAccessible as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"project root not accessible: {exc}",
            ) from exc
        rendered = RepoMap.render(files, budget_tokens=budget, project_name=project.name)
        return RepoMapResponse(
            text=rendered.text,
            file_count=rendered.file_count,
            truncated_files=rendered.truncated_files,
            total_bytes=rendered.total_bytes,
        )

    @router.post(
        "/projects/{project_id}/repo_map/rebuild",
        response_model=RepoMapResponse,
        tags=["balu_code"],
    )
    async def rebuild_repo_map_route(
        project_id: int,
        budget: int = Query(default=2048, ge=64, le=32768),
        _user: UserPublic = Depends(get_current_user),
        store: ProjectStore = Depends(get_project_store),
    ) -> RepoMapResponse:
        try:
            project = await asyncio.to_thread(store.get_project, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"project {project_id} not found",
            ) from exc
        # Drop the entire cache for this project, then walk afresh.
        await asyncio.to_thread(store.delete_repo_map_entries, project_id, set())
        repo_map = RepoMap(Path(project.root_path), store, project_id)
        try:
            files = await asyncio.to_thread(repo_map.walk_and_cache)
        except ProjectRootNotAccessible as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"project root not accessible: {exc}",
            ) from exc
        rendered = RepoMap.render(files, budget_tokens=budget, project_name=project.name)
        return RepoMapResponse(
            text=rendered.text,
            file_count=rendered.file_count,
            truncated_files=rendered.truncated_files,
            total_bytes=rendered.total_bytes,
        )
```

- [ ] **Step 4: Run the route tests**

Run: `pytest plugin/tests/test_routes_repo_map.py -v`

Expected: 6 passed.

- [ ] **Step 5: Run the full suite**

Run: `pytest plugin/tests/ -v`

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add plugin/routes.py plugin/tests/test_routes_repo_map.py
git commit -m "feat(repo-map): debug routes GET /repo_map + POST /rebuild"
```

---

## Task 16: Delete dead prompts/ folder

**Files:**
- Delete: `plugin/prompts/system.md`
- Delete: `plugin/prompts/tool_use.md`
- Delete: `plugin/prompts/` (empty dir)

- [ ] **Step 1: Verify nothing reads these files**

Run: `grep -rn "prompts/system\|prompts/tool_use\|prompts/" plugin/ --include="*.py" 2>/dev/null`

Expected: no matches.

- [ ] **Step 2: Delete the files and folder**

```bash
git rm plugin/prompts/system.md plugin/prompts/tool_use.md
rmdir plugin/prompts
```

- [ ] **Step 3: Run the suite as a final regression check**

Run: `pytest plugin/tests/ -v`

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(repo-map): remove dead prompts/ — system.md was never loaded"
```

---

## Task 17: Lint pass

**Files:** all touched files

- [ ] **Step 1: Run ruff check**

Run: `ruff check plugin/`

Expected: no errors. If any: fix them inline before committing.

- [ ] **Step 2: Run ruff format check**

Run: `ruff format --check plugin/`

Expected: no diffs. If diffs: `ruff format plugin/` then re-run the check.

- [ ] **Step 3: Commit any formatting fixes**

```bash
git add -u plugin/
git diff --cached --quiet || git commit -m "style: ruff format pass for repo-map module"
```

---

## Task 18: Manual smoke against the symlinked prod install

**Files:** none

The plugin is already symlinked at `/opt/baluhost/backend/app/plugins/installed/balu_code → /home/sven/projects/plugins/Balu_Code/plugin`. Code changes go live after a backend restart; tree-sitter wheels need a one-time install into the BaluHost backend venv.

- [ ] **Step 1: Install tree-sitter into the BaluHost backend venv**

Run: `/home/sven/projects/BaluHost/backend/.venv/bin/pip install 'tree-sitter>=0.22' 'tree-sitter-python>=0.21' 'tree-sitter-javascript>=0.23' 'tree-sitter-typescript>=0.23'`

Expected: four packages installed.

- [ ] **Step 2: Restart the BaluHost backend**

Run (interactive — ask Sven to do it if a privileged command is needed): `systemctl --user restart baluhost-backend` *or* whatever Sven normally uses to restart the backend.

Expected: backend comes back up healthy. Sven verifies via the Balu Code UI loading without errors.

- [ ] **Step 3: Hit the GET /repo_map endpoint**

Pick a registered project (or create one pointing at `/home/sven/projects/plugins/Balu_Code`). Then:

Run (substitute `<project_id>` and the BaluHost cookie/auth as appropriate; Sven knows the local pattern):

```bash
curl -sS "https://baluhost.local/api/plugins/balu_code/projects/<project_id>/repo_map?budget=2048" \
  | jq '{file_count, truncated_count: (.truncated_files | length), preview: (.text[:400])}'
```

Expected: `file_count` > 0, preview contains `<repo_map …>` and at least one `=== path/to/file.py (N lines)` block.

- [ ] **Step 4: Send a chat through /chat/v2**

Use the UI (preferred) or:

```bash
curl -sS -X POST "https://baluhost.local/api/plugins/balu_code/chat/v2/<project_id>" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Which file owns the OpencodeClient.prompt method?"}]}'
```

Expected: response cites a specific file path (e.g. `plugin/services/opencode_client.py`) without the model having to call Grep/Glob — proves the prepended map is being used.

- [ ] **Step 5: Sanity-check the cache table**

Run: `sqlite3 ~/.local/share/balu-code/store.db 'SELECT project_id, file_path, length(symbols_json) FROM repo_map_cache LIMIT 10;'`

Expected: rows with non-zero `symbols_json` length.

- [ ] **Step 6: Note any rough edges**

If anything misbehaves (wrong files indexed, truncation cuts off important symbols, qwen-coder ignores the map), capture the observation in a follow-up issue / memory note. Do **not** silently expand scope.

---

## Definition of Done

- All new tests pass (~50 added); full suite green on CI.
- `ruff check plugin/` and `ruff format --check plugin/` clean.
- Manual smoke (Task 18) confirms the envelope reaches a real chat turn and shows up in the model's response.
- `plugin/prompts/` folder removed.
- BaluHost backend running the new code via the existing symlink — no `.bhplugin` rebuild required for dev iteration.
