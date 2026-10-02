import logging
import time

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.logging_utils import elapsed_ms, preview, setup_logging
from core.pipeline import get_or_create_pipeline
from core.routing import RoutingError, resolve_session
from core.schemas import discover_apps
from core.session_store import InMemorySessionStore

setup_logging()
logger = logging.getLogger("orchestrator")

# discover_apps() scans configs/ for every app directory (any subdir with an
# app.yaml) and load_app()'s each - adding a new app is just adding a new
# configs/{app}/ directory, no code change here. Both of these are built
# once, at module import time (i.e. process startup), not per-request.
#
# _session_store maps conversation_id -> (app, functionality) so a client
# only names app/functionality on the first message of a conversation - see
# core/routing.py for the full resolution rules. It's in-process (see
# core/session_store.py's docstring for why that's a real limitation once
# this runs with >1 replica - same limitation as pipeline.py's checkpointer,
# and the two should be upgraded together since they're both keyed by the
# same conversation_id and one being stale without the other is worse than
# both being stale).
_app_registry = discover_apps("configs")
_session_store = InMemorySessionStore()

logger.info(
    "Loaded %d app(s): %s",
    len(_app_registry),
    {name: list(bundle.app_config.functionalities) for name, bundle in _app_registry.items()},
)


async def chat_with_bot(user_message: str, app: str, functionality: str, conversation_id: str) -> str:
    """
    Runs one turn of a conversation: gets (or builds) the compiled graph for
    this (app, functionality), invokes it with the new user message, and
    returns the model's reply text. Assumes app/functionality/conversation_id
    have already been resolved and validated by resolve_session() - this
    function does no validation of its own.
    """
    bundle = _app_registry[app]
    blueprint = bundle.blueprints[functionality]

    graph = await get_or_create_pipeline(app, blueprint, bundle.app_config)

    start = time.perf_counter()
    logger.info(
        "Graph execution started (app=%s, functionality=%s, conversation_id=%s)",
        app, functionality, conversation_id,
    )
    # thread_id == conversation_id: this is what lets the shared checkpointer
    # in core/pipeline.py accumulate this conversation's message history
    # across separate /chat calls, instead of each call only seeing the one
    # message it was sent. Only the new message is passed in - the
    # checkpointer is what supplies everything before it.
    response = await graph.ainvoke(
        {"messages": [("user", user_message)]},
        config={"configurable": {"thread_id": conversation_id}},
    )
    logger.info("Graph execution finished in %.0f ms", elapsed_ms(start))
    return response["messages"][-1].content


class ChatRequest(BaseModel):
    """
    conversation_id/app/functionality are all optional here on purpose -
    resolve_session() decides what combination is actually valid (new
    conversation needs app+functionality; existing one needs just
    conversation_id). Validating that here instead would duplicate the
    rules already in core/routing.py.
    """
    message: str
    conversation_id: str | None = None
    app: str | None = None
    functionality: str | None = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: str  # always present in the response, even if the
                           # request didn't send one - the client should
                           # store this and reuse it for the next message.


app = FastAPI(title="Agentic Framework Orchestrator")


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    start = time.perf_counter()
    logger.info("Request received (message_length=%d)", len(request.message))
    # Debug-only: the actual message content, truncated via preview() - never
    # logged at INFO, since a user message could contain sensitive content
    # and INFO-level logs are expected to be on in normal operation.
    logger.debug("Request message: %s", preview(request.message))

    try:
        session = await resolve_session(
            conversation_id=request.conversation_id,
            app=request.app,
            functionality=request.functionality,
            session_store=_session_store,
            app_registry=_app_registry,
        )
    except RoutingError as e:
        # RoutingError already carries the right HTTP status (400/404/409 -
        # see core/routing.py), so this just forwards it rather than
        # re-deriving one from the error message.
        logger.warning("Routing error (%d) after %.0f ms: %s", e.status_code, elapsed_ms(start), e.detail)
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    try:
        response_text = await chat_with_bot(
            request.message, session.app, session.functionality, session.conversation_id
        )
        logger.info(
            "Response returned (response_length=%d, total=%.0f ms)",
            len(response_text),
            elapsed_ms(start),
        )
        logger.debug("Response message: %s", preview(response_text))
        return ChatResponse(response=response_text, conversation_id=session.conversation_id)
    except ValueError as e:
        # Config/blueprint validation errors are client-facing (bad
        # functionality_ref, missing vectordb for a retrieve_context node,
        # etc. - see core/schemas.py's load_app) - these are configuration
        # problems, not the user's fault, but still safe to describe back.
        logger.warning(
            "Pipeline configuration error after %.0f ms: %s", elapsed_ms(start), e
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        # Anything else (model API errors, MCP server down, etc.): log the
        # full traceback via logger.exception so it's debuggable from
        # kubectl logs, but return an opaque 500 to the client - internal
        # failure details shouldn't leak over the API. See
        # docs/postmortems/2026-09-27-crio-configmap-nested-paths.md
        # (Incident 3) for a real example of this showing up in practice.
        logger.exception("CRITICAL PIPELINE ERROR after %.0f ms", elapsed_ms(start))
        raise HTTPException(status_code=500, detail="Internal pipeline error")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
