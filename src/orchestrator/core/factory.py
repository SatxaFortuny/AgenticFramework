import logging
import time

from langchain_mcp_adapters.client import MultiServerMCPClient

from core.IEmbeddingModel import IEmbeddingModel

# Abstract Interfaces
from core.IModel import IModel
from core.IVectorDB import IVectorDB
from core.logging_utils import elapsed_ms

# Pydantic Schemas
from core.schemas import FunctionalityConfig, ModelsConfig, VectorDBConfig
from infrastructure.ChromaDB import ChromaDB
from infrastructure.EmbedModelOllama import EmbedModelOllama

# Concrete Infrastructure Classes
from infrastructure.ModelGroq import ModelGroq
from infrastructure.ModelOllama import ModelOllama

logger = logging.getLogger(__name__)

MODEL_REGISTRY = {
    "ollama": ModelOllama,
    "groq": ModelGroq,
}

VECTORDB_REGISTRY = {
    "chromadb": ChromaDB
}

# CHANGED: keyed by embedding_provider (independent config field) instead of
# the vectordb `provider`. This is what actually lets a vectordb backend and
# an embedding backend be swapped independently of each other - e.g. Chroma
# paired with an OpenAI embedder, or a new vectordb paired with Ollama embed.
EMBEDDING_REGISTRY = {
    "ollama": EmbedModelOllama
}


def create_model(config: ModelsConfig) -> IModel:
    model_class = MODEL_REGISTRY.get(config.provider)
    if not model_class:
        raise ValueError(f"Unsupported model provider: {config.provider}")
    return model_class(model_name=config.model_name)


def create_vectordb(config: VectorDBConfig) -> IVectorDB:
    db_class = VECTORDB_REGISTRY.get(config.provider)
    if not db_class:
        raise ValueError(f"Unsupported VectorDB provider: {config.provider}")
    return db_class(collection_name=config.collection_name)


def create_embedder(config: VectorDBConfig) -> IEmbeddingModel:
    embedder_class = EMBEDDING_REGISTRY.get(config.embedding_provider)
    if not embedder_class:
        raise ValueError(
            f"No embedding backend registered for provider: {config.embedding_provider}"
        )
    return embedder_class(model_name=config.embedding_model)


async def get_filtered_mcp_tools(config: FunctionalityConfig):
    if not config.tools:
        logger.info("No MCP servers configured; skipping tool discovery")
        return []

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
    client = MultiServerMCPClient(mcp_dict)
    try:
        all_raw_tools = await client.get_tools()
    except Exception as exc:
        logger.error(
            "MCP tool discovery failed for %s after %.0f ms: %s",
            list(mcp_dict),
            elapsed_ms(start),
            exc,
        )
        raise

    safe_tools = [
        tool for tool in all_raw_tools
        if tool.name in allowed_tool_names
    ]

    logger.info(
        "MCP tools: discovered=%d allowed=%d in %.0f ms",
        len(all_raw_tools),
        len(safe_tools),
        elapsed_ms(start),
    )
    blocked = {tool.name for tool in all_raw_tools} - allowed_tool_names
    if blocked:
        logger.debug("MCP tools filtered out by allowlist: %s", sorted(blocked))
    missing = allowed_tool_names - {tool.name for tool in all_raw_tools}
    if missing:
        logger.warning("Allowed MCP tools not exposed by any server: %s", sorted(missing))

    return safe_tools
