"""
Shared data types passed across interface boundaries.

Kept as dataclasses (not raw dicts/strings) so that new fields can be
added later -- e.g. token usage on ModelResponse, or filters on
ScoredChunk -- without changing any interface's method signature.
"""

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Chunk:
    """A piece of a source document, before embedding/scoring. Produced
    by a Chunker, consumed by an EmbeddingModel + VectorStore."""
    id: str
    source_id: str
    title: str
    text: str


@dataclass
class ScoredChunk:
    id: str
    title: str
    text: str
    score: float


@dataclass
class ToolSpec:
    """What a ModelProvider needs to know about a tool to offer it to the
    model -- name, description, and a JSON schema for arguments. No
    handler here: the model doesn't execute tools, it only requests them.
    """
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
    # Room to grow further: usage, stop_reason, etc. will land here later
    # without touching the ModelProvider interface itself.


@dataclass
class RunResult:
    answer: str
    # Structured trace of what happened during this run -- which chunks
    # were retrieved, what was sent to the model, etc. This exists from
    # day one because both the eval harness (Phase 2) and observability
    # (Phase 5) need it, and it's much easier to require every
    # Orchestrator to produce it now than to retrofit it later.
    trace: list[dict] = field(default_factory=list)


@dataclass
class Tool:
    """
    What a ToolProvider deals in: a ToolSpec plus something that can
    actually execute it. `spec` is what gets handed to a ModelProvider;
    `handler` is only ever called by the ToolProvider itself, never by
    model adapters -- keeps execution out of the model layer entirely.
    """
    spec: ToolSpec
    handler: "Callable[[dict], str]"


@dataclass
class RunContext:
    """
    Carries the dependencies an Orchestrator needs, injected rather than
    constructed internally. retriever and tools are optional since not
    every Orchestrator needs both. worker_model is also optional: it
    exists for orchestrators that legitimately want two different models
    for two different jobs -- e.g. RouterOrchestrator using a fast/cheap
    model for the routing decision (`model`) and a stronger model for
    the actual generation (`worker_model`). Falls back to `model` when
    not set, so single-model configs are unaffected.
    """
    model: "ModelProvider"
    retriever: "Retriever | None" = None
    tools: "ToolProvider | None" = None
    worker_model: "ModelProvider | None" = None
