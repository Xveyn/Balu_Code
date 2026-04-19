"""Tests for RepoMap.render."""

from __future__ import annotations

from plugin.services.repo_map import RepoMap
from plugin.services.repo_map_types import (
    ClassSymbol,
    FileSymbols,
    FunctionSymbol,
    RenderedMap,
)


def _file(path: str, lines: int = 1, imports=None, classes=None, functions=None):
    return FileSymbols(
        path=path,
        lines=lines,
        imports=list(imports or []),
        classes=list(classes or []),
        functions=list(functions or []),
    )


def test_empty_file_list_returns_empty_render():
    out = RepoMap.render([], budget_tokens=1024)
    assert isinstance(out, RenderedMap)
    assert out.text == ""
    assert out.file_count == 0
    assert out.truncated_files == []
    assert out.total_bytes == 0


def test_single_file_with_no_symbols_renders_only_header():
    f = _file("a.py", lines=10)
    out = RepoMap.render([f], budget_tokens=1024)
    assert out.text == "=== a.py (10 lines)\n"
    assert out.file_count == 1
    assert out.truncated_files == []
    assert out.total_bytes == len(out.text)


def test_imports_section_rendered_when_non_empty():
    f = _file("a.py", lines=5, imports=["os", "sys", "app.models"])
    out = RepoMap.render([f], budget_tokens=1024)
    assert "imports: os, sys, app.models\n" in out.text


def test_imports_section_omitted_when_empty():
    f = _file("a.py", lines=5, imports=[])
    out = RepoMap.render([f], budget_tokens=1024)
    assert "imports:" not in out.text


def test_classes_and_functions_rendered():
    cls = ClassSymbol(
        name="Service",
        bases=["Base"],
        methods=["def __init__(self) -> None", "async def call(self) -> str"],
    )
    fn = FunctionSymbol(name="helper", signature="def helper(x: int) -> None")
    f = _file("a.py", lines=20, classes=[cls], functions=[fn])
    out = RepoMap.render([f], budget_tokens=1024)
    assert "classes:" in out.text
    assert "  class Service(Base):" in out.text
    assert "    def __init__(self) -> None" in out.text
    assert "    async def call(self) -> str" in out.text
    assert "functions:" in out.text
    assert "  def helper(x: int) -> None" in out.text


def test_class_without_bases_renders_no_parens():
    cls = ClassSymbol(name="Plain", bases=[], methods=["def m(self): ..."])
    f = _file("a.py", lines=5, classes=[cls])
    out = RepoMap.render([f], budget_tokens=1024)
    assert "  class Plain:" in out.text
    assert "Plain():" not in out.text


def test_files_sorted_alphabetically_by_path():
    files = [
        _file("z.py"),
        _file("a.py"),
        _file("m/n.py"),
    ]
    out = RepoMap.render(files, budget_tokens=1024)
    pos_a = out.text.index("=== a.py")
    pos_m = out.text.index("=== m/n.py")
    pos_z = out.text.index("=== z.py")
    assert pos_a < pos_m < pos_z


def test_truncation_when_budget_exhausted():
    # Five files; small budget — only a couple should fit.
    files = [_file(f"file_{i:02d}.py", lines=10) for i in range(5)]
    out = RepoMap.render(files, budget_tokens=8)  # ~32 chars budget
    assert out.file_count < 5
    assert len(out.truncated_files) == 5 - out.file_count
    # Truncated files are the alphabetically-later ones.
    expected_kept = [f.path for f in files[: out.file_count]]
    expected_truncated = [f.path for f in files[out.file_count :]]
    rendered_paths = [f"file_{i:02d}.py" for i in range(5) if f"file_{i:02d}.py" in out.text]
    assert rendered_paths == expected_kept
    assert sorted(out.truncated_files) == sorted(expected_truncated)


def test_total_bytes_matches_text_length():
    f = _file("a.py", lines=5, imports=["os"])
    out = RepoMap.render([f], budget_tokens=1024)
    assert out.total_bytes == len(out.text)


def test_first_file_always_included_even_when_budget_too_small():
    """A tiny budget must still yield at least one file block."""
    f = _file("a.py", lines=5, imports=["os"])
    out = RepoMap.render([f], budget_tokens=1)  # 4-char budget, header alone is >4 chars
    assert out.file_count == 1
    assert out.truncated_files == []
    assert "=== a.py" in out.text
