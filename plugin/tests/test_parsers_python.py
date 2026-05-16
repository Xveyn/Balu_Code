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
