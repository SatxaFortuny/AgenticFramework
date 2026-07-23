import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from core.interfaces import ToolProvider, Retriever
from core.types import Tool, ToolResult, ToolSpec

from typing import Literal
from pydantic import BaseModel, Field

class MCPToolsConfig(BaseModel):
    type: Literal["mcp"]
    command: str
    args: list[str] = Field(default_factory=list)
    def build(self, retriever: Retriever | None) -> ToolProvider:
        return MCPToolProvider(command=self.command, args=self.args)

class MCPToolProvider(ToolProvider):
    def __init__(self, command: str, args: list[str] | None = None):
        self.server_params = StdioServerParameters(command=command, args=args or [])

    async def _list_tools_async(self) -> list[Tool]:
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [
                    Tool(
                        spec=ToolSpec(
                            name=t.name,
                            description=t.description or "",
                            parameters=t.inputSchema,
                        ),
                        # MCP tools are executed on the server, not locally --
                        # this handler exists only to satisfy the Tool type;
                        # ToolProvider.call_tool (below) is the real path.
                        handler=lambda arguments, _name=t.name: self._call_tool_sync(
                            _name, arguments
                        ),
                    )
                    for t in result.tools
                ]

    async def _call_tool_async(self, name: str, arguments: dict) -> str:
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                return "\n".join(
                    block.text for block in result.content if hasattr(block, "text")
                )

    def _call_tool_sync(self, name: str, arguments: dict) -> str:
        return asyncio.run(self._call_tool_async(name, arguments))

    def list_tools(self) -> list[Tool]:
        return asyncio.run(self._list_tools_async())

    def call_tool(self, name: str, arguments: dict) -> ToolResult:
        try:
            output = asyncio.run(self._call_tool_async(name, arguments))
        except Exception as e:
            output = f"Error calling MCP tool '{name}': {e}"
        return ToolResult(name=name, output=output)
