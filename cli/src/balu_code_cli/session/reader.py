"""SessionReader — reconstructs messages and metadata from a JSONL session file."""

from __future__ import annotations

import json
from pathlib import Path


class SessionReader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _lines(self) -> list[dict]:
        text = self._path.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def messages(self) -> list[dict]:
        result: list[dict] = []
        current_tokens: list[str] = []

        for entry in self._lines():
            direction = entry["direction"]
            payload = entry["payload"]
            event_type = payload.get("type")

            if direction == "out" and event_type == "user_message":
                if current_tokens:
                    result.append({"role": "assistant", "content": "".join(current_tokens)})
                    current_tokens = []
                result.append({"role": "user", "content": payload.get("content", "")})

            elif direction == "in" and event_type == "token":
                current_tokens.append(payload.get("content", ""))

            elif direction == "in" and event_type == "turn_end":
                if current_tokens:
                    result.append({"role": "assistant", "content": "".join(current_tokens)})
                    current_tokens = []

        if current_tokens:
            result.append({"role": "assistant", "content": "".join(current_tokens)})

        return result

    def metadata(self) -> dict:
        lines = self._lines()
        start_ts = lines[0]["ts"] if lines else None
        turn_count = sum(
            1 for e in lines
            if e["direction"] == "in" and e["payload"].get("type") == "turn_end"
        )
        return {"start_ts": start_ts, "turn_count": turn_count}
