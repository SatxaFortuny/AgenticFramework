"""
Unit tests for the new configs/{app}/ directory loader (core.schemas.load_app).
Pure parsing - no live services, safe to run in CI.

Covers: the real committed app loads and matches today's effective behavior,
app-level model defaults are inherited when a functionality omits `models`,
and the load-time validation errors this batch adds (missing files, dangling
blueprint edges/entry_point, retrieve_context without a vectordb, a
functionality with no usable model at all).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

import pytest
import yaml

from core.schemas import load_app

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
REAL_APP_DIR = os.path.join(REPO_ROOT, "configs", "greeting_finance_app")


def _write_app(tmp_path, app_yaml, functionalities: dict, blueprints: dict):
    (tmp_path / "functionalities").mkdir()
    (tmp_path / "blueprints").mkdir()
    (tmp_path / "app.yaml").write_text(yaml.dump(app_yaml))
    for name, content in functionalities.items():
        (tmp_path / "functionalities" / f"{name}.yaml").write_text(yaml.dump(content))
    for name, content in blueprints.items():
        (tmp_path / "blueprints" / f"{name}.yaml").write_text(yaml.dump(content))
    return str(tmp_path)


def _minimal_blueprint(functionality_ref):
    return {
        "name": f"{functionality_ref}_graph",
        "functionality_ref": functionality_ref,
        "entry_point": "agent",
        "nodes": [{"id": "agent", "action": "call_llm"}],
        "edges": [],
    }


# --- Smoke test against the real, committed app ---

def test_real_app_loads_and_matches_todays_behavior():
    bundle = load_app(REAL_APP_DIR)
    assert bundle.meta.name == "greeting_finance_app"
    assert set(bundle.app_config.functionalities) == {"greeting_bot", "finance_bot"}

    greeting = bundle.app_config.functionalities["greeting_bot"]
    assert greeting.models[0].provider == "groq"
    assert greeting.models[0].model_name == "openai/gpt-oss-20b"

    # finance_bot omits `models` in its own file - this asserts the inherited
    # app default resolves to the same effective value the old flat
    # config.yaml had hardcoded per-functionality.
    finance = bundle.app_config.functionalities["finance_bot"]
    assert finance.models[0].provider == "ollama"
    assert finance.models[0].model_name == "llama3.1:8b"

    assert set(bundle.blueprints) == {"greeting_bot", "finance_bot"}
    assert bundle.blueprints["finance_bot"].entry_point == "agent"


# --- Inheritance ---

def test_functionality_without_models_inherits_app_default(tmp_path):
    app_dir = _write_app(
        tmp_path,
        app_yaml={
            "name": "test_app",
            "functionalities": ["bot"],
            "defaults": {"model": {"provider": "ollama", "model_name": "llama3.1:8b"}},
        },
        functionalities={"bot": {}},
        blueprints={"bot": _minimal_blueprint("bot")},
    )
    bundle = load_app(app_dir)
    assert bundle.app_config.functionalities["bot"].models[0].provider == "ollama"


def test_functionality_with_its_own_models_overrides_app_default(tmp_path):
    app_dir = _write_app(
        tmp_path,
        app_yaml={
            "name": "test_app",
            "functionalities": ["bot"],
            "defaults": {"model": {"provider": "ollama", "model_name": "llama3.1:8b"}},
        },
        functionalities={"bot": {"models": [{"provider": "groq", "model_name": "x"}]}},
        blueprints={"bot": _minimal_blueprint("bot")},
    )
    bundle = load_app(app_dir)
    assert bundle.app_config.functionalities["bot"].models[0].provider == "groq"


def test_no_models_and_no_app_default_raises(tmp_path):
    app_dir = _write_app(
        tmp_path,
        app_yaml={"name": "test_app", "functionalities": ["bot"]},
        functionalities={"bot": {}},
        blueprints={"bot": _minimal_blueprint("bot")},
    )
    with pytest.raises(ValueError, match="no models configured"):
        load_app(app_dir)


# --- Load-time validation ---

def test_missing_functionality_file_raises(tmp_path):
    app_dir = _write_app(
        tmp_path,
        app_yaml={"name": "test_app", "functionalities": ["bot"]},
        functionalities={},  # bot.yaml never written
        blueprints={"bot": _minimal_blueprint("bot")},
    )
    with pytest.raises(FileNotFoundError):
        load_app(app_dir)


def test_blueprint_entry_point_not_a_node_raises(tmp_path):
    bad_blueprint = _minimal_blueprint("bot")
    bad_blueprint["entry_point"] = "does_not_exist"
    app_dir = _write_app(
        tmp_path,
        app_yaml={
            "name": "test_app",
            "functionalities": ["bot"],
            "defaults": {"model": {"provider": "ollama", "model_name": "llama3.1:8b"}},
        },
        functionalities={"bot": {}},
        blueprints={"bot": bad_blueprint},
    )
    with pytest.raises(ValueError, match="entry_point"):
        load_app(app_dir)


def test_blueprint_dangling_edge_raises(tmp_path):
    bad_blueprint = _minimal_blueprint("bot")
    bad_blueprint["edges"] = [{"source": "agent", "target": "ghost_node"}]
    app_dir = _write_app(
        tmp_path,
        app_yaml={
            "name": "test_app",
            "functionalities": ["bot"],
            "defaults": {"model": {"provider": "ollama", "model_name": "llama3.1:8b"}},
        },
        functionalities={"bot": {}},
        blueprints={"bot": bad_blueprint},
    )
    with pytest.raises(ValueError, match="ghost_node"):
        load_app(app_dir)


def test_retrieve_context_without_vectordb_raises(tmp_path):
    blueprint = _minimal_blueprint("bot")
    blueprint["nodes"] = [{"id": "agent", "action": "retrieve_context"}]
    app_dir = _write_app(
        tmp_path,
        app_yaml={
            "name": "test_app",
            "functionalities": ["bot"],
            "defaults": {"model": {"provider": "ollama", "model_name": "llama3.1:8b"}},
        },
        functionalities={"bot": {}},  # no vectordb
        blueprints={"bot": blueprint},
    )
    with pytest.raises(ValueError, match="retrieve_context"):
        load_app(app_dir)


def test_blueprint_functionality_ref_mismatch_raises(tmp_path):
    mismatched = _minimal_blueprint("some_other_name")
    app_dir = _write_app(
        tmp_path,
        app_yaml={
            "name": "test_app",
            "functionalities": ["bot"],
            "defaults": {"model": {"provider": "ollama", "model_name": "llama3.1:8b"}},
        },
        functionalities={"bot": {}},
        blueprints={"bot": mismatched},
    )
    with pytest.raises(ValueError, match="functionality_ref"):
        load_app(app_dir)
