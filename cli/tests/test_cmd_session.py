"""Tests for commands/session.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from balu_code_cli.commands.session import app
from typer.testing import CliRunner

runner = CliRunner()

_BALUCODE_YAML = "project_id: 1\nserver_url: https://balu.example.com\n"


def _write_session(sess_dir: Path, filename: str, turns: int = 2) -> Path:
    path = sess_dir / filename
    lines = []
    for i in range(turns):
        lines.append(json.dumps({
            "direction": "out",
            "ts": f"2026-04-26T1{i}:00:00+00:00",
            "payload": {"type": "user_message", "content": f"q{i}"},
        }))
        lines.append(json.dumps({
            "direction": "in",
            "ts": f"2026-04-26T1{i}:00:01+00:00",
            "payload": {"type": "token", "content": f"a{i}"},
        }))
        lines.append(json.dumps({
            "direction": "in",
            "ts": f"2026-04-26T1{i}:00:02+00:00",
            "payload": {"type": "turn_end", "turn_id": f"t{i}",
                        "total_tokens": 10, "iterations": 1, "stop_reason": "done"},
        }))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_session_list_no_sessions(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = tmp_path / "empty_sessions"
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No sessions" in result.output


def test_session_list_shows_sessions(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    _write_session(sess_dir, "2026-04-26T14-00-00_sven_aaaabbbb-0000-0000-0000-000000000001.jsonl", turns=2)
    _write_session(sess_dir, "2026-04-25T09-00-00_sven_aaaabbbb-0000-0000-0000-000000000002.jsonl", turns=5)
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "2" in result.output
    assert "5" in result.output


def test_session_delete_confirmed(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    sess_file = _write_session(
        sess_dir, "2026-04-26T14-00-00_sven_deadbeef-0000-0000-0000-000000000001.jsonl"
    )
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        result = runner.invoke(app, ["delete", "deadbeef"], input="y\n")
    assert result.exit_code == 0
    assert not sess_file.exists()


def test_session_delete_aborted(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    sess_file = _write_session(
        sess_dir, "2026-04-26T14-00-00_sven_deadbeef-0000-0000-0000-000000000001.jsonl"
    )
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        result = runner.invoke(app, ["delete", "deadbeef"], input="N\n")
    assert result.exit_code == 0
    assert sess_file.exists()


def test_session_resume_calls_run_chat_with_initial_messages(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    from balu_code_cli.config.loader import Credentials, ServerCredentials
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    _write_session(
        sess_dir, "2026-04-26T14-00-00_sven_cafebabe-0000-0000-0000-000000000001.jsonl", turns=1
    )
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir, \
         patch("balu_code_cli.commands.session.load_credentials") as mock_creds, \
         patch("balu_code_cli.commands.session.run_chat") as mock_run:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        mock_creds.return_value = Credentials(
            servers={"https://balu.example.com": ServerCredentials(api_key="testkey")}
        )
        mock_run.return_value = None
        result = runner.invoke(app, ["resume", "cafebabe"])
    assert result.exit_code == 0
    call_kwargs = mock_run.call_args.kwargs
    assert "initial_messages" in call_kwargs
    assert len(call_kwargs["initial_messages"]) >= 1


def test_session_resume_ambiguous_prefix(tmp_path):
    from balu_code_cli.config.balucode_yaml import BaluCodeYaml
    sess_dir = tmp_path / "sessions"
    sess_dir.mkdir()
    _write_session(sess_dir, "2026-04-26T14-00-00_sven_aabbccdd-1111-0000-0000-000000000001.jsonl")
    _write_session(sess_dir, "2026-04-26T15-00-00_sven_aabbccdd-2222-0000-0000-000000000002.jsonl")
    with patch("balu_code_cli.commands.session.load_balucode_yaml") as mock_load, \
         patch("balu_code_cli.commands.session.sessions_dir") as mock_dir:
        mock_load.return_value = BaluCodeYaml(project_id=1, server_url="https://balu.example.com")
        mock_dir.return_value = sess_dir
        result = runner.invoke(app, ["resume", "aabbccdd"])
    assert result.exit_code != 0
    assert "Ambiguous" in result.output
