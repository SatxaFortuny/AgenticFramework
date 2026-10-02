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
from core.schemas import EmbeddingConfig, ModelConfig, VectorDBConfig

def test_known_providers_registered():
    assert "ollama" in MODEL_REGISTRY
    assert "groq" in MODEL_REGISTRY
    assert "chromadb" in VECTORDB_REGISTRY
    assert "ollama" in EMBEDDING_REGISTRY


def test_create_model_unsupported_provider_raises():
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_model(ModelConfig(provider="does-not-exist", model_name="x"))


def test_create_embedder_unsupported_provider_raises():
    with pytest.raises(ValueError, match="No embedding backend registered"):
        create_embedder(EmbeddingConfig(provider="does-not-exist", model_name="x"))


def test_vectordb_and_embedding_provider_are_independent():
    """
    The vectordb and the embedder are configured separately
    (VectorDBConfig vs EmbeddingConfig) and looked up in separate
    registries, so each can vary without touching the other.
    """
    db_config = VectorDBConfig(provider="chromadb", collection_name="x")
    embed_config = EmbeddingConfig(provider="ollama", model_name="nomic-embed-text")

    db_class = VECTORDB_REGISTRY[db_config.provider]
    embedder_class = EMBEDDING_REGISTRY[embed_config.provider]
    assert db_class is not embedder_class
