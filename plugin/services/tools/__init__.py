"""Tool registry + Phase-4a convenience exports.

``default_registry()`` (added in Task 8) will return a ``ToolRegistry``
pre-populated with the Phase-4a read tools.
"""

from __future__ import annotations

from plugin.services.tools.base import Tool, ToolContext, ToolResult
from plugin.services.tools.glob_tool import GlobTool
from plugin.services.tools.grep_tool import GrepTool
from plugin.services.tools.read_file import ReadFileTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def ollama_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.args_schema.model_json_schema(),
                },
            }
            for t in self._tools.values()
        ]


def default_registry() -> ToolRegistry:
    """Return a ToolRegistry pre-populated with the Phase-4a read tools."""
    reg = ToolRegistry()
    reg.register(ReadFileTool())
    reg.register(GlobTool())
    reg.register(GrepTool())
    return reg


__all__ = [
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "default_registry",
]
