import logging
import os
import time

import chromadb

from core.IVectorDB import IVectorDB
from core.logging_utils import elapsed_ms, preview

logger = logging.getLogger(__name__)

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
        self.collection_name = collection_name

        start = time.perf_counter()
        try:
            # Connect over the internal Kubernetes network instead of local files
            self.chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
            self.collection = self.chroma_client.get_or_create_collection(
                name=collection_name
            )
        except Exception as exc:
            logger.error(
                "ChromaDB connection failed at %s:%s (collection=%s) after %.0f ms: %s",
                chroma_host,
                chroma_port,
                collection_name,
                elapsed_ms(start),
                exc,
            )
            raise
        logger.info(
            "Connected to ChromaDB at %s:%s, collection '%s' ready (%.0f ms)",
            chroma_host,
            chroma_port,
            collection_name,
            elapsed_ms(start),
        )

    def load(self, ids: list[str], contents: list[str], vectors: list[list[float]]):
        start = time.perf_counter()
        self.collection.add(ids=ids, documents=contents, embeddings=vectors)
        logger.info(
            "Loaded %d document(s) into '%s' in %.0f ms",
            len(ids),
            self.collection_name,
            elapsed_ms(start),
        )

    def query(self, query: list[float], n_res: int) -> list[str]:
        start = time.perf_counter()
        results = self.collection.query(query_embeddings=[query], n_results=n_res)
        documents = []
        if results and "documents" in results and results["documents"]:
            documents = results["documents"][-1]
        logger.info(
            "Queried '%s' (n_res=%d): %d result(s) in %.0f ms",
            self.collection_name,
            n_res,
            len(documents),
            elapsed_ms(start),
        )
        logger.debug("Query results: %s", preview(documents))
        return documents
