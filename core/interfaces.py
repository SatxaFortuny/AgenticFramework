"""
The contracts. Nothing in here has any implementation -- these are the
ports that adapters (concrete ModelProviders, Retrievers, ToolProviders)
and strategies (concrete Orchestrators) must satisfy.

Rule of thumb enforced by this design: code outside of core/build.py's
wiring step should never import a concrete class from adapters/ or
orchestrators/ directly -- only these interfaces from core/.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel

from core.types import (
    Chunk,
    ModelResponse,
    RunContext,
    RunResult,
    ScoredChunk,
    Tool,
    ToolResult,
    ToolSpec,
)


class ModelProvider(ABC):
    """A swappable text-generation backend (local model, cloud API, ...)."""

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolSpec] | None = None,
    ) -> ModelResponse:
        """
        tools is optional -- most calls won't need it. When provided, the
        adapter is responsible for translating ToolSpec into whatever
        wire format its underlying API wants, and for translating any
        tool-call response back into ModelResponse.tool_calls. Calling
        code never needs to know the underlying API's tool-calling shape.
        """
        ...


class Document(BaseModel):
    content: str
    metadata: dict = {}


class Chunker(ABC):
    @abstractmethod
    def chunk(self, text: str, metadata: dict | None = None) -> list[Document]:
        """Splits a large text into smaller Document chunks."""
        pass


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Converts a list of strings into a list of vector embeddings."""
        pass


class VectorStore(ABC):
    @abstractmethod
    def add(self, documents: list[Document], embeddings: list[list[float]]) -> None:
        """Stores documents and their corresponding embeddings."""
        pass

    @abstractmethod
    def search(self, query_embedding: list[float], top_k: int = 5) -> list[Document]:
        """Searches the database for the closest vectors."""
        pass


class Retriever(ABC):
    """
    What tools/orchestrators depend on to look things up -- deliberately
    thinner than the full Rag object (no ingest()), so callers can't
    accidentally write to the index through a tool.
    """

    @abstractmethod
    def retrieve(self, query: str, k: int | None = None) -> list[Document]:
        """Returns the top-k most relevant Documents for the query.

        k overrides the retriever's configured default when provided.
        """
        ...


class ToolProvider(ABC):
    """
    A swappable source of tools -- a local Python function registry, or
    an MCP server. Orchestrators ask a ToolProvider what's available and
    ask it to execute calls; they never call tool handlers directly.
    """

    @abstractmethod
    def list_tools(self) -> list[Tool]:
        ...

    @abstractmethod
    def call_tool(self, name: str, arguments: dict) -> ToolResult:
        ...


class Orchestrator(ABC):
    """
    A swappable coordination strategy: sequential retrieve-then-generate,
    router/supervisor dispatching to tools, multi-agent later. Every
    implementation must go through this one entry point and return a
    RunResult carrying a trace -- no orchestrator-specific hooks or
    callbacks at this layer, so that swapping orchestrators never
    requires touching calling code.
    """

    @abstractmethod
    def run(self, query: str, context: RunContext) -> RunResult:
        ...