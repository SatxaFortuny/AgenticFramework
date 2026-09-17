"""
Unit tests for config/blueprint loading. Pure parsing - no live services,
safe to run in CI.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

from core.schemas import load_app_config, load_blueprint

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_load_app_config():
    config = load_app_config(os.path.join(REPO_ROOT, "configs", "config.yaml"))
    assert "greeting_bot" in config.functionalities
    assert "finance_bot" in config.functionalities

    greeting = config.functionalities["greeting_bot"]
    assert greeting.models[0].provider == "ollama"
    assert greeting.tools[0].server_name == "weather_mcp"


def test_load_blueprint():
    blueprint = load_blueprint(os.path.join(REPO_ROOT, "configs", "blueprint.yaml"))
    assert blueprint.entry_point == "agent"
    node_ids = {node.id for node in blueprint.nodes}
    assert {"agent", "tools"} <= node_ids


def test_missing_config_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_app_config("does/not/exist.yaml")
