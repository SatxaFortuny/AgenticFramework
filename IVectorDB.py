from abc import ABC, abstractmethod

class IVectorDB(ABC):
    
    @abstractmethod
    def load(self, ids: list[str], contents: list[str], vectors: list[list[float]]):
        pass
        
    @abstractmethod
    def query(self, query: list[float], n_res: int) -> list[str]:
        pass