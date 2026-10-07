import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


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
    """
    Single-process, non-persistent. Used for local dev and unit tests, and as
    the fallback when no Postgres is configured (see core/persistence.py).
    Does not work across multiple orchestrator replicas.
    """

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}

    async def get(self, conversation_id: str) -> SessionRecord | None:
        return self._records.get(conversation_id)

    async def set(self, conversation_id: str, record: SessionRecord) -> None:
        self._records[conversation_id] = record

    def clear(self) -> None:
        self._records.clear()


_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    conversation_id TEXT PRIMARY KEY,
    app             TEXT NOT NULL,
    functionality   TEXT NOT NULL,
    created_at      DOUBLE PRECISION NOT NULL
)
"""


class PostgresSessionStore(SessionStore):
    """
    Shared by every orchestrator replica, survives restarts.

    Takes an already-open psycopg AsyncConnectionPool (built by
    core/persistence.py, which owns the pool's lifecycle) instead of opening
    its own connections, so the LangGraph checkpointer and this store share
    one pool. The pool is configured with row_factory=dict_row, hence the
    row["..."] access below.

    set() is first-writer-wins (ON CONFLICT DO NOTHING). resolve_session()
    only calls set() for an id it just found missing, so a conflict means
    another replica bound that id a moment earlier - keeping the first
    binding is what stops a later request from silently re-pointing an
    existing conversation at a different app/functionality.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def setup(self) -> None:
        """Creates the table if needed. Called from migrations, not per request."""
        async with self._pool.connection() as conn:
            await conn.execute(_SESSIONS_DDL)

    async def get(self, conversation_id: str) -> SessionRecord | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT app, functionality, created_at FROM sessions "
                "WHERE conversation_id = %s",
                (conversation_id,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return SessionRecord(
            app=row["app"],
            functionality=row["functionality"],
            created_at=row["created_at"],
        )

    async def set(self, conversation_id: str, record: SessionRecord) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO sessions (conversation_id, app, functionality, created_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (conversation_id) DO NOTHING",
                (conversation_id, record.app, record.functionality, record.created_at),
            )


def new_session_record(app: str, functionality: str) -> SessionRecord:
    return SessionRecord(app=app, functionality=functionality, created_at=time.time())
