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
