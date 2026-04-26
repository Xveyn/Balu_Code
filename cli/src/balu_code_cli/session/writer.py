"""SessionWriter — appends WS events to a JSONL session file."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _event_to_dict(event: Any) -> dict:
    if hasattr(event, "model_dump"):
        return event.model_dump()
    if hasattr(event, "__dict__"):
        return vars(event)
    return {"raw": str(event)}


class SessionWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None

    def _open(self) -> None:
        if self._fh is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("a", encoding="utf-8")

    def _write(self, direction: str, payload: dict) -> None:
        self._open()
        line = json.dumps({
            "direction": direction,
            "ts": datetime.now(UTC).isoformat(),
            "payload": payload,
        })
        self._fh.write(line + "\n")
        self._fh.flush()

    def write_sent(self, payload: dict) -> None:
        self._write("out", payload)

    def write_event(self, event: Any) -> None:
        self._write("in", _event_to_dict(event))

    def __enter__(self) -> SessionWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
