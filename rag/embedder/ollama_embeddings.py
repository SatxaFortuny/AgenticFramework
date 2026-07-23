from typing import Literal

import ollama
from pydantic import BaseModel

from core.interfaces import Embedder


class OllamaEmbedderConfig(BaseModel):
    type: Literal["ollama"]
    model: str = "nomic-embed-text"

    def build(self) -> Embedder:
        return OllamaEmbeddingModel(model=self.model)


class OllamaEmbeddingModel(Embedder):
    def __init__(self, model: str = "nomic-embed-text"):
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            ollama.embeddings(model=self.model, prompt=text)["embedding"]
            for text in texts
        ]