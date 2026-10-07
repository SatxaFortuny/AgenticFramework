import asyncio
import hashlib
import json
import logging
import time

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

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

# The checkpointer is NOT created here anymore: api.py builds it at startup
# (Postgres-backed when configured - see core/persistence.py) and passes it
# into get_or_create_pipeline(). One instance is shared by every compiled
# graph (all functionalities, all apps). That's safe because LangGraph
# namespaces saved state by thread_id, not by which graph object wrote it -
# api.py always passes the request's conversation_id as thread_id, so two
# functionalities (or apps) never see each other's history.


# --- Standard Edge Conditions ---
def should_continue(state: State) -> str:
    """Routes the graph to tools if the LLM made a tool call, otherwise ends."""
    last_message = state["messages"][-1]
    # hasattr first: a HumanMessage has no tool_calls attribute at all, and
    # Python short-circuits `and`, so the second check never runs on a
    # message type that doesn't have the attribute.
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        names = [call["name"] for call in last_message.tool_calls]
        logger.info("Routing: tool call(s) requested %s -> execute_tools", names)
        logger.debug("Tool calls: %s", preview(last_message.tool_calls))
        # NOTE: this string has to match the "execute_tools" key hardcoded
        # into the conditional-edges mapping below. If we ever add a second
        # condition function, it would be stuck returning this same literal
        # or END - there's no per-edge way yet to declare a different
        # expected return value (would need a condition_value-style field on
        # EdgeDef in schemas.py, and this mapping built from it instead).
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
            # Log before re-raising - the exception still propagates and
            # fails the graph run, this only makes sure it's visible in the
            # logs with timing, not just wherever catches it upstream.
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
        # Debug-only: what each tool actually returned, truncated via
        # preview() so one large tool result doesn't flood the log. Gated on
        # isEnabledFor so none of this - the loop, the getattr, the preview
        # calls - runs at all when DEBUG logging is off.
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
# Building a pipeline does real I/O (MCP tool discovery, constructing model/
# vectordb/embedder clients), so it's cached per (app_name, functionality)
# instead of rebuilt on every request.
#
# Keyed by (app_name, functionality_ref), not just functionality_ref: two
# different apps could each define their own "greeting_bot" functionality,
# and without app_name in the key, one app's compiled graph would silently
# serve the other app's requests. The cache VALUE's hash (_cache_key, below)
# also includes app_name, for the same reason.
_pipeline_cache: dict[tuple[str, str], tuple[str, object]] = {}
# One lock per (app_name, functionality) so two concurrent requests for the
# same functionality don't both rebuild at once on a cache miss; requests
# for different functionalities don't block each other.
_pipeline_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _cache_key(app_name: str, blueprint: GraphBlueprint, tier1_limits: FunctionalityConfig) -> str:
    """
    Hashes everything that should invalidate a cached pipeline if it changes:
    the app, the blueprint, and the functionality's resolved config.
    model_dump() turns the Pydantic models back into plain dicts so they can
    be JSON-serialized; sort_keys=True makes the JSON deterministic so the
    same content always hashes the same way regardless of dict order.
    """
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
    app_name: str,
    blueprint: GraphBlueprint,
    app_config: AppConfig,
    checkpointer,
):
    """
    Public entry point for api.py. Returns a cached compiled graph for this
    (app_name, functionality) when the config hasn't changed, otherwise builds
    (and caches) a fresh one. `app_name` disambiguates the cache: it's the
    resolved app's name (from AppBundle.meta.name / discover_apps()), not
    anything the caller invents.

    `checkpointer` is whatever persistence.py built at startup. It is
    deliberately required (no default): silently compiling without one would
    mean conversations quietly lose their history. It is not part of the
    cache key - there is one per process, for the process's whole life (the
    cache is cleared when api.py's lifespan starts, so a graph never outlives
    the pool its checkpointer was built on).
    """
    # Defense in depth, not the primary check - load_app() already enforces
    # a blueprint's functionality_ref matches the functionality file it came
    # from. This just means a mismatched/forged blueprint can't be used to
    # run against a different functionality's resources than intended.
    if blueprint.functionality_ref not in app_config.functionalities:
        raise ValueError(
            f"Security Block: Blueprint requested unauthorized functionality '{blueprint.functionality_ref}'."
        )

    functionality_ref = blueprint.functionality_ref
    tier1_limits = app_config.functionalities[functionality_ref]
    cache_key = _cache_key(app_name, blueprint, tier1_limits)
    entry_key = (app_name, functionality_ref)

    # Fast path, no lock needed just to read.
    cached = _pipeline_cache.get(entry_key)
    if cached is not None and cached[0] == cache_key:
        logger.debug("Pipeline cache hit for '%s/%s'", app_name, functionality_ref)
        return cached[1]

    # Cache miss or stale: only take the lock now, and only for this
    # specific (app_name, functionality).
    lock = _pipeline_locks.setdefault(entry_key, asyncio.Lock())
    async with lock:
        # Re-check inside the lock: another request may have already
        # rebuilt while this one waited for the lock.
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
        graph = await _build_pipeline(blueprint, tier1_limits, checkpointer)
        _pipeline_cache[entry_key] = (cache_key, graph)
        return graph


# --- The Pipeline Compiler ---
async def _build_pipeline(
    blueprint: GraphBlueprint, tier1_limits: FunctionalityConfig, checkpointer
):
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
    # Only the first model is used today - see FunctionalityConfig's
    # docstring in schemas.py.
    active_model = create_model(tier1_limits.models[0])
    logger.info(
        "Model: %s/%s",
        tier1_limits.models[0].provider,
        tier1_limits.models[0].model_name,
    )
    # "Safe" = already filtered by the allowlist, see get_filtered_mcp_tools
    # in factory.py.
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
        """
        Only called if the blueprint actually has a retrieve_context node
        (see ACTION_REGISTRY below) - vectordb/embedder clients are only
        ever created if the functionality needs them.
        """
        if not tier1_limits.vectordb:
            raise ValueError(
                f"Blueprint '{blueprint.name}' uses a retrieve_context node but "
                f"functionality '{blueprint.functionality_ref}' has no vectordb configured."
            )
        if not tier1_limits.embedding:
            raise ValueError(
                f"Blueprint '{blueprint.name}' uses a retrieve_context node but "
                f"functionality '{blueprint.functionality_ref}' has no embedding configured."
            )
        # [0]: same "only the first entry is used today" situation as
        # models. vectordb[0] and embedding[0] are assumed to correspond to
        # each other positionally - see the note on this in schemas.py.
        vectordb_config = tier1_limits.vectordb[0]
        embedding_config = tier1_limits.embedding[0]
        vectordb = create_vectordb(vectordb_config)
        embedder = create_embedder(embedding_config)

        def retrieve_context_node(state: State):
            last_user_message = state["messages"][-1].content
            query_vector = embedder.embed(content=[last_user_message])[0]
            results = vectordb.query(query=query_vector, n_res=3)
            # Copy rather than mutate state.get("context", {}) in place -
            # LangGraph nodes are expected to return updates, not mutate
            # state directly. "default" is the same context_id used by
            # call_llm_node, which is how the LLM node picks this back up.
            context = dict(state.get("context", {}))
            context["default"] = results
            return {"context": context}

        return retrieve_context_node

    # 3. Map YAML strings to actual Python execution logic
    # Runtime counterpart to NodeDef in schemas.py: a blueprint only ever
    # stores action names as strings, this dict resolves those strings into
    # real callables, rebuilt fresh per pipeline (since the callables close
    # over this build's active_model/safe_tools).
    ACTION_REGISTRY = {
        "call_llm": call_llm_node,
        "execute_tools": execute_tools_node,
    }
    # Only added - and only built - if this blueprint actually uses it, since
    # not every functionality needs a vectordb.
    if any(node.action == "retrieve_context" for node in blueprint.nodes):
        ACTION_REGISTRY["retrieve_context"] = make_retrieve_context_node()

    # Same idea, for condition_action strings used by conditional edges.
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
        # ToolNode needs the async wrapper; every other action is a plain
        # sync function and uses _timed_node.
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
            # Hardcoded mapping - see the NOTE on should_continue above and
            # EdgeDef's docstring in schemas.py. Every conditional edge in
            # the project is currently forced through this same two-outcome
            # mapping, regardless of which condition_action it names.
            builder.add_conditional_edges(
                edge.source,
                condition_func,
                {"execute_tools": edge.target, END: END}
            )
        else:
            builder.add_edge(edge.source, edge.target)

    # 5. Compile with the injected checkpointer so LangGraph accumulates
    # state["messages"] per thread_id (== conversation_id) across calls,
    # instead of every ainvoke() only seeing the single latest message.
    # With the Postgres saver this history is shared by all replicas and
    # survives restarts. (It requires async invocation - api.py uses ainvoke.)
    graph = builder.compile(checkpointer=checkpointer)
    logger.info(
        "Pipeline '%s' built in %.0f ms (%d nodes, %d edges)",
        blueprint.name,
        elapsed_ms(build_start),
        len(blueprint.nodes),
        len(blueprint.edges),
    )
    return graph
