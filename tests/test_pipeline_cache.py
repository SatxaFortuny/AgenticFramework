"""
Unit tests for the pipeline cache in core/pipeline.py. These stub out
_build_pipeline entirely (no LLM/MCP/vectordb calls), so they only check the
caching contract: same (app, config) -> cache hit, changed config -> rebuild,
two apps with the same functionality name don't collide, and the
functionality_ref allowlist check still happens up front.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

import pytest

import core.pipeline as pipeline_module
from core.pipeline import get_or_create_pipeline, clear_pipeline_cache
from core.schemas import (
    AppConfig,
    FunctionalityConfig,
    GraphBlueprint,
    ModelConfig,
    NodeDef,
    EdgeDef,
)


# Stand-in for the checkpointer api.py injects at startup. These tests stub
# _build_pipeline out, so it only needs to be passed through, never used.
CHECKPOINTER = object()


async def _get(app_name, blueprint, app_config):
    return await get_or_create_pipeline(app_name, blueprint, app_config, CHECKPOINTER)


def make_blueprint() -> GraphBlueprint:
    return GraphBlueprint(
        name="test_graph",
        functionality_ref="greeting_bot",
        entry_point="agent",
        nodes=[NodeDef(id="agent", action="call_llm")],
        edges=[],
    )


def make_app_config(model_name: str = "llama3.1:8b") -> AppConfig:
    return AppConfig(
        functionalities={
            "greeting_bot": FunctionalityConfig(
                models=[ModelConfig(provider="ollama", model_name=model_name)],
            )
        }
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_pipeline_cache()
    pipeline_module._pipeline_locks.clear()
    yield
    clear_pipeline_cache()
    pipeline_module._pipeline_locks.clear()


async def _fake_build_pipeline(blueprint, tier1_limits, build_calls):
    build_calls.append(tier1_limits.models[0].model_name)
    return object()


def test_second_call_is_a_cache_hit(monkeypatch):
    build_calls = []
    monkeypatch.setattr(
        pipeline_module,
        "_build_pipeline",
        lambda bp, cfg, cp: _fake_build_pipeline(bp, cfg, build_calls),
    )

    async def run():
        blueprint = make_blueprint()
        app_config = make_app_config()
        graph1 = await _get("greeting_finance_app", blueprint, app_config)
        graph2 = await _get("greeting_finance_app", blueprint, app_config)
        return graph1, graph2

    graph1, graph2 = asyncio.run(run())

    assert graph1 is graph2
    assert build_calls == ["llama3.1:8b"]  # only built once


def test_config_change_invalidates_cache(monkeypatch):
    build_calls = []
    monkeypatch.setattr(
        pipeline_module,
        "_build_pipeline",
        lambda bp, cfg, cp: _fake_build_pipeline(bp, cfg, build_calls),
    )

    async def run():
        blueprint = make_blueprint()
        graph1 = await _get(
            "greeting_finance_app", blueprint, make_app_config("llama3.1:8b")
        )
        graph2 = await _get(
            "greeting_finance_app", blueprint, make_app_config("llama3.1:70b")
        )
        return graph1, graph2

    graph1, graph2 = asyncio.run(run())

    assert graph1 is not graph2
    assert build_calls == ["llama3.1:8b", "llama3.1:70b"]


def test_different_apps_with_same_functionality_name_do_not_collide(monkeypatch):
    """The exact bug the app_name cache key exists to prevent: two apps that
    both happen to define a functionality called 'greeting_bot', with
    different configs, must not share a cache entry."""
    build_calls = []
    monkeypatch.setattr(
        pipeline_module,
        "_build_pipeline",
        lambda bp, cfg, cp: _fake_build_pipeline(bp, cfg, build_calls),
    )

    async def run():
        blueprint = make_blueprint()
        graph_app1 = await _get(
            "app_one", blueprint, make_app_config("llama3.1:8b")
        )
        graph_app2 = await _get(
            "app_two", blueprint, make_app_config("llama3.1:8b")
        )
        # Same app again - should be a cache hit, not a third build.
        graph_app1_again = await _get(
            "app_one", blueprint, make_app_config("llama3.1:8b")
        )
        return graph_app1, graph_app2, graph_app1_again

    graph_app1, graph_app2, graph_app1_again = asyncio.run(run())

    assert graph_app1 is not graph_app2
    assert graph_app1 is graph_app1_again
    assert build_calls == ["llama3.1:8b", "llama3.1:8b"]  # built once per app, not per call


def test_unauthorized_functionality_ref_raises_without_building(monkeypatch):
    build_calls = []
    monkeypatch.setattr(
        pipeline_module,
        "_build_pipeline",
        lambda bp, cfg, cp: _fake_build_pipeline(bp, cfg, build_calls),
    )

    blueprint = GraphBlueprint(
        name="test_graph",
        functionality_ref="not_a_real_functionality",
        entry_point="agent",
        nodes=[NodeDef(id="agent", action="call_llm")],
        edges=[],
    )

    async def run():
        await _get("greeting_finance_app", blueprint, make_app_config())

    with pytest.raises(ValueError, match="Security Block"):
        asyncio.run(run())

    assert build_calls == []


def test_checkpointer_is_forwarded_to_the_build_step(monkeypatch):
    """The checkpointer api.py creates at startup must be the one the graph is
    compiled with - otherwise history silently goes to the wrong place."""
    received = []

    async def fake_build(blueprint, tier1_limits, checkpointer):
        received.append(checkpointer)
        return object()

    monkeypatch.setattr(pipeline_module, "_build_pipeline", fake_build)
    sentinel = object()
    asyncio.run(
        get_or_create_pipeline("greeting_finance_app", make_blueprint(), make_app_config(), sentinel)
    )
    assert received == [sentinel]
