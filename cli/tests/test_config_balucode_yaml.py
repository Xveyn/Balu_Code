"""Tests for config/balucode_yaml.py."""

from __future__ import annotations

import pytest
from balu_code_cli.config.balucode_yaml import (
    BaluCodeYaml,
    find_balucode_yaml,
    load_balucode_yaml,
)


def test_load_minimal_yaml(tmp_path):
    f = tmp_path / ".balucode.yaml"
    f.write_text("project_id: 42\nserver_url: https://balu.example.com\n")
    cfg = load_balucode_yaml(f)
    assert cfg.project_id == 42
    assert cfg.server_url == "https://balu.example.com"
    assert cfg.model is None
    assert cfg.tools.allow_write is False
    assert cfg.tools.allow_bash is False
    assert cfg.tools.allow_web_fetch is True


def test_load_full_yaml(tmp_path):
    f = tmp_path / ".balucode.yaml"
    f.write_text(
        "project_id: 7\nserver_url: https://x.com\nmodel: llama3.1:8b\n"
        "tools:\n  allow_write: true\n  allow_bash: true\n  allow_web_fetch: false\n"
    )
    cfg = load_balucode_yaml(f)
    assert cfg.model == "llama3.1:8b"
    assert cfg.tools.allow_write is True
    assert cfg.tools.allow_bash is True
    assert cfg.tools.allow_web_fetch is False


def test_is_tool_allowed_write_file_when_allow_write_false():
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com")
    assert cfg.is_tool_allowed("write_file") is False
    assert cfg.is_tool_allowed("apply_patch") is False


def test_is_tool_allowed_write_file_when_allow_write_true():
    from balu_code_cli.config.balucode_yaml import ToolsConfig

    cfg = BaluCodeYaml(
        project_id=1, server_url="https://x.com", tools=ToolsConfig(allow_write=True)
    )
    assert cfg.is_tool_allowed("write_file") is True
    assert cfg.is_tool_allowed("apply_patch") is True


def test_is_tool_allowed_run_bash_default_false():
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com")
    assert cfg.is_tool_allowed("run_bash") is False


def test_is_tool_allowed_web_fetch_default_true():
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com")
    assert cfg.is_tool_allowed("web_fetch") is True


def test_is_tool_allowed_read_file_always_true():
    cfg = BaluCodeYaml(project_id=1, server_url="https://x.com")
    assert cfg.is_tool_allowed("read_file") is True
    assert cfg.is_tool_allowed("glob") is True


def test_find_balucode_yaml_finds_in_cwd(tmp_path):
    f = tmp_path / ".balucode.yaml"
    f.write_text("project_id: 1\nserver_url: https://x.com\n")
    found = find_balucode_yaml(tmp_path)
    assert found == f


def test_find_balucode_yaml_walks_up(tmp_path):
    f = tmp_path / ".balucode.yaml"
    f.write_text("project_id: 1\nserver_url: https://x.com\n")
    subdir = tmp_path / "a" / "b" / "c"
    subdir.mkdir(parents=True)
    found = find_balucode_yaml(subdir)
    assert found == f


def test_find_balucode_yaml_returns_none_when_not_found(tmp_path):
    assert find_balucode_yaml(tmp_path) is None


def test_load_balucode_yaml_raises_when_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="balu-code init"):
        load_balucode_yaml()  # no file in cwd during tests (tmp_path not used here)
