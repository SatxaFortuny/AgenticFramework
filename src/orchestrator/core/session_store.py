"""
Maps conversation_id -> (app_name, functionality_ref), so a client only has
to name the app/functionality on the *first* message of a conversation; every
later message just sends conversation_id and the server resolves the rest.

SessionStore is the interface a Redis-backed implementation would need to
satisfy - get/set/exists, all async so a network-backed store fits the same
shape without api.py or routing.py needing to change. InMemorySessionStore is
fine for a single-process dev/test setup; it does NOT survive a restart and
does NOT work across multiple orchestrator replicas (each has its own dict).
That's the concrete reason a Redis-backed store becomes necessary once the
orchestrator is horizontally scaled - flagged here rather than silently
discovered in production.
"""
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SessionRecord:
    app: str
    functionality: str
    created_at: float


class SessionStore(Protocol):
    async def get(self, conversation_id: str) -> SessionRecord | None: ...
    async def set(self, conversation_id: str, record: SessionRecord) -> None: ...


class InMemorySessionStore:
    """Single-process, non-persistent. See module docstring for limits."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    async def get(self, conversation_id: str) -> SessionRecord | None:
        return self._records.get(conversation_id)

    async def set(self, conversation_id: str, record: SessionRecord) -> None:
        self._records[conversation_id] = record

    def clear(self) -> None:
        """Test/admin helper - not part of the SessionStore protocol."""
        self._records.clear()


def new_session_record(app: str, functionality: str) -> SessionRecord:
    return SessionRecord(app=app, functionality=functionality, created_at=time.time())
