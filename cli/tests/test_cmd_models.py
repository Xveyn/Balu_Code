"""Tests for commands/models.py."""
from __future__ import annotations

import httpx
import respx
from balu_code_cli.__main__ import app
from typer.testing import CliRunner

runner = CliRunner()
BASE = "https://balu.example.com/api/plugins/balu_code"


def _setup(tmp_path, monkeypatch):
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
def test_models_lists_names(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    respx.get(f"{BASE}/models").mock(
        return_value=httpx.Response(200, json={
            "models": [
                {"name": "llama3.1:8b", "size": 4_000_000_000, "digest": "abc"},
                {"name": "codellama:7b", "size": 3_500_000_000, "digest": "def"},
            ]
        })
    )
    result = runner.invoke(app, ["models"])
    assert result.exit_code == 0
    assert "llama3.1:8b" in result.output
    assert "codellama:7b" in result.output
