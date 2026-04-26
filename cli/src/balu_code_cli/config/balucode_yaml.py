"""BaluCodeYaml — .balucode.yaml parser + walk-up search."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class ToolsConfig(BaseModel):
    allow_write: bool = False
    allow_bash: bool = False
    allow_web_fetch: bool = True


_WRITE_TOOLS = {"write_file", "apply_patch"}
_BASH_TOOLS = {"run_bash"}
_NETWORK_TOOLS = {"web_fetch"}


class BaluCodeYaml(BaseModel):
    project_id: int
    server_url: str
    model: str | None = None
    tools: ToolsConfig = ToolsConfig()

    def is_tool_allowed(self, tool_name: str) -> bool:
        if tool_name in _WRITE_TOOLS:
            return self.tools.allow_write
        if tool_name in _BASH_TOOLS:
            return self.tools.allow_bash
        if tool_name in _NETWORK_TOOLS:
            return self.tools.allow_web_fetch
        return True


def find_balucode_yaml(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / ".balucode.yaml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def load_balucode_yaml(path: Path | None = None) -> BaluCodeYaml:
    found = path or find_balucode_yaml()
    if found is None:
        raise FileNotFoundError("No .balucode.yaml found. Run `balu-code init` first.")
    return BaluCodeYaml.model_validate(yaml.safe_load(found.read_text()))


__all__ = ["BaluCodeYaml", "ToolsConfig", "find_balucode_yaml", "load_balucode_yaml"]
