from IVectorDB import IVectorDB
from IEmbeddingModel import IEmbeddingModel
from EmbedModelOllama import EmbedModelOllama
import chromadb

"""
Here I made an important structural decision. By standard chromadb has its internal chunking model. If the user wants to put his embedding model
he has two options. Add the model inside the db or process the chunks before the load.
I choose the second option because my main objective is swappability.

"""

class ChromaDB(IVectorDB):
    
    def __init__(self, collection_name: str):
        # I need to use persistent client or else it's saved in-memory'
        db_path="chroma_data/" + collection_name
        self.chroma_client = chromadb.PersistentClient(path=db_path)
        self.collection = self.chroma_client.get_or_create_collection(name=collection_name)
    
    def load(self, ids: list[str], contents: list[str], vectors: list[list[float]]):
        self.collection.add(ids=ids, documents=contents, embeddings=vectors)
        print(f"Loaded documents with ids {ids}")
        
    def query(self, query: list[float], n_res: int) -> list[str]:
        results = self.collection.query(query_embeddings=[query], n_results=n_res)
        if results and "documents" in results and results["documents"]:
            return results["documents"][-1]
        return []
    
# This is a testing part

db = ChromaDB(collection_name="test")
embedder = EmbedModelOllama(model_name="nomic-embed-text:latest")

DOCS = [
    {"id": "banana", "content": "Bananas are yellow"},
    {"id": "pear", "content": "Pears are green"},
    {"id": "redapple", "content": "Apples are red"},
    {"id": "greenapple", "content": "Apples are green"},
    {"id": "kiwi", "content": "Kiwis are brown and green"}
]

ids = [doc["id"] for doc in DOCS]
contents = [doc["content"] for doc in DOCS]

vectors = embedder.embed(content=contents) 
db.load(ids=ids, contents=contents, vectors=vectors)
question = "Are apples green?"
print(f"Question: {question}")


question_vector = embedder.embed(content=[question])[0] 
results = db.query(query=question_vector, n_res=3)

print(f"Results found: {results}")