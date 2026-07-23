import json

from groq import Groq

from core.interfaces import ModelProvider
from core.types import ModelResponse, ToolCall, ToolSpec

from typing import Literal
from pydantic import BaseModel

class GroqConfig(BaseModel):
    type: Literal["groq"]
    model: str = "qwen/qwen3.6-27b"
    def build(self) -> ModelProvider:
        return GroqProvider(model=self.model)

def _to_groq_tool(spec: ToolSpec) -> dict:
    """Translate our provider-agnostic ToolSpec into Groq's (OpenAI-compatible) tool schema."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


class GroqProvider(ModelProvider):
    def __init__(self, model: str = "qwen/qwen3.6-27b"):
        self.model = model
        self._client: Groq | None = None

    def _get_client(self) -> Groq:
        if self._client is None:
            self._client = Groq()
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolSpec] | None = None,
    ) -> ModelResponse:
        kwargs = {}
        if tools:
            kwargs["tools"] = [_to_groq_tool(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        # stream=True is deliberately omitted to satisfy the ModelProvider
        # interface, which expects one compiled ModelResponse, not chunks.
        response = self._get_client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_completion_tokens=2048,
            top_p=1,
            **kwargs,
        )

        message = response.choices[0].message
        text_content = message.content or ""

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                arguments_dict = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_calls.append(ToolCall(name=tc.function.name, arguments=arguments_dict))

        return ModelResponse(text=text_content, tool_calls=tool_calls)
