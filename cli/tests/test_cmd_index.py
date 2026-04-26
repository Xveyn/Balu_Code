"""Tests for commands/index.py."""
from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from balu_code_cli.__main__ import app

runner = CliRunner()
BASE = "https://balu.example.com/api/plugins/balu_code"


def _setup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    import importlib, balu_code_cli.config.paths as p
    importlib.reload(p)
    from balu_code_cli.config.loader import AppConfig, Credentials, ServerCredentials, save_config, save_credentials
    save_config(AppConfig(server_url="https://balu.example.com"), p.config_yaml())
    save_credentials(
        Credentials(servers={"https://balu.example.com": ServerCredentials(api_key="bc_key")}),
        p.credentials_yaml(),
    )


@respx.mock
def test_index_polls_until_done(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / ".balucode.yaml").write_text(
        "project_id: 3\nserver_url: https://balu.example.com\n"
    )
    monkeypatch.chdir(tmp_path)

    respx.post(f"{BASE}/projects/3/index").mock(
        return_value=httpx.Response(202, json={"job_id": "j1", "project_id": 3, "status": "running"})
    )
    respx.get(f"{BASE}/projects/3/index/status/j1").mock(
        return_value=httpx.Response(200, json={
            "job_id": "j1", "project_id": 3, "status": "done",
            "files_total": 20, "files_processed": 20, "chunks_total": 150,
            "error": None, "started_at": None, "finished_at": None,
        })
    )
    result = runner.invoke(app, ["index"])
    assert result.exit_code == 0
    assert "20" in result.output  # files_total


@respx.mock
def test_index_shows_error_on_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / ".balucode.yaml").write_text(
        "project_id: 3\nserver_url: https://balu.example.com\n"
    )
    monkeypatch.chdir(tmp_path)

    respx.post(f"{BASE}/projects/3/index").mock(
        return_value=httpx.Response(202, json={"job_id": "j2", "project_id": 3, "status": "running"})
    )
    respx.get(f"{BASE}/projects/3/index/status/j2").mock(
        return_value=httpx.Response(200, json={
            "job_id": "j2", "project_id": 3, "status": "failed",
            "files_total": 0, "files_processed": 0, "chunks_total": 0,
            "error": "disk full", "started_at": None, "finished_at": None,
        })
    )
    result = runner.invoke(app, ["index"])
    assert result.exit_code != 0
    assert "disk full" in result.output
