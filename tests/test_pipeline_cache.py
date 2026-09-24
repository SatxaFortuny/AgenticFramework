"""
Unit tests for the pipeline cache in core/pipeline.py. These stub out
_build_pipeline entirely (no LLM/MCP/vectordb calls), so they only check the
caching contract: same config -> cache hit (no rebuild), changed config ->
rebuild, and the functionality_ref allowlist check still happens up front.

Note: written with asyncio.run() rather than pytest-asyncio, since the
project doesn't currently depend on that plugin - avoids adding a new
dependency just for these three tests.
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
    ModelsConfig,
    NodeDef,
    EdgeDef,
)


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
                models=[ModelsConfig(provider="ollama", model_name=model_name)],
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
        lambda bp, cfg: _fake_build_pipeline(bp, cfg, build_calls),
    )

    async def run():
        blueprint = make_blueprint()
        app_config = make_app_config()
        graph1 = await get_or_create_pipeline(blueprint, app_config)
        graph2 = await get_or_create_pipeline(blueprint, app_config)
        return graph1, graph2

    graph1, graph2 = asyncio.run(run())

    assert graph1 is graph2
    assert build_calls == ["llama3.1:8b"]  # only built once


def test_config_change_invalidates_cache(monkeypatch):
    build_calls = []
    monkeypatch.setattr(
        pipeline_module,
        "_build_pipeline",
        lambda bp, cfg: _fake_build_pipeline(bp, cfg, build_calls),
    )

    async def run():
        blueprint = make_blueprint()
        graph1 = await get_or_create_pipeline(blueprint, make_app_config("llama3.1:8b"))
        graph2 = await get_or_create_pipeline(blueprint, make_app_config("llama3.1:70b"))
        return graph1, graph2

    graph1, graph2 = asyncio.run(run())

    assert graph1 is not graph2
    assert build_calls == ["llama3.1:8b", "llama3.1:70b"]


def test_unauthorized_functionality_ref_raises_without_building(monkeypatch):
    build_calls = []
    monkeypatch.setattr(
        pipeline_module,
        "_build_pipeline",
        lambda bp, cfg: _fake_build_pipeline(bp, cfg, build_calls),
    )

    blueprint = GraphBlueprint(
        name="test_graph",
        functionality_ref="not_a_real_functionality",
        entry_point="agent",
        nodes=[NodeDef(id="agent", action="call_llm")],
        edges=[],
    )

    async def run():
        await get_or_create_pipeline(blueprint, make_app_config())

    with pytest.raises(ValueError, match="Security Block"):
        asyncio.run(run())

    assert build_calls == []
