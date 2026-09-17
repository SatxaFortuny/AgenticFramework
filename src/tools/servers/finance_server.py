import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

mcp = FastMCP(
    "FinanceServer",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
)

@mcp.tool()
async def sql_read(query: str) -> str:
    """Simulates reading data from a financial database."""
    return f"Simulated SQL read execution for: {query}\nResults: Q3 revenue up 12%."

@mcp.tool()
async def sql_write(query: str) -> str:
    """Simulates writing data to a financial database."""
    return f"Simulated SQL write execution for: {query}\nStatus: Success. 1 row updated."

# Extract the underlying SSE web application
app = Starlette(routes=[Mount('/', app=mcp.sse_app())])

if __name__ == "__main__":
    # Explicitly define the port right here in the code
    uvicorn.run(app, host="0.0.0.0", port=8001)
