from core.interfaces import Orchestrator
from core.types import RunContext, RunResult

SYSTEM_PROMPT = """You are a documentation assistant for the Fetchly HTTP \
client library. Answer the user's question using ONLY the provided \
documentation excerpts below. If the excerpts don't contain the answer, \
say so explicitly rather than guessing.
"""


class SequentialOrchestrator(Orchestrator):
    def __init__(self, k: int = 2):
        self.k = k

    def run(self, query: str, context: RunContext) -> RunResult:
        chunks = context.retriever.retrieve(query, k=self.k)

        if not chunks:
            context_text = "(no relevant documentation found)"
        else:
            context_text = "\n\n".join(
                f"--- {c.title} ---\n{c.text.strip()}" for c in chunks
            )

        user_message = f"Documentation excerpts:\n\n{context_text}\n\nQuestion: {query}"
        response = context.model.generate(SYSTEM_PROMPT, user_message)

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
                "system_prompt": SYSTEM_PROMPT,
                "user_message": user_message,
            },
        ]

        return RunResult(answer=response.text, trace=trace)
