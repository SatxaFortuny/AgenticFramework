from abc import ABC, abstractmethod


class IEmbeddingModel(ABC):
    """In order to maintain swappability, we must declare a contract between this component and the others. By creating an embedding model interface, we make all the providers have a common ground in order to maintain transparency."""

    @abstractmethod
    def embed(self, content: list[str]) -> list[list[float]]:
        """The embedding model returns a fixed amount of floats per chunk, so each chunk is a list. In a sentence, we have various chunks so we end up with a list of lists, where each list is the embeded chunk."""
