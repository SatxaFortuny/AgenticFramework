from google import genai
from google.genai import types

from core.interfaces import ModelProvider
from core.types import ModelResponse, ToolCall, ToolSpec

from typing import Literal
from pydantic import BaseModel

class GeminiConfig(BaseModel):
    type: Literal["gemini"]
    model: str = "models/gemini-3.5-flash"
    def build(self) -> ModelProvider:
        return GeminiProvider(model=self.model)

def _to_gemini_tool(spec: ToolSpec) -> types.Tool:
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=spec.name,
                description=spec.description,
                parameters=spec.parameters,
            )
        ]
    )


class GeminiProvider(ModelProvider):
    def __init__(self, model: str = "models/gemini-3.5-flash"):
        self.model = model if model.startswith("models/") else f"models/{model}"
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client()
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolSpec] | None = None,
    ) -> ModelResponse:
        config_kwargs = {
            "system_instruction": system_prompt,
            "max_output_tokens": 65536,
            "thinking_config": types.ThinkingConfig(thinking_level="MEDIUM"),
        }

        if tools:
            config_kwargs["tools"] = [_to_gemini_tool(t) for t in tools]

        config = types.GenerateContentConfig(**config_kwargs)

        response = self._get_client().models.generate_content(
            model=self.model,
            contents=user_message,
            config=config,
        )

        text_content = response.text or ""

        tool_calls = []
        if response.function_calls:
            for fc in response.function_calls:
                arguments_dict = dict(fc.args) if fc.args else {}
                tool_calls.append(ToolCall(name=fc.name, arguments=arguments_dict))

        return ModelResponse(text=text_content, tool_calls=tool_calls)
