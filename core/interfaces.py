from abc import ABC, abstractmethod

from core.types import (
    ModelResponse,
    RunContext,
    RunResult,
    ScoredChunk,
    Tool,
    ToolResult,
    ToolSpec,
)


class ModelProvider(ABC):

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolSpec] | None = None,
    ) -> ModelResponse:
        ...


class Retriever(ABC):

    @abstractmethod
    def retrieve(self, query: str, k: int = 2) -> list[ScoredChunk]:
        ...


class ToolProvider(ABC):

    @abstractmethod
    def list_tools(self) -> list[Tool]:
        ...

    @abstractmethod
    def call_tool(self, name: str, arguments: dict) -> ToolResult:
        ...


class Orchestrator(ABC):

    @abstractmethod
    def run(self, query: str, context: RunContext) -> RunResult:
        ...
