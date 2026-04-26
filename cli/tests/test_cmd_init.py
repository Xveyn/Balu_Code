"""Tests for commands/init.py."""
from __future__ import annotations

import httpx
import respx
import yaml
from balu_code_cli.__main__ import app
from typer.testing import CliRunner

runner = CliRunner()
BASE = "https://balu.example.com/api/plugins/balu_code"


def _setup_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib

    import balu_code_cli.config.paths as p
    importlib.reload(p)
    from balu_code_cli.config.loader import (
        AppConfig,
        Credentials,
        ServerCredentials,
        save_config,
        save_credentials,
    )
    save_config(AppConfig(server_url="https://balu.example.com"), p.config_yaml())
    save_credentials(
        Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_key")}),
        p.credentials_yaml(),
    )


@respx.mock
def test_init_creates_balucode_yaml(tmp_path, monkeypatch):
    _setup_auth(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)

    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b", "size": 1, "digest": "a"}]})
    )
    respx.post(f"{BASE}/projects").mock(
        return_value=httpx.Response(201, json={"id": 7, "name": "myproj", "root_path": str(tmp_path)})
    )

    result = runner.invoke(
        app, ["init"],
        input=f"myproj\n{tmp_path}\nllama3.1:8b\n",
    )
    assert result.exit_code == 0, result.output
    balucode = tmp_path / ".balucode.yaml"
    assert balucode.exists()
    data = yaml.safe_load(balucode.read_text())
    assert data["project_id"] == 7
    assert data["server_url"] == "https://balu.example.com"
    assert data["model"] == "llama3.1:8b"


@respx.mock
def test_init_aborts_if_balucode_yaml_exists_and_user_declines(tmp_path, monkeypatch):
    _setup_auth(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".balucode.yaml").write_text("project_id: 1\nserver_url: x\n")

    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.1:8b", "size": 1, "digest": "a"}]})
    )

    result = runner.invoke(app, ["init"], input="n\n")
    assert result.exit_code == 0
    # File not overwritten
    assert yaml.safe_load((tmp_path / ".balucode.yaml").read_text())["project_id"] == 1
