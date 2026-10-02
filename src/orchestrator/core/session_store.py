import time
from dataclasses import dataclass
from abc import ABC, abstractmethod

# TODO: Migrate to postgre

# Since the metadata of the conversation won't change after its creation we can freeze the attributes.
@dataclass(frozen=True)
class SessionRecord:
    app: str
    functionality: str
    created_at: float

class SessionStore(ABC):
    # We are using async because in order to account for future slow I/O.
    @abstractmethod
    async def get(self, conversation_id: str) -> SessionRecord | None: ...
    @abstractmethod
    async def set(self, conversation_id: str, record: SessionRecord) -> None: ...

class InMemorySessionStore(SessionStore):
    """Single-process, non-persistent."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    async def get(self, conversation_id: str) -> SessionRecord | None:
        return self._records.get(conversation_id)

    async def set(self, conversation_id: str, record: SessionRecord) -> None:
        self._records[conversation_id] = record

    def clear(self) -> None:
        self._records.clear()


def new_session_record(app: str, functionality: str) -> SessionRecord:
    return SessionRecord(app=app, functionality=functionality, created_at=time.time())
