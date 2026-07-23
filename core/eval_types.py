"""
Types for the eval harness. Kept separate from core/types.py since these
are specific to evaluation, not to the runtime request path.
"""

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    id: str
    query: str
    # Which doc id we expect the retriever to surface. None = not checked.
    expected_source_id: str | None = None
    # Substrings (case-insensitive) we expect to appear somewhere in the
    # answer. Crude but transparent -- good enough before adding an
    # LLM-as-judge scorer later.
    required_keywords: list[str] = field(default_factory=list)
    # Tool-routing expectations, for pipelines with a ToolProvider.
    # None = not checked. True = a tool call is expected (optionally a
    # specific one via expected_tool_name). False = NO tool call is
    # expected (e.g. greetings/small talk) -- this is what catches
    # over-triggering regressions like the one we found and fixed.
    expects_tool_call: bool | None = None
    expected_tool_name: str | None = None


@dataclass
class EvalScore:
    case_id: str
    query: str
    retrieval_hit: bool | None       # None if not checked or not applicable
    keyword_coverage: float          # fraction of required_keywords found, 0-1
    tool_routing_correct: bool | None  # None if not checked or not applicable
    latency_seconds: float
    answer: str
