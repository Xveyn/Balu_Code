"""Tests for plugin/services/repo_map.py RepoMap.render()."""

from __future__ import annotations

from plugin.services.repo_map import (
    ClassSymbol,
    FileSymbols,
    FunctionSymbol,
    RepoMap,
)


def _file(path: str, *, lines: int = 10, imports=None, classes=None, functions=None):
    return FileSymbols(
        path=path,
        lines=lines,
        imports=imports or [],
        classes=classes or [],
        functions=functions or [],
    )


def test_empty_files_returns_envelope_only():
    rendered = RepoMap.render([], budget_tokens=2048, project_name="x")
    assert rendered.file_count == 0
    assert rendered.truncated_files == []
    assert "<repo_map" in rendered.text
    assert 'project="x"' in rendered.text
    assert 'files="0"' in rendered.text
    assert "</repo_map>" in rendered.text


def test_single_file_renders_header_and_sections():
    files = [
        _file(
            "a.py",
            lines=42,
            imports=["os"],
            classes=[ClassSymbol(name="C", bases=["B"], methods=["def m(self) -> None"])],
            functions=[FunctionSymbol(name="f", signature="def f() -> int")],
        )
    ]
    rendered = RepoMap.render(files, budget_tokens=2048)
    assert rendered.file_count == 1
    assert "=== a.py (42 lines)" in rendered.text
    assert "imports: os" in rendered.text
    assert "classes:" in rendered.text
    assert "class C(B):" in rendered.text
    assert "def m(self) -> None" in rendered.text
    assert "functions:" in rendered.text
    assert "def f() -> int" in rendered.text


def test_files_sorted_alphabetically():
    files = [
        _file("z.py", functions=[FunctionSymbol(name="z", signature="def z()")]),
        _file("a.py", functions=[FunctionSymbol(name="a", signature="def a()")]),
        _file("m.py", functions=[FunctionSymbol(name="m", signature="def m()")]),
    ]
    rendered = RepoMap.render(files, budget_tokens=2048)
    a_idx = rendered.text.index("=== a.py")
    m_idx = rendered.text.index("=== m.py")
    z_idx = rendered.text.index("=== z.py")
    assert a_idx < m_idx < z_idx


def test_empty_sections_omitted():
    files = [_file("a.py", functions=[FunctionSymbol(name="x", signature="def x()")])]
    rendered = RepoMap.render(files, budget_tokens=2048)
    assert "imports:" not in rendered.text
    assert "classes:" not in rendered.text
    assert "functions:" in rendered.text


def test_class_without_bases_renders_plain():
    files = [_file("a.py", classes=[ClassSymbol(name="C", bases=[], methods=["def m()"])])]
    rendered = RepoMap.render(files, budget_tokens=2048)
    assert "class C:" in rendered.text


def test_budget_truncates_excess_files():
    # Build many small files so the budget is exceeded
    files = [
        _file(f"f{i:03d}.py", functions=[FunctionSymbol(name="g", signature="def g()")])
        for i in range(200)
    ]
    rendered = RepoMap.render(files, budget_tokens=64)  # very tight budget
    assert rendered.file_count < 200
    assert len(rendered.truncated_files) > 0
    # Truncated must be the tail (alphabetical)
    truncated_set = set(rendered.truncated_files)
    rendered_paths = [f"f{i:03d}.py" for i in range(rendered.file_count)]
    for p in rendered_paths:
        assert p not in truncated_set


def test_total_bytes_matches_text_length():
    files = [_file("a.py", functions=[FunctionSymbol(name="x", signature="def x()")])]
    rendered = RepoMap.render(files, budget_tokens=2048)
    assert rendered.total_bytes == len(rendered.text.encode("utf-8"))


def test_envelope_contains_metadata():
    files = [_file("a.py", functions=[FunctionSymbol(name="x", signature="def x()")])]
    rendered = RepoMap.render(files, budget_tokens=999, project_name="balu-code")
    assert 'project="balu-code"' in rendered.text
    assert 'budget="999"' in rendered.text
    assert 'files="1"' in rendered.text
    assert "generated=" in rendered.text
