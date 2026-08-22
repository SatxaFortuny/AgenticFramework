from abc import ABC, abstractmethod

class IEmbeddingModel(ABC):
    
    @abstractmethod
    def embed(self, content: list[str]) -> list[list[float]]:
        # The embedding model returns various floats per chunk. Also it parallelizes the queries. That's why the double list.
        pass