"""Pure-function chunker for RAG embedding.

Splits a Python source file into chunks at tree-sitter top-level symbol
boundaries (``class_definition`` / ``function_definition`` / wrapping
``decorated_definition``), with a sliding-window fallback for long
symbols and unparseable files. Decorators are included in the symbol's
line range so the chunk captures the full "definition unit".

This module is stateless and synchronous. It is called from the
indexer worker (``plugin.services.indexer``), which handles embedding
and persistence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .parsers.python import get_parser


@dataclass(frozen=True)
class Chunk:
    file_path: str
    start_line: int  # 1-indexed, inclusive
    end_line: int  # 1-indexed, inclusive
    text: str


def chunk_python_file(
    file_path: str,
    source: bytes,
    *,
    window_lines: int = 40,
    overlap_lines: int = 10,
    symbol_max_lines: int = 80,
) -> list[Chunk]:
    """Split a Python file into chunks for embedding.

    - Top-level ``class`` / ``def`` (and ``decorated_definition`` wrapping
      one) become one chunk each, unless their line span exceeds
      ``symbol_max_lines``, in which case they are split into sliding
      windows of ``window_lines`` with ``overlap_lines`` overlap.
    - Lines between symbols (module docstring + imports before the first
      symbol, inter-symbol gaps, trailing module-level code) become
      single non-symbol chunks. For v1 these are emitted whole, not
      split — they are usually short (imports / a comment block).
    - If the parser returns zero top-level symbols (empty file, pure
      module-level code, syntax error), the whole file is split into
      sliding windows.
    - Empty ``source`` returns an empty list.
    """
    if not source:
        return []

    text = source.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    n_lines = len(lines)
    if n_lines == 0:
        return []

    ranges = _extract_top_level_ranges(source)

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


def _extract_top_level_ranges(source: bytes) -> list[tuple[int, int]]:
    """Return (start_line, end_line) pairs for top-level symbols, 1-indexed inclusive, sorted ascending.

    Recognised node types: ``class_definition``, ``function_definition``,
    and ``decorated_definition`` wrapping either. For a decorated
    definition, the range covers the decorator line(s) too.
    """
    parser = get_parser()
    try:
        tree = parser.parse(source)
    except Exception:
        return []

    ranges: list[tuple[int, int]] = []
    for node in tree.root_node.children:
        nt = node.type
        if nt in ("class_definition", "function_definition"):
            ranges.append((node.start_point[0] + 1, node.end_point[0] + 1))
        elif nt == "decorated_definition":
            inner = node.child_by_field_name("definition")
            if inner is not None and inner.type in ("class_definition", "function_definition"):
                ranges.append((node.start_point[0] + 1, node.end_point[0] + 1))
    ranges.sort()
    return ranges


def _build_chunk(file_path: str, lines: list[str], start: int, end: int) -> Chunk:
    return Chunk(
        file_path=file_path,
        start_line=start,
        end_line=end,
        text="".join(lines[start - 1 : end]),
    )


def _sliding_windows(
    file_path: str,
    lines: list[str],
    start: int,
    end: int,
    window_lines: int,
    overlap_lines: int,
) -> Iterable[Chunk]:
    stride = max(1, window_lines - overlap_lines)
    pos = start
    while pos <= end:
        win_end = min(pos + window_lines - 1, end)
        yield _build_chunk(file_path, lines, pos, win_end)
        if win_end == end:
            break
        pos += stride


__all__ = ["Chunk", "chunk_python_file"]
