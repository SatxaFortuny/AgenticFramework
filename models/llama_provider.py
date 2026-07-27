import json
import ollama

from core.interfaces import ModelProvider
from core.types import ModelResponse, ToolCall, ToolSpec

from typing import Literal
from pydantic import BaseModel

class OllamaConfig(BaseModel):
    type: Literal["ollama"]
    model: str = "llama3.1:8b"
    host: str = "http://localhost:11434"
    
    def build(self) -> ModelProvider:
        return OllamaProvider(model=self.model, host=self.host)

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
    def __init__(self, model: str = "llama3.1:8b", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host
        self._client: ollama.Client | None = None

    def _get_client(self) -> ollama.Client:
        if self._client is None:
            self._client = ollama.Client(host=self.host)
        return self._client

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolSpec] | None = None,
    ) -> ModelResponse:
        kwargs = {}
        if tools:
            kwargs["tools"] = [_to_ollama_tool(t) for t in tools]

        # The ollama client returns a dictionary directly
        response = self._get_client().chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options={
                "temperature": 0.7,
            },
            **kwargs,
        )

        message = response.get("message", {})
        text_content = message.get("content", "")

        tool_calls = []
        
        # Extract tool calls if the model triggered any
        if message.get("tool_calls"):
            for tc in message.get("tool_calls"):
                func = tc.get("function", {})
                
                # The ollama python client usually parses arguments into a dict automatically, 
                # but we handle strings via json.loads just in case.
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                        
                tool_calls.append(ToolCall(name=func.get("name"), arguments=args))

        return ModelResponse(text=text_content, tool_calls=tool_calls)