"""Tests for chunk_python_file."""

from __future__ import annotations

from plugin.services.rag_chunker import Chunk, chunk_python_file


def test_empty_source_returns_empty_list():
    assert chunk_python_file("a.py", b"") == []


def test_single_short_function_one_chunk():
    src = b"def foo(x):\n    return x\n"
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.file_path == "a.py"
    assert c.start_line == 1
    assert c.end_line == 2
    assert c.text == "def foo(x):\n    return x\n"


def test_prologue_emitted_before_first_symbol():
    src = b'"""Module docstring."""\nimport os\n\ndef foo():\n    return 1\n'
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 2
    prologue, func = chunks
    assert prologue.start_line == 1
    assert prologue.end_line == 3
    assert "Module docstring" in prologue.text
    assert "import os" in prologue.text
    assert func.start_line == 4
    assert func.end_line == 5
    assert func.text.startswith("def foo")


def test_two_adjacent_symbols_no_gap_chunk():
    src = b"def foo():\n    return 1\ndef bar():\n    return 2\n"
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 2
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 2
    assert chunks[1].start_line == 3
    assert chunks[1].end_line == 4


def test_gap_between_symbols_emitted_as_separate_chunk():
    src = (
        b"def foo():\n    return 1\n"
        b"\n"
        b"# A comment spanning\n"
        b"# multiple lines.\n"
        b"\n"
        b"def bar():\n    return 2\n"
    )
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 3
    foo, gap, bar = chunks
    assert foo.text.startswith("def foo")
    assert gap.text.strip().startswith("# A comment")
    assert bar.text.startswith("def bar")


def test_tail_after_last_symbol_emitted():
    src = b"def foo():\n    return 1\n\nTRAILING = 42\n"
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 2
    assert chunks[0].text.startswith("def foo")
    assert "TRAILING = 42" in chunks[1].text


def test_long_symbol_split_into_sliding_windows():
    # One function that is 100 lines long. Default symbol_max_lines=80.
    body_lines = [f"    x_{i} = {i}\n" for i in range(98)]
    src = b"def big():\n" + b"".join(line.encode() for line in body_lines) + b"    return None\n"
    chunks = chunk_python_file("a.py", src, window_lines=40, overlap_lines=10)
    assert len(chunks) >= 2
    # All chunks stay inside the function's line range [1, 100].
    for c in chunks:
        assert c.start_line >= 1
        assert c.end_line <= 100
    # Windows overlap: second chunk's start_line < first chunk's end_line.
    assert chunks[1].start_line < chunks[0].end_line


def test_no_symbols_fallback_to_sliding_windows():
    # 50 lines of module-level code, no defs/classes.
    src = b"\n".join(f"CONST_{i} = {i}".encode() for i in range(50)) + b"\n"
    chunks = chunk_python_file("a.py", src, window_lines=40, overlap_lines=10)
    assert len(chunks) == 2  # windows at [1,40] and [31,50]
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 40
    assert chunks[1].start_line == 31
    assert chunks[1].end_line == 50


def test_decorated_function_included_in_chunk_range():
    src = b"@staticmethod\ndef foo():\n    return 1\n"
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.start_line == 1  # decorator line included
    assert c.end_line == 3
    assert "@staticmethod" in c.text


def test_class_with_methods_is_one_chunk():
    src = (
        b"class Service:\n    def a(self):\n        return 1\n    def b(self):\n        return 2\n"
    )
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 1
    assert chunks[0].text.startswith("class Service:")
    assert "def a" in chunks[0].text
    assert "def b" in chunks[0].text


def test_syntax_error_fallback_to_sliding_windows():
    # Unparseable but non-empty; fallback must still produce at least one chunk.
    src = b"def broken(\n" + b"x = 1\n" * 50
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) >= 1
    # All chunks cover the file exactly (no crashes).
    for c in chunks:
        assert 1 <= c.start_line <= c.end_line


def test_chunk_text_decodes_non_utf8_safely():
    # Invalid UTF-8 bytes must not raise; errors='replace' turns them into U+FFFD.
    src = b"def foo():\n    return '\xff\xfe'\n"
    chunks = chunk_python_file("a.py", src)
    assert len(chunks) == 1
    assert "foo" in chunks[0].text


def test_returns_Chunk_dataclass_instances():
    src = b"def f(): pass\n"
    chunks = chunk_python_file("a.py", src)
    assert isinstance(chunks[0], Chunk)
