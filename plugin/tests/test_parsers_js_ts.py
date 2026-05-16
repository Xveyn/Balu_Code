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
