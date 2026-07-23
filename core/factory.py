from pathlib import Path
from typing import Annotated, Union

import yaml
from pydantic import BaseModel, Field

from core import RunContext
from core.interfaces import Chunker, Document, Embedder, Retriever, VectorStore
from models import (
    FallbackConfig,
    GeminiConfig,
    GroqConfig,
)
from orchestrators import RouterOrchestratorConfig, SequentialOrchestratorConfig
from rag import (
    ParagraphChunkerConfig,
    OllamaEmbedderConfig,
    ChromaVectorConfig,
)
from tools import LocalToolsConfig, MCPToolsConfig


ModelConfigType = Annotated[
    Union[GroqConfig, GeminiConfig, FallbackConfig],
    Field(discriminator="type")
]

ToolConfigType = Annotated[
    Union[LocalToolsConfig, MCPToolsConfig],
    Field(discriminator="type")
]

OrchestratorConfigType = Annotated[
    Union[SequentialOrchestratorConfig, RouterOrchestratorConfig],
    Field(discriminator="type")
]

EmbedderConfigType = Annotated[
    Union[OllamaEmbedderConfig],
    Field(discriminator="type")
]

VectorStoreConfigType = Annotated[
    Union[ChromaVectorConfig],
    Field(discriminator="type")
]

ChunkerConfigType = Annotated[
    Union[ParagraphChunkerConfig],
    Field(discriminator="type")
]


class Rag(Retriever):
    """The orchestrator that wires the RAG components together."""
    def __init__(
        self,
        chunker: Chunker,
        embedder: Embedder,
        vector_store: VectorStore,
        top_k: int = 5
    ):
        self.chunker = chunker
        self.embedder = embedder
        self.vector_store = vector_store
        self.top_k = top_k

    def ingest(self, text: str, metadata: dict | None = None) -> None:
        chunks = self.chunker.chunk(text, metadata)
        if not chunks:
            return

        texts = [chunk.content for chunk in chunks]
        embeddings = self.embedder.embed(texts)
        self.vector_store.add(chunks, embeddings)

    def retrieve(self, query: str, k: int | None = None) -> list[Document]:
        query_embedding = self.embedder.embed([query])[0]
        return self.vector_store.search(query_embedding, k or self.top_k)


class PipelineConfig(BaseModel):
    model_provider: ModelConfigType
    worker_model_provider: ModelConfigType | None = None
    embedder: EmbedderConfigType
    vectordb: VectorStoreConfigType
    chunker: ChunkerConfigType
    tools: ToolConfigType | None = None
    orchestrator: OrchestratorConfigType

FallbackConfig.model_rebuild(_types_namespace={"ModelConfigType": ModelConfigType})
PipelineConfig.model_rebuild()

# ==========================================
# 3. Factory Build Functions
# ==========================================

def build_pipeline_from_config(config_dict: dict):
    # 1. Pydantic validates the dictionary and converts it into strongly-typed objects
    config = PipelineConfig.model_validate(config_dict)

    # 2. Call the build() methods to instantiate the actual framework classes
    model = config.model_provider.build()
    worker_model = config.worker_model_provider.build() if config.worker_model_provider else None

    # The RAG stack is always assembled from its three components -- there's
    # no standalone "retriever" config, just chunker + embedder + vectordb
    # wired together by Rag.
    chunker = config.chunker.build()
    embedder = config.embedder.build()
    vector_store = config.vectordb.build()
    retriever = Rag(chunker=chunker, embedder=embedder, vector_store=vector_store)

    tools = config.tools.build(retriever) if config.tools else None
    orchestrator = config.orchestrator.build()

    # 3. Assemble and return
    context = RunContext(model=model, worker_model=worker_model, retriever=retriever, tools=tools)
    return orchestrator, context

def build_pipeline_from_file(path: str | Path):
    with open(path) as f:
        config_dict = yaml.safe_load(f)
    return build_pipeline_from_config(config_dict)