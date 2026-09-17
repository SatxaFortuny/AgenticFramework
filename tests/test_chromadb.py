"""
Integration test for ChromaDB + EmbedModelOllama.
Requires a reachable ChromaDB instance (CHROMA_HOST/CHROMA_PORT) and Ollama
running the embedding model locally — run manually, not in unit CI, unless
those services are available in the test environment.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

from infrastructure.ChromaDB import ChromaDB
from infrastructure.EmbedModelOllama import EmbedModelOllama

import pytest

pytestmark = pytest.mark.integration

DOCS = [
    {"id": "banana", "content": "Bananas are yellow"},
    {"id": "pear", "content": "Pears are green"},
    {"id": "redapple", "content": "Apples are red"},
    {"id": "greenapple", "content": "Apples are green"},
    {"id": "kiwi", "content": "Kiwis are brown and green"},
]


def test_chromadb_load_and_query():
    db = ChromaDB(collection_name="test")
    embedder = EmbedModelOllama(model_name="nomic-embed-text:latest")

    ids = [doc["id"] for doc in DOCS]
    contents = [doc["content"] for doc in DOCS]

    vectors = embedder.embed(content=contents)
    db.load(ids=ids, contents=contents, vectors=vectors)

    question = "Are apples green?"
    question_vector = embedder.embed(content=[question])[0]
    results = db.query(query=question_vector, n_res=3)

    assert results, "Expected at least one result back from ChromaDB"
    assert any("apple" in r.lower() for r in results)
