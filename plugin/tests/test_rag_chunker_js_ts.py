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
