"""
Unit tests for core/factory.py's provider registries. These check the
"swappable component" contract - unknown providers fail loudly, known
providers resolve to the right class - without needing live services.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

import pytest
from core.factory import (
    create_model,
    create_vectordb,
    create_embedder,
    MODEL_REGISTRY,
    VECTORDB_REGISTRY,
    EMBEDDING_REGISTRY,
)
from core.schemas import ModelsConfig, VectorDBConfig


def test_known_providers_registered():
    assert "ollama" in MODEL_REGISTRY
    assert "groq" in MODEL_REGISTRY
    assert "chromadb" in VECTORDB_REGISTRY
    assert "ollama" in EMBEDDING_REGISTRY


def test_create_model_unsupported_provider_raises():
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_model(ModelsConfig(provider="does-not-exist", model_name="x"))


def test_create_vectordb_unsupported_provider_raises():
    with pytest.raises(ValueError, match="Unsupported VectorDB provider"):
        create_vectordb(VectorDBConfig(provider="does-not-exist", collection_name="x"))


def test_create_embedder_unsupported_provider_raises():
    with pytest.raises(ValueError, match="No embedding backend registered"):
        create_embedder(
            VectorDBConfig(
                provider="chromadb",
                collection_name="x",
                embedding_provider="does-not-exist",
            )
        )


def test_vectordb_and_embedding_provider_are_independent():
    """
    The whole point of the split: a vectordb provider and its embedding
    provider are looked up from separate config fields/registries, so they
    can vary independently (e.g. chromadb + ollama today, chromadb + a
    future cloud embedder tomorrow, without touching VECTORDB_REGISTRY).
    """
    config = VectorDBConfig(
        provider="chromadb",
        collection_name="x",
        embedding_provider="ollama",
    )
    db_class = VECTORDB_REGISTRY[config.provider]
    embedder_class = EMBEDDING_REGISTRY[config.embedding_provider]
    assert db_class is not embedder_class
