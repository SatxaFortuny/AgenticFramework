import ollama

from core.interfaces import ModelProvider
from core.types import ModelResponse, ToolCall, ToolSpec


def _to_ollama_tool(spec: ToolSpec) -> dict:
    """Translate our provider-agnostic ToolSpec into Ollama's tool schema."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


class OllamaProvider(ModelProvider):
    def __init__(self, model: str = "llama3.2"):
        self.model = model

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolSpec] | None = None,
    ) -> ModelResponse:
        kwargs = {}
        if tools:
            kwargs["tools"] = [_to_ollama_tool(t) for t in tools]

        response = ollama.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            **kwargs,
        )

        message = response["message"]
        tool_calls = [
            ToolCall(name=tc["function"]["name"], arguments=tc["function"]["arguments"])
            for tc in message.get("tool_calls", []) or []
        ]

        return ModelResponse(text=message.get("content", "") or "", tool_calls=tool_calls)
