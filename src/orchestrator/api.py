import logging
import sys

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.pipeline import create_pipeline
from core.schemas import load_app_config, load_blueprint

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("orchestrator")


async def chat_with_bot(user_message: str) -> str:
    app_config = load_app_config("configs/config.yaml")
    blueprint = load_blueprint("configs/blueprint.yaml")

    graph = await create_pipeline(blueprint, app_config)

    response = await graph.ainvoke({"messages": [("user", user_message)]})
    return response["messages"][-1].content


class ChatRequest(BaseModel):
    message: str


app = FastAPI(title="Agentic Framework Orchestrator")


@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        response = await chat_with_bot(request.message)
        return {"response": response}
    except ValueError as e:
        # Config/blueprint validation errors are client-facing (bad functionality_ref, etc.)
        logger.warning("Pipeline configuration error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("CRITICAL PIPELINE ERROR")
        raise HTTPException(status_code=500, detail="Internal pipeline error")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
