from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ScoredChunk:
    id: str
    title: str
    text: str
    score: float


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON schema, e.g. {"type": "object", "properties": {...}}


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class ToolResult:
    name: str
    output: str


@dataclass
class ModelResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class RunResult:
    answer: str
    trace: list[dict] = field(default_factory=list)


@dataclass
class Tool:
    spec: ToolSpec
    handler: "Callable[[dict], str]"


@dataclass
class RunContext:
    model: "ModelProvider"
    retriever: "Retriever | None" = None
    tools: "ToolProvider | None" = None
