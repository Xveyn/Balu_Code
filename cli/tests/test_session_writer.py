"""Tests for session/writer.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from balu_code_cli.config.paths import sessions_dir
from balu_code_cli.session.writer import SessionWriter


def test_sessions_dir_uses_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d = sessions_dir("https://balu.example.com", 42)
    assert str(tmp_path) in str(d)
    assert "balu-code" in str(d)
    assert "sessions" in str(d)


def test_sessions_dir_falls_back_to_local_share(monkeypatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    d = sessions_dir("https://balu.example.com", 42)
    assert ".local/share/balu-code/sessions" in str(d)


def test_sessions_dir_same_url_project_same_hash():
    d1 = sessions_dir("https://balu.example.com", 1)
    d2 = sessions_dir("https://balu.example.com", 1)
    assert d1 == d2


def test_sessions_dir_different_project_different_hash():
    d1 = sessions_dir("https://balu.example.com", 1)
    d2 = sessions_dir("https://balu.example.com", 2)
    assert d1 != d2


def test_write_sent_creates_file(tmp_path):
    path = tmp_path / "session.jsonl"
    with SessionWriter(path) as w:
        w.write_sent({"type": "user_message", "content": "hello"})
    assert path.exists()
    line = json.loads(path.read_text().strip())
    assert line["direction"] == "out"
    assert line["payload"]["type"] == "user_message"
    assert "ts" in line


def test_write_event_appends_line(tmp_path):
    path = tmp_path / "session.jsonl"

    class FakeEvent:
        def model_dump(self):
            return {"type": "token", "content": "hello"}

    with SessionWriter(path) as w:
        w.write_event(FakeEvent())
        w.write_event(FakeEvent())
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert all(l["direction"] == "in" for l in lines)


def test_written_lines_are_valid_json(tmp_path):
    path = tmp_path / "session.jsonl"

    class FakeEvent:
        def model_dump(self):
            return {"type": "turn_end", "turn_id": "t1", "total_tokens": 50,
                    "iterations": 1, "stop_reason": "done"}

    with SessionWriter(path) as w:
        w.write_sent({"type": "user_message", "content": "test"})
        w.write_event(FakeEvent())
    for line in path.read_text().splitlines():
        obj = json.loads(line)
        assert "direction" in obj
        assert "ts" in obj
        assert "payload" in obj
