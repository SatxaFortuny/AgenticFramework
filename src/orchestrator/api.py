import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from core.logging_utils import elapsed_ms, preview, setup_logging
from core.persistence import build_persistence
from core.pipeline import clear_pipeline_cache, get_or_create_pipeline
from core.routing import RoutingError, resolve_session
from core.schemas import AppBundle, discover_apps

setup_logging()
logger = logging.getLogger("orchestrator")


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    """
    Builds everything stateful once at startup and tears it down at shutdown.
    Lives in a lifespan (not at module import time, as before) because the
    Postgres connection pool is async and has to be opened and closed inside
    the running event loop.

    discover_apps() scans configs/ for every app directory (any subdir with an
    app.yaml) and load_app()'s each - adding a new app is just adding a new
    configs/{app}/ directory, no code change here. A broken config raises
    here, so the pod fails at startup instead of mid-request.

    The persistence object carries the session store (conversation_id ->
    app/functionality) and the LangGraph checkpointer (message history). Both
    are Postgres-backed when DATABASE_URL/PGHOST is set, which is what makes
    the orchestrator stateless and safe to run with more than one replica -
    see core/persistence.py.
    """
    fastapi_app.state.app_registry = discover_apps(os.getenv("CONFIGS_ROOT", "configs"))
    logger.info(
        "Loaded %d app(s): %s",
        len(fastapi_app.state.app_registry),
        {
            name: list(bundle.app_config.functionalities)
            for name, bundle in fastapi_app.state.app_registry.items()
        },
    )
    # A cached graph holds a reference to the checkpointer (and so to the
    # pool) of the lifespan that built it - never reuse one across lifespans.
    clear_pipeline_cache()
    fastapi_app.state.persistence = await build_persistence()
    try:
        yield
    finally:
        await fastapi_app.state.persistence.close()


async def chat_with_bot(
    app_registry: dict[str, AppBundle],
    checkpointer,
    user_message: str,
    app: str,
    functionality: str,
    conversation_id: str,
) -> str:
    """
    Runs one turn of a conversation: gets (or builds) the compiled graph for
    this (app, functionality), invokes it with the new user message, and
    returns the model's reply text. Assumes app/functionality/conversation_id
    have already been resolved and validated by resolve_session() - this
    function does no validation of its own.
    """
    bundle = app_registry[app]
    blueprint = bundle.blueprints[functionality]

    graph = await get_or_create_pipeline(
        app, blueprint, bundle.app_config, checkpointer
    )

    start = time.perf_counter()
    logger.info(
        "Graph execution started (app=%s, functionality=%s, conversation_id=%s)",
        app,
        functionality,
        conversation_id,
    )
    # thread_id == conversation_id: this is what lets the shared checkpointer
    # accumulate this conversation's message history across separate /chat
    # calls (and across replicas and restarts, with the Postgres saver),
    # instead of each call only seeing the one message it was sent. Only the
    # new message is passed in - the checkpointer supplies everything before it.
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


app = FastAPI(title="Agentic Framework Orchestrator", lifespan=lifespan)


@app.get("/healthz")
async def healthz():
    """Liveness: the process is up and serving. Deliberately checks nothing
    external - a database outage must not get the pod restarted."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(http_request: Request):
    """Readiness: this pod can actually serve /chat, i.e. it can reach its
    persistence backend. Failing it takes the pod out of the Service."""
    try:
        await http_request.app.state.persistence.ping()
    except Exception:
        logger.exception("Readiness check failed")
        raise HTTPException(status_code=503, detail="Persistence backend unavailable")
    return {"status": "ready"}


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, http_request: Request):
    start = time.perf_counter()
    state = http_request.app.state
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
            session_store=state.persistence.session_store,
            app_registry=state.app_registry,
        )
    except RoutingError as e:
        # RoutingError already carries the right HTTP status (400/404/409 -
        # see core/routing.py), so this just forwards it rather than
        # re-deriving one from the error message.
        logger.warning(
            "Routing error (%d) after %.0f ms: %s",
            e.status_code,
            elapsed_ms(start),
            e.detail,
        )
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    try:
        response_text = await chat_with_bot(
            state.app_registry,
            state.persistence.checkpointer,
            request.message,
            session.app,
            session.functionality,
            session.conversation_id,
        )
        logger.info(
            "Response returned (response_length=%d, total=%.0f ms)",
            len(response_text),
            elapsed_ms(start),
        )
        logger.debug("Response message: %s", preview(response_text))
        return ChatResponse(
            response=response_text, conversation_id=session.conversation_id
        )
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
