from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

from core.IModel import State
from core.schemas import AppConfig, GraphBlueprint
from core.factory import create_model, create_vectordb, create_embedder, get_filtered_mcp_tools

# --- Standard Edge Conditions ---
def should_continue(state: State) -> str:
    """Routes the graph to tools if the LLM made a tool call, otherwise ends."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "execute_tools"
    return END


# --- The Pipeline Compiler ---
async def create_pipeline(blueprint: GraphBlueprint, app_config: AppConfig):
    """
    Validates limits, instantiates resources, and dynamically builds the LangGraph.
    This is what your API endpoint will call.
    """

    # 1. Enforce Tier 1 Security Vault
    if blueprint.functionality_ref not in app_config.functionalities:
        raise ValueError(
            f"Security Block: Blueprint requested unauthorized functionality '{blueprint.functionality_ref}'."
        )

    tier1_limits = app_config.functionalities[blueprint.functionality_ref]

    # 2. Spin up secure infrastructure
    active_model = create_model(tier1_limits.models[0])
    safe_tools = await get_filtered_mcp_tools(tier1_limits)

    if safe_tools:
        active_model.bind_tools(safe_tools)

    # 3. Create closure functions for the nodes (injecting the active resources)
    def call_llm_node(state: State):
        return active_model.generate(state, context_id="default")

    execute_tools_node = ToolNode(safe_tools)

    def make_retrieve_context_node():
        """
        Builds a node that embeds the latest user message, queries the
        functionality's configured vector store, and stashes the results
        in state["context"]["default"] for the model node to pick up.
        Only built if the blueprint actually uses a retrieve_context node,
        since not every functionality has a vectordb configured.
        """
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

    # 4. Map YAML strings to actual Python execution logic
    ACTION_REGISTRY = {
        "call_llm": call_llm_node,
        "execute_tools": execute_tools_node,
    }
    if any(node.action == "retrieve_context" for node in blueprint.nodes):
        ACTION_REGISTRY["retrieve_context"] = make_retrieve_context_node()

    CONDITION_REGISTRY = {
        "should_continue": should_continue
    }

    # 5. Build the literal Graph Structure based on the Tier 2 Blueprint
    builder = StateGraph(State)

    for node in blueprint.nodes:
        if node.action not in ACTION_REGISTRY:
            raise ValueError(f"Unknown action '{node.action}' in blueprint.")
        builder.add_node(node.id, ACTION_REGISTRY[node.action])

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

    # 6. Compile and return
    return builder.compile()
