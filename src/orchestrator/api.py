import logging
import time

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.logging_utils import elapsed_ms, preview, setup_logging
from core.pipeline import get_or_create_pipeline
from core.schemas import load_app_config, load_blueprint

setup_logging()
logger = logging.getLogger("orchestrator")


async def chat_with_bot(user_message: str) -> str:
    app_config = load_app_config("configs/config.yaml")
    blueprint = load_blueprint("configs/blueprint.yaml")
    logger.info(
        "Loaded blueprint '%s' (functionality=%s)",
        blueprint.name,
        blueprint.functionality_ref,
    )

    # CHANGED: was create_pipeline(...) - rebuilt the graph (MCP discovery,
    # model/vectordb init) on every call. get_or_create_pipeline() reuses a
    # cached graph for this functionality when config.yaml/blueprint.yaml
    # haven't changed since the last build.
    graph = await get_or_create_pipeline(blueprint, app_config)

    start = time.perf_counter()
    logger.info("Graph execution started")
    response = await graph.ainvoke({"messages": [("user", user_message)]})
    logger.info("Graph execution finished in %.0f ms", elapsed_ms(start))
    return response["messages"][-1].content


class ChatRequest(BaseModel):
    message: str


app = FastAPI(title="Agentic Framework Orchestrator")


@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    start = time.perf_counter()
    logger.info("Request received (message_length=%d)", len(request.message))
    logger.debug("Request message: %s", preview(request.message))
    try:
        response = await chat_with_bot(request.message)
        logger.info(
            "Response returned (response_length=%d, total=%.0f ms)",
            len(response),
            elapsed_ms(start),
        )
        logger.debug("Response message: %s", preview(response))
        return {"response": response}
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
