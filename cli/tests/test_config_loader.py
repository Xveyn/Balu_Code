"""Tests for config/loader.py and config/paths.py."""

from __future__ import annotations

from balu_code_cli.config.loader import (
    AppConfig,
    Credentials,
    ServerCredentials,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
)


def test_config_dir_uses_xdg_config_home(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib

    import balu_code_cli.config.paths as paths_mod

    importlib.reload(paths_mod)
    assert paths_mod.config_dir() == tmp_path / "balu-code"


def test_config_dir_defaults_to_home_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    import balu_code_cli.config.paths as paths_mod

    importlib.reload(paths_mod)
    assert paths_mod.config_dir() == tmp_path / ".config" / "balu-code"


def test_load_config_returns_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.server_url == ""
    assert cfg.default_project_id is None


def test_save_and_load_config_round_trips(tmp_path):
    path = tmp_path / "config.yaml"
    cfg = AppConfig(server_url="https://balu.example.com", default_project_id=42)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.server_url == "https://balu.example.com"
    assert loaded.default_project_id == 42


def test_load_credentials_returns_empty_when_file_missing(tmp_path):
    creds = load_credentials(tmp_path / "credentials.yaml")
    assert creds.servers == {}


def test_save_credentials_sets_mode_0600(tmp_path):
    path = tmp_path / "credentials.yaml"
    creds = Credentials(
        servers={"https://balu.example.com": ServerCredentials(api_key="bc_abc123")}
    )
    save_credentials(creds, path)
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_save_and_load_credentials_round_trips(tmp_path):
    path = tmp_path / "credentials.yaml"
    creds = Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_xyz")})
    save_credentials(creds, path)
    loaded = load_credentials(path)
    assert loaded.servers["https://balu.example.com"].api_key == "bc_xyz"
