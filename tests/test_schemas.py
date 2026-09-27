"""
Unit tests for the legacy flat-file config/blueprint loaders (load_app_config,
load_blueprint) and env-var expansion. Pure parsing - no live services, safe
to run in CI.

NOTE: the "does the real committed config load" smoke test now lives in
test_app_loader.py (test_real_app_loads_and_matches_todays_behavior), since
the real config moved from a single configs/config.yaml to the
configs/{app}/ directory layout. load_app_config() itself is kept only for
backwards compatibility with any flat config.yaml a caller might still have;
it is not used by the real app anymore.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

import pytest
import yaml

from core.schemas import VectorDBConfig, load_app_config, load_blueprint

SAMPLE_APP_CONFIG = {
    "functionalities": {
        "greeting_bot": {
            "vectordb": [
                {
                    "provider": "chromadb",
                    "collection_name": "general_knowledge",
                    "embedding_provider": "ollama",
                }
            ],
            "tools": [
                {
                    "server_name": "weather_mcp",
                    "url": "${WEATHER_MCP_URL:-http://weather-mcp-service:8000/sse}",
                    "allowed_tools": ["get_weather"],
                }
            ],
            "models": [{"provider": "ollama", "model_name": "llama3.1:8b"}],
        }
    }
}


@pytest.fixture
def sample_config_path(tmp_path):
    """Writes SAMPLE_APP_CONFIG to a temp file and returns its path. Fully
    isolated - doesn't depend on any file in the repo."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(SAMPLE_APP_CONFIG))
    return str(path)


def test_load_app_config(sample_config_path):
    config = load_app_config(sample_config_path)
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


def test_missing_config_raises():
    with pytest.raises(FileNotFoundError):
        load_app_config("does/not/exist.yaml")


def test_env_var_override_for_mcp_url(sample_config_path, monkeypatch):
    """MCP tool URLs use ${VAR:-default}; a local dev env var should
    override that without needing to touch the file."""
    monkeypatch.setenv("WEATHER_MCP_URL", "http://localhost:9000/sse")
    config = load_app_config(sample_config_path)
    assert config.functionalities["greeting_bot"].tools[0].url == "http://localhost:9000/sse"


def test_env_var_falls_back_to_default_when_unset(sample_config_path, monkeypatch):
    monkeypatch.delenv("WEATHER_MCP_URL", raising=False)
    config = load_app_config(sample_config_path)
    assert config.functionalities["greeting_bot"].tools[0].url == "http://weather-mcp-service:8000/sse"


def test_load_blueprint_from_fixture(tmp_path):
    blueprint_data = {
        "name": "test_graph",
        "functionality_ref": "greeting_bot",
        "entry_point": "agent",
        "nodes": [{"id": "agent", "action": "call_llm"}],
        "edges": [],
    }
    path = tmp_path / "blueprint.yaml"
    path.write_text(yaml.dump(blueprint_data))
    blueprint = load_blueprint(str(path))
    assert blueprint.entry_point in {node.id for node in blueprint.nodes}
