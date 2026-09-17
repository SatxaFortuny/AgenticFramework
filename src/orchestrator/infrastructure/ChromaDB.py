from core.IVectorDB import IVectorDB
import chromadb
import os

"""
Structural note: by default chromadb has its own internal chunking/embedding
model. Instead of letting the vector store own that, embeddings are computed
externally (see EmbedModelOllama) and passed in already-chunked. This keeps
the embedding backend swappable independently of the vector store backend.
"""

class ChromaDB(IVectorDB):

    def __init__(self, collection_name: str):
        chroma_host = os.getenv("CHROMA_HOST", "chromadb-service")
        chroma_port = os.getenv("CHROMA_PORT", "8000")

        # Connect over the internal Kubernetes network instead of local files
        self.chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        self.collection = self.chroma_client.get_or_create_collection(name=collection_name)

    def load(self, ids: list[str], contents: list[str], vectors: list[list[float]]):
        self.collection.add(ids=ids, documents=contents, embeddings=vectors)

    def query(self, query: list[float], n_res: int) -> list[str]:
        results = self.collection.query(query_embeddings=[query], n_results=n_res)
        if results and "documents" in results and results["documents"]:
            return results["documents"][-1]
        return []
