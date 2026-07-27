"""Single entrypoint for tool access in the framework.

factory.py should call build_tool_provider(app_id, retriever) and use
whatever it returns -- it should never import tools.local.* or
tools.mcp.* directly. That keeps "which app can use which tools" fully
determined by tools/configs/apps/<app_id>.yaml, in one place, instead
of scattered across app code.
"""

from pathlib import Path

import yaml

from core.interfaces import Retriever, ToolProvider
from core.types import Tool, ToolResult
from tools.configs.schema import AppToolsManifest
from tools.local.base import LocalToolRegistry
from tools.local.catalog import TOOL_CATALOG
from tools.mcp.provider import MCPToolProvider

CONFIGS_DIR = Path(__file__).parent / "configs"
MCP_SERVERS_PATH = CONFIGS_DIR / "mcp_servers.yaml"
APP_MANIFESTS_DIR = CONFIGS_DIR / "apps"


def _load_mcp_servers() -> dict[str, dict]:
    with open(MCP_SERVERS_PATH) as f:
        data = yaml.safe_load(f) or {}
    return data.get("servers") or {}


def load_app_manifest(app_id: str) -> AppToolsManifest:
    path = APP_MANIFESTS_DIR / f"{app_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No tools manifest found for app '{app_id}' at {path}")
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return AppToolsManifest(**data)


class CompositeToolProvider(ToolProvider):
    """Merges several ToolProviders (one local registry + one per
    granted MCP server) into a single ToolProvider, so the rest of the
    framework (orchestrators, agents) never has to know tools came from
    different backends."""

    def __init__(self, providers: list[ToolProvider]):
        self._providers = providers
        self._tool_owner: dict[str, ToolProvider] = {}
        for provider in providers:
            for tool in provider.list_tools():
                self._tool_owner[tool.spec.name] = provider

    def list_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for provider in self._providers:
            tools.extend(provider.list_tools())
        return tools

    def call_tool(self, name: str, arguments: dict) -> ToolResult:
        provider = self._tool_owner.get(name)
        if provider is None:
            return ToolResult(name=name, output=f"Error: unknown tool '{name}'")
        return provider.call_tool(name, arguments)


def build_tool_provider(app_id: str, retriever: Retriever | None = None) -> ToolProvider:
    """Resolve an app's manifest into a ToolProvider scoped to exactly
    what that app was granted -- nothing more."""
    manifest = load_app_manifest(app_id)
    providers: list[ToolProvider] = []

    # --- local tools (shared + this app's own) ---
    local_tools: list[Tool] = []
    for tool_ref in manifest.local_tools:
        builder = TOOL_CATALOG.get(tool_ref)
        if builder is None:
            raise KeyError(
                f"App '{app_id}' requests unknown local tool '{tool_ref}'. "
                f"Check tools/local/catalog.py."
            )
        local_tools.append(builder(retriever))
    if local_tools:
        providers.append(LocalToolRegistry(local_tools))

    # --- MCP servers this app was granted ---
    available_servers = _load_mcp_servers()
    for server_name in manifest.mcp_servers:
        server_cfg = available_servers.get(server_name)
        if server_cfg is None:
            raise KeyError(
                f"App '{app_id}' requests unknown MCP server '{server_name}'. "
                f"Check tools/configs/mcp_servers.yaml."
            )
        providers.append(
            MCPToolProvider(
                command=server_cfg["command"],
                args=server_cfg.get("args", []),
            )
        )

    return CompositeToolProvider(providers)
