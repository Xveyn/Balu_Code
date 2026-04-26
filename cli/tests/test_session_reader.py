"""Tests for session/reader.py."""

from __future__ import annotations

import json
from pathlib import Path

from balu_code_cli.session.reader import SessionReader


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _entry(direction: str, payload: dict, ts: str = "2026-04-26T14:00:00+00:00") -> dict:
    return {"direction": direction, "ts": ts, "payload": payload}


def test_messages_single_turn(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(
        path,
        [
            _entry("out", {"type": "user_message", "content": "hello"}),
            _entry(
                "in", {"type": "turn_start", "turn_id": "t1", "model": "m", "context_tokens": 0}
            ),
            _entry("in", {"type": "token", "content": "Hi "}),
            _entry("in", {"type": "token", "content": "there"}),
            _entry(
                "in",
                {
                    "type": "turn_end",
                    "turn_id": "t1",
                    "total_tokens": 10,
                    "iterations": 1,
                    "stop_reason": "done",
                },
            ),
        ],
    )
    msgs = SessionReader(path).messages()
    assert msgs == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there"},
    ]


def test_messages_multiple_turns(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(
        path,
        [
            _entry("out", {"type": "user_message", "content": "q1"}),
            _entry("in", {"type": "token", "content": "a1"}),
            _entry(
                "in",
                {
                    "type": "turn_end",
                    "turn_id": "t1",
                    "total_tokens": 5,
                    "iterations": 1,
                    "stop_reason": "done",
                },
            ),
            _entry("out", {"type": "user_message", "content": "q2"}),
            _entry("in", {"type": "token", "content": "a2"}),
            _entry(
                "in",
                {
                    "type": "turn_end",
                    "turn_id": "t2",
                    "total_tokens": 5,
                    "iterations": 1,
                    "stop_reason": "done",
                },
            ),
        ],
    )
    msgs = SessionReader(path).messages()
    assert msgs == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]


def test_messages_empty_file(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("")
    assert SessionReader(path).messages() == []


def test_metadata_turn_count(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(
        path,
        [
            _entry(
                "out", {"type": "user_message", "content": "q1"}, ts="2026-04-26T10:00:00+00:00"
            ),
            _entry(
                "in",
                {
                    "type": "turn_end",
                    "turn_id": "t1",
                    "total_tokens": 5,
                    "iterations": 1,
                    "stop_reason": "done",
                },
            ),
            _entry("out", {"type": "user_message", "content": "q2"}),
            _entry(
                "in",
                {
                    "type": "turn_end",
                    "turn_id": "t2",
                    "total_tokens": 5,
                    "iterations": 1,
                    "stop_reason": "done",
                },
            ),
        ],
    )
    meta = SessionReader(path).metadata()
    assert meta["turn_count"] == 2
    assert meta["start_ts"] == "2026-04-26T10:00:00+00:00"


def test_metadata_empty_file(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("")
    meta = SessionReader(path).metadata()
    assert meta["turn_count"] == 0
    assert meta["start_ts"] is None
