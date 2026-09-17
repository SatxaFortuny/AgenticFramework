import ollama

from core.IEmbeddingModel import IEmbeddingModel


class EmbedModelOllama(IEmbeddingModel):
    
    def __init__(self, model_name: str):
        self.model = model_name
    
    def embed(self, content: list[str]) -> list[list[float]]:
        return ollama.embed(model=self.model, input=content)["embeddings"]
