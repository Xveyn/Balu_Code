"""Tests for commands/auth.py."""
from __future__ import annotations

import httpx
import respx
from balu_code_cli.__main__ import app
from typer.testing import CliRunner

runner = CliRunner()
BASE = "https://balu.example.com/api/plugins/balu_code"


@respx.mock
def test_auth_login_success(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib

    import balu_code_cli.config.paths as p
    importlib.reload(p)

    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = runner.invoke(
        app,
        ["auth", "login"],
        input="https://balu.example.com\nbc_testkey123\n",
    )
    assert result.exit_code == 0
    assert "Logged in" in result.output


@respx.mock
def test_auth_login_bad_key_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib

    import balu_code_cli.config.paths as p
    importlib.reload(p)

    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(401))
    result = runner.invoke(
        app,
        ["auth", "login"],
        input="https://balu.example.com\nbad_key\n",
    )
    assert result.exit_code != 0


@respx.mock
def test_auth_status_shows_server(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib

    import balu_code_cli.config.paths as p
    importlib.reload(p)

    # Pre-populate credentials
    from balu_code_cli.config.loader import (
        AppConfig,
        Credentials,
        ServerCredentials,
        save_config,
        save_credentials,
    )
    importlib.reload(p)
    save_config(AppConfig(server_url="https://balu.example.com"), p.config_yaml())
    save_credentials(
        Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_abc12345")}),
        p.credentials_yaml(),
    )

    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    assert "balu.example.com" in result.output
