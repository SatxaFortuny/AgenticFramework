from abc import ABC, abstractmethod


class IVectorDB(ABC):
    """In order to maintain swappability, we must declare a contract between this component and the others. By creating a vector database interface, we make all the providers have a common ground in order to maintain transparency."""
    
    @abstractmethod
    def load(self, ids: list[str], contents: list[str], vectors: list[list[float]]):
        """load takes a set of data and stores it in the vectordb. It has three main arguments, and all three are synchronized by their index. ids relates the vector to its original document. contents has the original chunk. vectors is the embeded chunk, which is a list of floats."""
        
    @abstractmethod
    def query(self, query: list[float], n_res: int) -> list[str]:
        """query takes a set of data and it looks for the most similar stored embeddings. query is the list of chunks, meaning that it only can search similarities for one chunk per query (one chunk of the original text). Here, we take the chunks already embedded in order to maintain swappability. n_res is the number of top n results that the function should return."""
