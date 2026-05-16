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
