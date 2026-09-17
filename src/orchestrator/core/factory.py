from langchain_mcp_adapters.client import MultiServerMCPClient

from core.IEmbeddingModel import IEmbeddingModel

# Abstract Interfaces
from core.IModel import IModel
from core.IVectorDB import IVectorDB

# Pydantic Schemas
from core.schemas import FunctionalityConfig, ModelsConfig, VectorDBConfig
from infrastructure.ChromaDB import ChromaDB
from infrastructure.EmbedModelOllama import EmbedModelOllama

# Concrete Infrastructure Classes
from infrastructure.ModelOllama import ModelOllama

MODEL_REGISTRY = {
    "ollama": ModelOllama
}

VECTORDB_REGISTRY = {
    "chromadb": ChromaDB
}

EMBEDDING_REGISTRY = {
    "chromadb": EmbedModelOllama  # embedding backend paired with the chromadb provider
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
    embedder_class = EMBEDDING_REGISTRY.get(config.provider)
    if not embedder_class:
        raise ValueError(f"No embedding backend registered for provider: {config.provider}")
    return embedder_class(model_name=config.embedding_model)


async def get_filtered_mcp_tools(config: FunctionalityConfig):
    if not config.tools:
        return []

    mcp_dict = {}
    allowed_tool_names = set()

    for tool_config in config.tools:
        mcp_dict[tool_config.server_name] = {
            "url": tool_config.url,
            "transport": tool_config.transport,
        }
        allowed_tool_names.update(tool_config.allowed_tools)

    client = MultiServerMCPClient(mcp_dict)
    all_raw_tools = await client.get_tools()

    safe_tools = [
        tool for tool in all_raw_tools
        if tool.name in allowed_tool_names
    ]

    return safe_tools
