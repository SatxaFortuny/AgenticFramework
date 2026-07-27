"""Generic in-process ToolProvider.

LocalToolRegistry doesn't know how to build any particular tool -- it's
just a container that takes an already-built list[Tool] and dispatches
calls to it. Which tools go into that list is decided by
tools/registry.py based on an app's manifest, not by this class.
"""

from core.interfaces import ToolProvider
from core.types import Tool, ToolResult


class LocalToolRegistry(ToolProvider):
    def __init__(self, tools: list[Tool]):
        self._tools = {t.spec.name: t for t in tools}

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def call_tool(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(name=name, output=f"Error: unknown tool '{name}'")
        try:
            output = tool.handler(arguments)
        except Exception as e:
            output = f"Error executing tool '{name}': {e}"
        return ToolResult(name=name, output=output)
