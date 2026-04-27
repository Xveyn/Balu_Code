# JS/TS Indexing & Repo-Map Extension

**Date:** 2026-04-27
**Status:** Approved

## Goal

Extend `balu-code index` and the repo-map to support JavaScript, TypeScript, JSX, and TSX files in addition to Python. Both the RAG vector-search index and the Aider-style repo-map context block must cover all four new extensions.

## Scope

| Component | Change |
|---|---|
| `plugin/services/parsers/python.py` | Rename from `repo_map_python.py`; no logic change |
| `plugin/services/parsers/js_ts.py` | New: tree-sitter parser + symbol extractor for JS/JSX/TS/TSX |
| `plugin/services/parsers/__init__.py` | Re-exports public API of both parser modules |
| `plugin/services/rag_chunker.py` | Add `chunk_js_ts_file()`; update import |
| `plugin/services/indexer.py` | `_iter_python_files()` → `_iter_source_files()` with extension dispatch |
| `plugin/services/repo_map.py` | `walk_and_cache()` extended with extension dispatch |
| `pyproject.toml` (plugin dev deps) | Add `tree-sitter-javascript>=0.23`, `tree-sitter-typescript>=0.23` |

Out of scope: Rust, Go, or any other language; a generic language-registry abstraction.

## Module Structure

```
plugin/services/
  parsers/
    __init__.py       ← re-exports get_parser, parse_python_file, parse_js_ts_file
    python.py         ← was repo_map_python.py (identical logic, moved)
    js_ts.py          ← NEW
  repo_map.py         ← dispatch via parsers package
  rag_chunker.py      ← dispatch via parsers package
  indexer.py
```

The pattern is explicit: one module per language family. Adding Rust later means adding `parsers/rust.py` and touching `walk_and_cache()` + `_iter_source_files()` only.

## `parsers/js_ts.py` — Symbol Extraction

Two lazy Parser singletons, one per tree-sitter grammar:

- `get_js_parser()` — `tree-sitter-javascript` (handles `.js`, `.jsx`)
- `get_ts_parser()` — `tree-sitter-typescript` language `typescript` (handles `.ts`, `.tsx`)

Public function:

```python
def parse_js_ts_file(
    source: bytes, extension: str
) -> tuple[list[str], list[ClassSymbol], list[FunctionSymbol]]:
```

`extension` (e.g. `".ts"`, `".jsx"`) selects the parser. Returns the same three-tuple that `parse_python_file` returns so callers are uniform.

### Top-Level Node Mapping

| tree-sitter node | Output |
|---|---|
| `function_declaration` | `FunctionSymbol` |
| `generator_function_declaration` | `FunctionSymbol` |
| `class_declaration` | `ClassSymbol` (methods from body) |
| `interface_declaration` *(TS)* | `ClassSymbol` (bases=[], methods=method signatures) |
| `type_alias_declaration` *(TS)* | `FunctionSymbol` with signature `type Name = ...` |
| `export_statement` wrapping any of the above | unwrap → same handling |
| `lexical_declaration` containing a `variable_declarator` whose value is `arrow_function` or `function` | `FunctionSymbol` |
| `import_statement` | collect module name → `imports` |

Nodes not in this list are skipped (expressions, `debugger`, etc.).

### Class Method Extraction

For `class_declaration` and `interface_declaration`, iterate the body for:
- `method_definition` — extract `async`, `static`, `get`/`set` modifier + name + parameters
- `public_field_definition` with arrow value — treated as method

## `rag_chunker.py` — `chunk_js_ts_file()`

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
```

Identical algorithm to `chunk_python_file`:

1. Extract top-level symbol line ranges via `parsers/js_ts.py`'s internal range extractor.
2. Lines between symbols → non-symbol chunk.
3. Symbol ≤ `symbol_max_lines` → single chunk; longer → sliding windows.
4. No symbols detected (pure expression file, parse error) → whole-file sliding windows.

The range extractor recognises the same node types as the symbol extractor above, plus decorators (`export_statement` wraps count as the outer boundary).

## `indexer.py` — `_iter_source_files()`

Replace `_iter_python_files()` with:

```python
_SOURCE_EXTENSIONS = frozenset({".py", ".js", ".ts", ".jsx", ".tsx"})

def _iter_source_files(project_root: Path):
    """Yield (fs_path, rel_posix) for every supported source file under project_root."""
```

In the indexing loop, dispatch by extension:

```python
ext = Path(rel_posix).suffix
if ext == ".py":
    chunks = chunk_python_file(rel_posix, content_bytes)
else:
    chunks = chunk_js_ts_file(rel_posix, content_bytes, ext)
```

## `repo_map.py` — `walk_and_cache()`

Same extension set `_SOURCE_EXTENSIONS`. Dispatch:

```python
if ext == ".py":
    imports, classes, functions = parse_python_file(content_bytes)
else:
    imports, classes, functions = parse_js_ts_file(content_bytes, ext)
```

The `_format_file_block` render function is unchanged — `ClassSymbol`, `FunctionSymbol`, `FileSymbols` are already language-agnostic.

## Dependencies

Add to `pyproject.toml` (plugin dev deps):

```toml
"tree-sitter-javascript>=0.23",
"tree-sitter-typescript>=0.23",
```

Both packages follow the same API as `tree-sitter-python`: `tsjava.language()` / `tsts.language_typescript()`.

## Error Handling

- Tree-sitter is error-tolerant by design — partial parses still yield recognised nodes.
- Both `parse_js_ts_file` and `chunk_js_ts_file` catch any `Exception` from the parser and fall back to `([], [], [])` / whole-file sliding windows respectively. Same contract as the Python equivalents.
- Unknown extension passed to `parse_js_ts_file` / `chunk_js_ts_file` raises `ValueError` immediately (fast fail, not silent).

## Testing

| File | Coverage |
|---|---|
| `plugin/tests/test_repo_map_js_ts.py` | parse function, class, interface, type alias, export wrapper, arrow-function const, import extraction; unknown extension raises ValueError |
| `plugin/tests/test_rag_chunker_js_ts.py` | empty source, single function, class, interface, export wrapper, long symbol → sliding window, no-symbol file → sliding window |
| `plugin/tests/test_indexer.py` | new cases: `.js` file indexed, `.ts` file indexed, `.tsx` file indexed, mixed `.py`+`.ts` directory |
| `plugin/tests/test_repo_map.py` | new cases: JS/TS files appear in walk_and_cache output alongside Python files |

Existing tests must continue to pass without modification.

## Migration / Rename

`repo_map_python.py` is deleted and replaced by `parsers/python.py`. The only callers are `repo_map.py` and `rag_chunker.py` — both imports are updated. No public API change; `repo_map_types.py` stays where it is.
