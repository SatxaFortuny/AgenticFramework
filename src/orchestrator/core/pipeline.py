import asyncio
import hashlib
import json
import logging
import time

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

try:
    # Current langgraph versions.
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # pragma: no cover - older langgraph versions
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver

from core.factory import (
    create_embedder,
    create_model,
    create_vectordb,
    get_filtered_mcp_tools,
)
from core.IModel import State
from core.logging_utils import elapsed_ms, preview
from core.schemas import AppConfig, FunctionalityConfig, GraphBlueprint

logger = logging.getLogger(__name__)

# CHANGED: one process-wide checkpointer, shared across every compiled graph
# (all functionalities, all apps). This is safe because LangGraph namespaces
# saved state by thread_id, not by which graph object called it - so as long
# as api.py always passes the request's conversation_id as thread_id, two
# different functionalities (or apps) never see each other's history even
# though they share this one checkpointer instance.
#
# InMemorySaver does not persist across a restart and does not work across
# multiple orchestrator replicas (same limitation as InMemorySessionStore in
# core/session_store.py, for the same reason: it's an in-process dict).
# Swap for a Postgres/Redis-backed checkpointer when that starts to matter -
# nothing else in this module needs to change, since _build_pipeline is the
# only place that references it.
_checkpointer = InMemorySaver()


# --- Standard Edge Conditions ---
def should_continue(state: State) -> str:
    """Routes the graph to tools if the LLM made a tool call, otherwise ends."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        names = [call["name"] for call in last_message.tool_calls]
        logger.info("Routing: tool call(s) requested %s -> execute_tools", names)
        logger.debug("Tool calls: %s", preview(last_message.tool_calls))
        return "execute_tools"
    logger.info("Routing: no tool calls -> END")
    return END


# --- Node logging/timing wrappers ---
def _timed_node(node_id: str, fn):
    """Wraps a plain (sync) node function with start/finish/failure logs and timing."""

    def wrapper(state: State):
        logger.info("Node '%s' started", node_id)
        start = time.perf_counter()
        try:
            result = fn(state)
        except Exception as exc:
            logger.error(
                "Node '%s' failed after %.0f ms: %s", node_id, elapsed_ms(start), exc
            )
            raise
        logger.info("Node '%s' finished in %.0f ms", node_id, elapsed_ms(start))
        return result

    return wrapper


def _timed_tool_node(node_id: str, tool_node: ToolNode):
    """
    Same as _timed_node but for the ToolNode. It must stay async: MCP tools are
    async-only, so a sync wrapper calling .invoke() would break them.
    """

    async def wrapper(state: State, config: RunnableConfig):
        logger.info("Node '%s' started", node_id)
        start = time.perf_counter()
        try:
            result = await tool_node.ainvoke(state, config)
        except Exception as exc:
            logger.error(
                "Node '%s' failed after %.0f ms: %s", node_id, elapsed_ms(start), exc
            )
            raise
        logger.info("Node '%s' finished in %.0f ms", node_id, elapsed_ms(start))
        if logger.isEnabledFor(logging.DEBUG) and isinstance(result, dict):
            for message in result.get("messages", []):
                logger.debug(
                    "Tool result [%s]: %s",
                    getattr(message, "name", None),
                    preview(message.content),
                )
        return result

    return wrapper


# --- Pipeline cache ---
#
# CHANGED: the cache is now keyed by (app_name, functionality_ref), not just
# functionality_ref. Before multi-app support, two different apps could not
# both define a "greeting_bot" functionality without colliding in this cache
# - one app's compiled graph would silently serve the other app's requests.
# The cache VALUE's hash payload also now includes app_name, so a config
# change in one app never accidentally invalidates another app's cache entry
# purely from a hash coincidence (astronomically unlikely, but the app_name
# key already makes that moot).
_pipeline_cache: dict[tuple[str, str], tuple[str, object]] = {}
_pipeline_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _cache_key(app_name: str, blueprint: GraphBlueprint, tier1_limits: FunctionalityConfig) -> str:
    payload = {
        "app_name": app_name,
        "blueprint": blueprint.model_dump(),
        "tier1_limits": tier1_limits.model_dump(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def clear_pipeline_cache() -> None:
    """Drops all cached pipelines. Useful for tests or an explicit admin reload."""
    _pipeline_cache.clear()


async def get_or_create_pipeline(
    app_name: str, blueprint: GraphBlueprint, app_config: AppConfig
):
    """
    Public entry point for api.py. Returns a cached compiled graph for this
    (app_name, functionality) when the config hasn't changed, otherwise builds
    (and caches) a fresh one. `app_name` disambiguates the cache: it's the
    resolved app's name (from AppBundle.meta.name / discover_apps()), not
    anything the caller invents.
    """
    if blueprint.functionality_ref not in app_config.functionalities:
        raise ValueError(
            f"Security Block: Blueprint requested unauthorized functionality '{blueprint.functionality_ref}'."
        )

    functionality_ref = blueprint.functionality_ref
    tier1_limits = app_config.functionalities[functionality_ref]
    cache_key = _cache_key(app_name, blueprint, tier1_limits)
    entry_key = (app_name, functionality_ref)

    cached = _pipeline_cache.get(entry_key)
    if cached is not None and cached[0] == cache_key:
        logger.debug("Pipeline cache hit for '%s/%s'", app_name, functionality_ref)
        return cached[1]

    lock = _pipeline_locks.setdefault(entry_key, asyncio.Lock())
    async with lock:
        cached = _pipeline_cache.get(entry_key)
        if cached is not None and cached[0] == cache_key:
            logger.debug(
                "Pipeline cache hit for '%s/%s' (post-lock)", app_name, functionality_ref
            )
            return cached[1]

        if cached is not None:
            logger.info(
                "Pipeline cache stale for '%s/%s' (config changed); rebuilding",
                app_name,
                functionality_ref,
            )
        graph = await _build_pipeline(blueprint, tier1_limits)
        _pipeline_cache[entry_key] = (cache_key, graph)
        return graph


# --- The Pipeline Compiler ---
async def _build_pipeline(blueprint: GraphBlueprint, tier1_limits: FunctionalityConfig):
    """
    Instantiates resources and dynamically builds the LangGraph for one
    functionality. Only called on a cache miss - see get_or_create_pipeline().
    """
    build_start = time.perf_counter()
    logger.info(
        "Building pipeline '%s' (functionality=%s)",
        blueprint.name,
        blueprint.functionality_ref,
    )

    # 1. Spin up secure infrastructure
    active_model = create_model(tier1_limits.models[0])
    logger.info(
        "Model: %s/%s",
        tier1_limits.models[0].provider,
        tier1_limits.models[0].model_name,
    )
    safe_tools = await get_filtered_mcp_tools(tier1_limits)

    if safe_tools:
        active_model.bind_tools(safe_tools)
    logger.info(
        "Tools bound to model: %d %s", len(safe_tools), [t.name for t in safe_tools]
    )

    # 2. Create closure functions for the nodes (injecting the active resources)
    def call_llm_node(state: State):
        return active_model.generate(state, context_id="default")

    execute_tools_node = ToolNode(safe_tools)

    def make_retrieve_context_node():
        if not tier1_limits.vectordb:
            raise ValueError(
                f"Blueprint '{blueprint.name}' uses a retrieve_context node but "
                f"functionality '{blueprint.functionality_ref}' has no vectordb configured."
            )
        vectordb_config = tier1_limits.vectordb[0]
        vectordb = create_vectordb(vectordb_config)
        embedder = create_embedder(vectordb_config)

        def retrieve_context_node(state: State):
            last_user_message = state["messages"][-1].content
            query_vector = embedder.embed(content=[last_user_message])[0]
            results = vectordb.query(query=query_vector, n_res=3)
            context = dict(state.get("context", {}))
            context["default"] = results
            return {"context": context}

        return retrieve_context_node

    # 3. Map YAML strings to actual Python execution logic
    ACTION_REGISTRY = {
        "call_llm": call_llm_node,
        "execute_tools": execute_tools_node,
    }
    if any(node.action == "retrieve_context" for node in blueprint.nodes):
        ACTION_REGISTRY["retrieve_context"] = make_retrieve_context_node()

    CONDITION_REGISTRY = {
        "should_continue": should_continue
    }

    # 4. Build the literal Graph Structure based on the Tier 2 Blueprint
    builder = StateGraph(State)

    for node in blueprint.nodes:
        if node.action not in ACTION_REGISTRY:
            raise ValueError(f"Unknown action '{node.action}' in blueprint.")
        action = ACTION_REGISTRY[node.action]
        logger.debug("Adding node '%s' (action=%s)", node.id, node.action)
        if isinstance(action, ToolNode):
            builder.add_node(node.id, _timed_tool_node(node.id, action))
        else:
            builder.add_node(node.id, _timed_node(node.id, action))

    builder.add_edge(START, blueprint.entry_point)

    for edge in blueprint.edges:
        if edge.is_conditional:
            condition_func = CONDITION_REGISTRY.get(edge.condition_action)
            if not condition_func:
                raise ValueError(f"Unknown condition '{edge.condition_action}' in blueprint.")
            builder.add_conditional_edges(
                edge.source,
                condition_func,
                {"execute_tools": edge.target, END: END}
            )
        else:
            builder.add_edge(edge.source, edge.target)

    # 5. Compile with the shared checkpointer so LangGraph accumulates
    # state["messages"] per thread_id (== conversation_id) across calls,
    # instead of every ainvoke() only seeing the single latest message.
    graph = builder.compile(checkpointer=_checkpointer)
    logger.info(
        "Pipeline '%s' built in %.0f ms (%d nodes, %d edges)",
        blueprint.name,
        elapsed_ms(build_start),
        len(blueprint.nodes),
        len(blueprint.edges),
    )
    return graph
