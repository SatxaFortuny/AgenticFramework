"""
Unit tests for config/blueprint loading. Pure parsing - no live services,
safe to run in CI.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

from core.schemas import load_app_config, load_blueprint, VectorDBConfig

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_load_app_config():
    config = load_app_config(os.path.join(REPO_ROOT, "configs", "config.yaml"))
    assert "greeting_bot" in config.functionalities
    assert "finance_bot" in config.functionalities

    greeting = config.functionalities["greeting_bot"]
    assert greeting.models[0].provider == "ollama"
    assert greeting.tools[0].server_name == "weather_mcp"
    assert greeting.vectordb[0].embedding_provider == "ollama"


def test_vectordb_embedding_provider_defaults_to_ollama():
    """A config that omits embedding_provider (pre-split configs) should
    still work: it falls back to 'ollama', matching the old behaviour where
    the embedding backend was implicitly tied to the vectordb provider."""
    config = VectorDBConfig(provider="chromadb", collection_name="x")
    assert config.embedding_provider == "ollama"


def test_load_blueprint():
    blueprint = load_blueprint(os.path.join(REPO_ROOT, "configs", "blueprint.yaml"))
    assert blueprint.entry_point == "agent"
    node_ids = {node.id for node in blueprint.nodes}
    assert {"agent", "tools"} <= node_ids


def test_missing_config_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_app_config("does/not/exist.yaml")


def test_env_var_override_for_mcp_url(monkeypatch):
    """The committed config.yaml points MCP tool URLs at k8s Service DNS
    names via ${VAR:-default}; a local dev env var should override that
    without needing to touch the file."""
    monkeypatch.setenv("WEATHER_MCP_URL", "http://localhost:9000/sse")
    config = load_app_config(os.path.join(REPO_ROOT, "configs", "config.yaml"))
    assert config.functionalities["greeting_bot"].tools[0].url == "http://localhost:9000/sse"


def test_env_var_falls_back_to_default_when_unset(monkeypatch):
    monkeypatch.delenv("WEATHER_MCP_URL", raising=False)
    config = load_app_config(os.path.join(REPO_ROOT, "configs", "config.yaml"))
    assert config.functionalities["greeting_bot"].tools[0].url == "http://weather-mcp-service:8000/sse"
