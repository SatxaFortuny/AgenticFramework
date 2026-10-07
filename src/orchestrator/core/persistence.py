import asyncio
import logging
import os
import time
from dataclasses import dataclass

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

try:
    # Current langgraph versions.
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # pragma: no cover - older langgraph versions
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver

from core.session_store import (
    InMemorySessionStore,
    PostgresSessionStore,
    SessionStore,
)

logger = logging.getLogger(__name__)

# Arbitrary constant, but every process that runs migrations must use the
# same one: it's the key of the Postgres advisory lock that serialises them.
_MIGRATION_LOCK_ID = 727_274_001


def get_conninfo() -> str | None:
    """
    Returns the libpq connection string/conninfo to use, or None if Postgres
    isn't configured. An empty string is a valid result: it means "connect
    using the PG* environment variables".
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    if os.getenv("PGHOST"):
        return ""
    return None


async def open_pool(
    conninfo: str, *, max_size: int = 10, wait_timeout: float = 30.0
) -> AsyncConnectionPool:
    """
    Opens a connection pool configured the way AsyncPostgresSaver requires:
    autocommit (it manages its own transactions), no prepared statements
    (they break behind PgBouncer in transaction mode, which is where this
    is headed once replicas multiply) and dict rows.

    Waits up to wait_timeout for the first connection, so a pod that starts
    a few seconds before Postgres is ready retries instead of crash-looping.
    Raises psycopg_pool.PoolTimeout if the database never becomes reachable.
    """
    pool = AsyncConnectionPool(
        conninfo=conninfo,
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open(wait=True, timeout=wait_timeout)
    return pool


async def _acquire_migration_lock(
    conn, *, poll_interval: float = 0.5, timeout: float = 300.0
) -> None:
    """
    Takes the migration advisory lock by POLLING pg_try_advisory_lock instead
    of blocking in pg_advisory_lock - and that difference is load-bearing.

    LangGraph's own migrations run CREATE INDEX CONCURRENTLY, which waits for
    every other open transaction in the database to finish. A process blocked
    inside pg_advisory_lock() *is* an open transaction, so with the blocking
    call the lock holder waits for the waiters while the waiters wait for the
    holder, and every replica hangs forever on a fresh database. Polling keeps
    each attempt a short, already-finished statement (the connection is in
    autocommit mode), so waiters are never inside a transaction while they wait.
    """
    deadline = time.monotonic() + timeout
    while True:
        cur = await conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired", (_MIGRATION_LOCK_ID,)
        )
        if (await cur.fetchone())["acquired"]:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Could not acquire the migration lock within {timeout:.0f}s; "
                "another process is holding it."
            )
        await asyncio.sleep(poll_interval)


async def run_migrations(pool: AsyncConnectionPool) -> None:
    """
    Creates/upgrades every table this app needs (LangGraph's checkpoint
    tables + our sessions table). Idempotent.

    Serialised with a Postgres advisory lock because several replicas (or
    their init containers) can start at the same moment on a rollout, and
    concurrent migration bookkeeping would collide. The lock is held on a
    dedicated connection; the actual setup() calls borrow others from the
    pool, so the pool needs max_size >= 2. See _acquire_migration_lock for why
    waiting is done by polling.
    """
    async with pool.connection() as lock_conn:
        await _acquire_migration_lock(lock_conn)
        try:
            await AsyncPostgresSaver(pool).setup()
            await PostgresSessionStore(pool).setup()
        finally:
            await lock_conn.execute(
                "SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,)
            )
    logger.info("Database migrations applied")


@dataclass
class Persistence:
    """The two stateful pieces api.py needs, plus the pool backing them."""

    checkpointer: object  # an InMemorySaver or AsyncPostgresSaver
    session_store: SessionStore
    pool: AsyncConnectionPool | None = None

    async def ping(self, timeout: float = 2.0) -> None:
        """
        Raises if the backing store is unreachable (used by /readyz). Fails
        fast on purpose: the pool's default 30 s wait for a connection is far
        longer than a k8s probe is willing to wait, so a probe would just time
        out with no useful log line.
        """
        if self.pool is not None:
            async with self.pool.connection(timeout=timeout) as conn:
                await conn.execute("SELECT 1")

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()


async def build_persistence() -> Persistence:
    """Postgres-backed if configured (see module docstring), else in-memory."""
    conninfo = get_conninfo()
    if conninfo is None:
        logger.warning(
            "No DATABASE_URL/PGHOST set: conversations are kept in process "
            "memory and are lost on restart (single replica only)."
        )
        return Persistence(
            checkpointer=InMemorySaver(), session_store=InMemorySessionStore()
        )

    pool = await open_pool(conninfo, max_size=int(os.getenv("DB_POOL_MAX", "10")))
    if os.getenv("AUTO_MIGRATE", "").lower() == "true":
        await run_migrations(pool)
    logger.info("Postgres persistence ready (checkpointer + session store)")
    return Persistence(
        checkpointer=AsyncPostgresSaver(pool),
        session_store=PostgresSessionStore(pool),
        pool=pool,
    )
