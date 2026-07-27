"""
Minimal conversational API on top of the existing pipeline framework.

    POST /conversations                      -> {"conversation_id": "..."}
    POST /conversations/{id}/messages         -> {"answer": "...", "trace": [...]}

Both require: Authorization: Bearer <api_key>
app_id is NEVER read from the client; resolve_identity() derives it from the key.
"""
import sys
from pathlib import Path

# so `from core import build_pipeline_from_file` resolves against the
# AgenticFramework repo root, same as run.py does when run from there.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv()  # same as run.py -- picks up GROQ_API_KEY, GEMINI_API_KEY, etc. from .env

from fastapi import Depends, FastAPI, HTTPException, status

from pydantic import BaseModel

from core import build_pipeline_from_file  # noqa: E402

from .auth import AppIdentity, resolve_identity
from .store import Turn, store

app = FastAPI(title="AgenticFramework Conversations API")


# ---- schemas ----------------------------------------------------------

class CreateConversationResponse(BaseModel):
    conversation_id: str


class PostMessageRequest(BaseModel):
    content: str


class PostMessageResponse(BaseModel):
    conversation_id: str
    answer: str
    trace: list


# ---- endpoints ----------------------------------------------------------

@app.post("/conversations", response_model=CreateConversationResponse)
def create_conversation(identity: AppIdentity = Depends(resolve_identity)):
    orchestrator, context = build_pipeline_from_file(identity.config_path)
    conv = store.create(app_id=identity.app_id, orchestrator=orchestrator, context=context)
    return CreateConversationResponse(conversation_id=conv.id)


@app.post("/conversations/{conversation_id}/messages", response_model=PostMessageResponse)
def post_message(
    conversation_id: str,
    body: PostMessageRequest,
    identity: AppIdentity = Depends(resolve_identity),
):
    conv = store.get(conversation_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    # The auth-hole check: a valid key for app A must not be able to post
    # into a conversation owned by app B, even though both keys are valid.
    if conv.app_id != identity.app_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    conv.history.append(Turn(role="user", content=body.content))

    # ASSUMPTION (adjust once I see core/interfaces.py): orchestrator.run()
    # is single-shot per run.py and context doesn't obviously carry chat
    # history itself. So we fold prior turns into the query as a simple
    # transcript. If `context` has its own memory/history mechanism, swap
    # this block to use that instead and just pass body.content.
    if len(conv.history) > 1:
        transcript = "\n".join(f"{t.role}: {t.content}" for t in conv.history[:-1])
        query = f"Conversation so far:\n{transcript}\n\nuser: {body.content}"
    else:
        query = body.content

    result = conv.orchestrator.run(query, conv.context)
    conv.history.append(Turn(role="assistant", content=result.answer))

    return PostMessageResponse(
        conversation_id=conversation_id,
        answer=result.answer,
        trace=result.trace,
    )