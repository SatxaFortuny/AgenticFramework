from core.interfaces import ModelProvider
from core.types import ModelResponse, ToolSpec
from typing import Literal
from pydantic import BaseModel

class FallbackConfig(BaseModel):
    type: Literal["fallback"]
    providers: list['ModelConfigType']  # Recursive typing for sub-providers
    def build(self) -> ModelProvider:
        return FallbackModelProvider([p.build() for p in self.providers])

class FallbackModelProvider(ModelProvider):
    def __init__(self, providers: list[ModelProvider]):
        if not providers:
            raise ValueError("FallbackModelProvider needs at least one provider")
        self.providers = providers

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[ToolSpec] | None = None,
    ) -> ModelResponse:
        last_error: Exception | None = None
        for provider in self.providers:
            try:
                return provider.generate(system_prompt, user_message, tools=tools)
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(
            f"All {len(self.providers)} providers failed. Last error: {last_error}"
        )
