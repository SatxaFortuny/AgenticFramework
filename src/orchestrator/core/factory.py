import logging
import time

from langchain_mcp_adapters.client import MultiServerMCPClient

# Abstract Interfaces
from core.IEmbeddingModel import IEmbeddingModel
from core.IModel import IModel
from core.IVectorDB import IVectorDB
from core.logging_utils import elapsed_ms

# Pydantic Schemas
from core.schemas import (
    EmbeddingConfig,
    FunctionalityConfig,
    ModelConfig,
    VectorDBConfig,
)
from infrastructure.ChromaDB import ChromaDB
from infrastructure.EmbedModelOllama import EmbedModelOllama

# Concrete Infrastructure Classes
from infrastructure.ModelGroq import ModelGroq
from infrastructure.ModelOllama import ModelOllama

logger = logging.getLogger(__name__)

# This is the factory: it's the one place config strings ("ollama", "groq",
# "chromadb") get turned into real objects. Each registry maps a provider
# name (as written in YAML) to the concrete class that implements the
# matching interface (IModel / IVectorDB / IEmbeddingModel). Adding a new
# provider means adding one import + one dict entry here - nothing else in
# the codebase needs to know this file exists, since everything downstream
# only ever talks to the interface, not the concrete class.
MODEL_REGISTRY = {
    "ollama": ModelOllama,
    "groq": ModelGroq,
}

VECTORDB_REGISTRY = {"chromadb": ChromaDB}

# Keyed by embedding provider, independent from VECTORDB_REGISTRY's keys, so
# a vectordb backend and an embedding backend can be swapped independently
# of each other (e.g. Chroma paired with an OpenAI embedder).
EMBEDDING_REGISTRY = {"ollama": EmbedModelOllama}


def create_model(config: ModelConfig) -> IModel:
    """Builds the IModel implementation named by config.provider."""
    model_class = MODEL_REGISTRY.get(config.provider)
    if not model_class:
        raise ValueError(f"Unsupported model provider: {config.provider}")
    return model_class(model_name=config.model_name)


def create_vectordb(config: VectorDBConfig) -> IVectorDB:
    """Builds the IVectorDB implementation named by config.provider."""
    db_class = VECTORDB_REGISTRY.get(config.provider)
    if not db_class:
        raise ValueError(f"Unsupported VectorDB provider: {config.provider}")
    return db_class(collection_name=config.collection_name)


def create_embedder(config: EmbeddingConfig) -> IEmbeddingModel:
    """
    Builds the IEmbeddingModel implementation named by config.provider.
    Takes an EmbeddingConfig, not a VectorDBConfig - the two are independent
    (see EmbeddingConfig's docstring in schemas.py), so a vectordb object
    never needs to know which embedder produced the vectors it stores.
    """
    embedder_class = EMBEDDING_REGISTRY.get(config.provider)
    if not embedder_class:
        raise ValueError(
            f"No embedding backend registered for provider: {config.provider}"
        )
    return embedder_class(model_name=config.model_name)


async def get_filtered_mcp_tools(config: FunctionalityConfig):
    """
    Connects to every MCP server this functionality is configured to use,
    discovers all tools they expose, and returns only the ones on the
    allowlist (allowed_tools, per server) - this is the security boundary
    mentioned in MCPServerConfig's docstring: a compromised or misconfigured
    MCP server can expose extra tools, but the agent will never be bound to
    anything outside what the functionality's YAML explicitly allows.
    """
    if not config.tools:
        logger.info("No MCP servers configured; skipping tool discovery")
        return []

    # Build the {server_name: {url, transport}} shape MultiServerMCPClient
    # expects, and collect every allowed tool name across all servers into
    # one flat set (used for filtering after discovery, below).
    mcp_dict = {}
    allowed_tool_names = set()

    for tool_config in config.tools:
        mcp_dict[tool_config.server_name] = {
            "url": tool_config.url,
            "transport": tool_config.transport,
        }
        allowed_tool_names.update(tool_config.allowed_tools)

    logger.info(
        "Discovering MCP tools from %d server(s): %s", len(mcp_dict), list(mcp_dict)
    )
    start = time.perf_counter()
    # One client fans out to every configured server at once and returns
    # every tool every one of them exposes - unfiltered at this point.
    client = MultiServerMCPClient(mcp_dict)
    try:
        all_raw_tools = await client.get_tools()
    except Exception as exc:
        # Network/connection errors here would otherwise be swallowed by
        # whatever calls this function; log with timing before re-raising,
        # so a slow/failing MCP server is visible in the logs either way.
        logger.error(
            "MCP tool discovery failed for %s after %.0f ms: %s",
            list(mcp_dict),
            elapsed_ms(start),
            exc,
        )
        raise

    # The actual security filter: drop every tool not explicitly allowed.
    safe_tools = [tool for tool in all_raw_tools if tool.name in allowed_tool_names]

    logger.info(
        "MCP tools: discovered=%d allowed=%d in %.0f ms",
        len(all_raw_tools),
        len(safe_tools),
        elapsed_ms(start),
    )
    # Two sanity checks, logged but not fatal - they catch config drift
    # between the YAML allowlist and what the MCP servers actually expose.
    blocked = {tool.name for tool in all_raw_tools} - allowed_tool_names
    if blocked:
        logger.debug("MCP tools filtered out by allowlist: %s", sorted(blocked))
    # A tool named in allowed_tools that no server actually exposes is
    # probably a typo or a renamed/removed tool - worth a warning, since the
    # agent silently has one fewer capability than the config intended.
    missing = allowed_tool_names - {tool.name for tool in all_raw_tools}
    if missing:
        logger.warning(
            "Allowed MCP tools not exposed by any server: %s", sorted(missing)
        )

    return safe_tools
