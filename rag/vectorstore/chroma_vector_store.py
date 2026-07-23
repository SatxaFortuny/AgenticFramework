import uuid
from typing import Literal

import chromadb
from pydantic import BaseModel

from core.interfaces import Document, VectorStore


class ChromaVectorConfig(BaseModel):
    type: Literal["chroma"]
    collection_name: str = "portfolio_collection"
    persist_directory: str = "./chroma_db"

    def build(self) -> VectorStore:
        return ChromaVectorStore(
            collection_name=self.collection_name,
            persist_directory=self.persist_directory,
        )


class ChromaVectorStore(VectorStore):
    def __init__(self, collection_name: str = "portfolio_collection", persist_directory: str = "./chroma_db"):
        # Initialize a persistent client so your data saves to the local disk
        self.client = chromadb.PersistentClient(path=persist_directory)

        # Retrieves the collection if it exists, otherwise creates a new one
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def add(self, documents: list[Document], embeddings: list[list[float]]) -> None:
        if not documents:
            return

        # ChromaDB requires a unique string ID for every record
        ids = [str(uuid.uuid4()) for _ in documents]

        texts = [doc.content for doc in documents]
        metadatas = [doc.metadata for doc in documents]

        # Add the records to the collection
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[Document]:
        # Query the collection using the raw embedding directly
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        retrieved_docs = []

        # Chroma returns results as lists of lists because it supports batch querying
        if results and results.get("documents") and results["documents"][0]:
            texts = results["documents"][0]
            metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(texts)

            for text, metadata in zip(texts, metadatas):
                retrieved_docs.append(Document(content=text, metadata=metadata))

        return retrieved_docs