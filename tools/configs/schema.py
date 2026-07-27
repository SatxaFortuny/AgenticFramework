"""The access-control manifest for tools.

An AppToolsManifest is the declarative answer to "what is this app
allowed to touch?" -- both local tools and MCP servers. tools/registry.py
reads this and builds a ToolProvider that can only see what's listed
here; an app's code cannot reach a tool it wasn't granted, even if the
tool exists elsewhere in the framework.
"""

from pydantic import BaseModel, Field


class AppToolsManifest(BaseModel):
    app_id: str
    local_tools: list[str] = Field(default_factory=list)  # keys into tools.local.catalog.TOOL_CATALOG
    mcp_servers: list[str] = Field(default_factory=list)  # names into tools/configs/mcp_servers.yaml
