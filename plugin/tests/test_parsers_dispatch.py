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
