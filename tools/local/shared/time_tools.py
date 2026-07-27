"""Shared local tools -- reusable by any app in the framework.

Anything in tools/local/shared/ is considered "public": it has no
dependency on a specific app's data or domain, so it's safe to expose
to whichever apps request it in their manifest.
"""

from datetime import datetime, timezone

from core.types import Tool, ToolSpec


def build_current_time_tool() -> Tool:
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
