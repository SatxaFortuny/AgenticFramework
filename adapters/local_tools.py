from datetime import datetime, timezone

from core.interfaces import Retriever, ToolProvider
from core.types import Tool, ToolResult, ToolSpec


def _make_search_docs_tool(retriever: Retriever) -> Tool:
    def handler(arguments: dict) -> str:
        query = arguments.get("query", "")
        chunks = retriever.retrieve(query, k=2)
        if not chunks:
            return "No relevant documentation found."
        return "\n\n".join(f"--- {c.title} ---\n{c.text.strip()}" for c in chunks)

    return Tool(
        spec=ToolSpec(
            name="search_fetchly_docs",
            description=(
                "Search the Fetchly HTTP client library documentation for "
                "information about how to use the library (installation, "
                "timeouts, retries, auth, error handling)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to search for in the docs.",
                    }
                },
                "required": ["query"],
            },
        ),
        handler=handler,
    )


def _make_current_time_tool() -> Tool:
    def handler(arguments: dict) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return Tool(
        spec=ToolSpec(
            name="get_current_time",
            description="Get the current date and time in UTC.",
            parameters={"type": "object", "properties": {}},
        ),
        handler=handler,
    )


class LocalToolRegistry(ToolProvider):
    def __init__(self, retriever: Retriever):
        self._tools = {
            t.spec.name: t
            for t in [_make_search_docs_tool(retriever), _make_current_time_tool()]
        }

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
