"""
Simplest possible Orchestrator: retrieve, then generate, once.
"""

from core.interfaces import Orchestrator
from core.prompts import DEFAULT_SEQUENTIAL_PROMPT_VERSION, get_prompt
from core.types import RunContext, RunResult

from typing import Literal
from pydantic import BaseModel

class SequentialOrchestratorConfig(BaseModel):
    type: Literal["sequential"]
    k: int | None = None
    prompt_version: str | None = None
    
    def build(self):
        # Exclude 'type' and any null values, pass the rest directly as kwargs
        kwargs = self.model_dump(exclude={"type"}, exclude_none=True)
        return SequentialOrchestrator(**kwargs)

class SequentialOrchestrator(Orchestrator):
    def __init__(self, k: int = 2, prompt_version: str = DEFAULT_SEQUENTIAL_PROMPT_VERSION):
        self.k = k
        self.prompt_version = prompt_version

    def run(self, query: str, context: RunContext) -> RunResult:
        system_prompt = get_prompt(self.prompt_version)
        chunks = context.retriever.retrieve(query, k=self.k)

        if not chunks:
            context_text = "(no relevant documentation found)"
        else:
            context_text = "\n\n".join(
                f"--- {c.title} ---\n{c.text.strip()}" for c in chunks
            )

        user_message = f"Documentation excerpts:\n\n{context_text}\n\nQuestion: {query}"
        response = context.model.generate(system_prompt, user_message)

        trace = [
            {
                "step": "retrieve",
                "query": query,
                "results": [
                    {"id": c.id, "title": c.title, "score": c.score} for c in chunks
                ],
            },
            {
                "step": "generate",
                "prompt_version": self.prompt_version,
                "system_prompt": system_prompt,
                "user_message": user_message,
            },
        ]

        return RunResult(answer=response.text, trace=trace)
