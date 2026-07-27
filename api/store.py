"""
In-memory conversation store.

Each conversation pins the app_id that created it, plus the live
orchestrator/context pair from build_pipeline_from_file so repeated turns
reuse the same pipeline instance (and its memory, if the context object
carries any) instead of rebuilding it per message.

Swap this module for a DB-backed version later; the interface
(create/get/append) is what main.py depends on, not the storage.
"""
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class Conversation:
    id: str
    app_id: str
    orchestrator: Any
    context: Any
    history: list[Turn] = field(default_factory=list)


class ConversationStore:
    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._lock = Lock()

    def create(self, app_id: str, orchestrator: Any, context: Any) -> Conversation:
        conv = Conversation(
            id=str(uuid.uuid4()),
            app_id=app_id,
            orchestrator=orchestrator,
            context=context,
        )
        with self._lock:
            self._conversations[conv.id] = conv
        return conv

    def get(self, conversation_id: str) -> Conversation | None:
        return self._conversations.get(conversation_id)


store = ConversationStore()
