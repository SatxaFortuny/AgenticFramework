from typing import List
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Server1")

@mcp.tool()
async def get_favorite_fruit(name: str) -> str:
    if name == "Satxa":
        return "apple"
    return "No user by that name"

if __name__ == "__main__":
    mcp.run(transport="sse")