from core.interfaces import Chunker, EmbeddingModel, Reranker, Retriever, VectorStore
from core.types import ScoredChunk

from typing import Literal
from pydantic import BaseModel

from typing import Literal
from pydantic import BaseModel

from docs import DOCUMENTS

class DenseRetrieverConfig(BaseModel):
    type: Literal["dense"]
    embedding_model: str = "nomic-embed-text"
    def build(self) -> Retriever:
        return DenseRetriever(
            documents=DOCUMENTS,
            chunker=ParagraphChunker(),
            embedding_model=OllamaEmbeddingModel(model=self.embedding_model),
            vector_store=InMemoryVectorStore(),
        )

class DenseRetriever(Retriever):
    def __init__(
        self,
        documents: list[dict],
        chunker: Chunker,
        embedding_model: EmbeddingModel,
        vector_store: VectorStore,
        reranker: Reranker | None = None,
    ):
        self.embedding_model = embedding_model
        self.vector_store = vector_store
        self.reranker = reranker

        # Ingestion: chunk every document, embed all chunks, index them.
        all_chunks = [
            chunk for document in documents for chunk in chunker.chunk(document)
        ]
        vectors = embedding_model.embed([c.text for c in all_chunks])
        self.vector_store.upsert(all_chunks, vectors)

    def retrieve(self, query: str, k: int = 2) -> list[ScoredChunk]:
        [query_vector] = self.embedding_model.embed([query])
        results = self.vector_store.query(query_vector, k=k)
        if self.reranker is not None:
            results = self.reranker.rerank(query, results)
        return results
