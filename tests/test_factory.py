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
    assert "chromadb" in VECTORDB_REGISTRY
    assert "chromadb" in EMBEDDING_REGISTRY


def test_create_model_unsupported_provider_raises():
    with pytest.raises(ValueError, match="Unsupported model provider"):
        create_model(ModelsConfig(provider="does-not-exist", model_name="x"))


def test_create_vectordb_unsupported_provider_raises():
    with pytest.raises(ValueError, match="Unsupported VectorDB provider"):
        create_vectordb(VectorDBConfig(provider="does-not-exist", collection_name="x"))


def test_create_embedder_unsupported_provider_raises():
    with pytest.raises(ValueError, match="No embedding backend registered"):
        create_embedder(VectorDBConfig(provider="does-not-exist", collection_name="x"))
