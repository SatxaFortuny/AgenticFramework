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

# CHANGED (Batch 2): was one hardcoded APP_DIR/FUNCTIONALITY_REF. discover_apps()
# scans configs/ for every app directory (any subdir with an app.yaml) and
# load_app()'s each - adding a new app is now just adding a new
# configs/{app}/ directory, no code change here.
#
# _session_store maps conversation_id -> (app, functionality) so a client only
# names app/functionality on the first message of a conversation; see
# core/routing.py for the full resolution rules. It's in-process (see
# core/session_store.py's docstring for why that's a real limitation once
# this runs with >1 replica).
_app_registry = discover_apps("configs")
_session_store = InMemorySessionStore()

logger.info(
    "Loaded %d app(s): %s",
    len(_app_registry),
    {name: list(bundle.app_config.functionalities) for name, bundle in _app_registry.items()},
)


async def chat_with_bot(user_message: str, app: str, functionality: str, conversation_id: str) -> str:
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
    # message it was sent.
    response = await graph.ainvoke(
        {"messages": [("user", user_message)]},
        config={"configurable": {"thread_id": conversation_id}},
    )
    logger.info("Graph execution finished in %.0f ms", elapsed_ms(start))
    return response["messages"][-1].content


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    app: str | None = None
    functionality: str | None = None


class ChatResponse(BaseModel):
    response: str
    conversation_id: str


app = FastAPI(title="Agentic Framework Orchestrator")


@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    start = time.perf_counter()
    logger.info("Request received (message_length=%d)", len(request.message))
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
        # Config/blueprint validation errors are client-facing (bad functionality_ref, etc.)
        logger.warning(
            "Pipeline configuration error after %.0f ms: %s", elapsed_ms(start), e
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("CRITICAL PIPELINE ERROR after %.0f ms", elapsed_ms(start))
        raise HTTPException(status_code=500, detail="Internal pipeline error")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
