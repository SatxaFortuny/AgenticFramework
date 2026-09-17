import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

mcp = FastMCP(
    "WeatherServer",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
)

@mcp.tool()
async def get_weather(location: str) -> str:
    """Returns the current weather for a given location."""
    if location.lower() == "cambrils":
        return "Sunny and 24°C"
    return f"Partly cloudy and 18°C in {location}"

# Extract the underlying SSE web application
app = Starlette(routes=[Mount('/', app=mcp.sse_app())])

if __name__ == "__main__":
    # Explicitly define the port right here in the code
    uvicorn.run(app, host="0.0.0.0", port=8000)
