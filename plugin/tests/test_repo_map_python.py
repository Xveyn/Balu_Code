"""Tests for parse_python_file."""

from __future__ import annotations

from plugin.services.repo_map_python import parse_python_file
from plugin.services.repo_map_types import ClassSymbol, FunctionSymbol


def test_empty_file_returns_three_empty_lists():
    imports, classes, functions = parse_python_file(b"")
    assert imports == []
    assert classes == []
    assert functions == []


def test_plain_imports():
    src = b"import os\nimport sys, json\n"
    imports, _, _ = parse_python_file(src)
    assert "os" in imports
    assert "sys" in imports
    assert "json" in imports


def test_dotted_import():
    src = b"import xml.etree.ElementTree\n"
    imports, _, _ = parse_python_file(src)
    assert "xml.etree.ElementTree" in imports


def test_aliased_import():
    src = b"import numpy as np\n"
    imports, _, _ = parse_python_file(src)
    assert "numpy" in imports


def test_from_import():
    src = b"from app.models import User, Group\n"
    imports, _, _ = parse_python_file(src)
    assert "app.models" in imports


def test_relative_from_import():
    src = b"from .helpers import x\nfrom ..parent import y\n"
    imports, _, _ = parse_python_file(src)
    assert ".helpers" in imports
    assert "..parent" in imports


def test_multiline_from_import():
    src = b"from app.models import (\n    User,\n    Group,\n)\n"
    imports, _, _ = parse_python_file(src)
    assert "app.models" in imports


def test_top_level_function():
    src = b"def foo(x: int) -> str:\n    return str(x)\n"
    _, _, functions = parse_python_file(src)
    assert len(functions) == 1
    assert functions[0].name == "foo"
    assert functions[0].signature == "def foo(x: int) -> str"


def test_async_function():
    src = b"async def fetch(url: str) -> bytes:\n    return b''\n"
    _, _, functions = parse_python_file(src)
    assert len(functions) == 1
    assert functions[0].name == "fetch"
    assert functions[0].signature.startswith("async def fetch(")
    assert functions[0].signature.endswith(" -> bytes")


def test_decorated_function_is_recorded():
    src = b"import functools\n@functools.cache\ndef cached() -> int:\n    return 1\n"
    _, _, functions = parse_python_file(src)
    assert any(f.name == "cached" for f in functions)


def test_function_without_return_type_omits_arrow():
    src = b"def f(x):\n    pass\n"
    _, _, functions = parse_python_file(src)
    assert functions[0].signature == "def f(x)"


def test_class_with_methods():
    src = (
        b"class Service(Base, IFace):\n"
        b"    def __init__(self, x: int) -> None:\n"
        b"        self.x = x\n"
        b"    async def call(self) -> str:\n"
        b"        return ''\n"
    )
    _, classes, _ = parse_python_file(src)
    assert len(classes) == 1
    cls = classes[0]
    assert cls.name == "Service"
    assert cls.bases == ["Base", "IFace"]
    assert any(m.startswith("def __init__(self, x: int)") for m in cls.methods)
    assert any(m.startswith("async def call(self)") for m in cls.methods)


def test_decorated_class():
    src = b"@register\nclass Registered:\n    def x(self): ...\n"
    _, classes, _ = parse_python_file(src)
    assert len(classes) == 1
    assert classes[0].name == "Registered"


def test_class_without_bases():
    src = b"class Plain:\n    pass\n"
    _, classes, _ = parse_python_file(src)
    assert classes[0].bases == []


def test_syntax_error_does_not_raise():
    """Tree-sitter is error-tolerant; we accept partial results so long as
    the function itself never raises. (For ``b"def broken(\\n"`` the parser
    actually returns three empty lists today, but we don't pin that — the
    contract is the no-exception guarantee.)"""
    src = b"def broken(\n"  # unterminated
    imports, classes, functions = parse_python_file(src)
    assert isinstance(imports, list)
    assert isinstance(classes, list)
    assert isinstance(functions, list)


def test_returns_correct_dataclass_types():
    src = b"def f(): pass\nclass C: pass\n"
    _, classes, functions = parse_python_file(src)
    assert isinstance(functions[0], FunctionSymbol)
    assert isinstance(classes[0], ClassSymbol)
