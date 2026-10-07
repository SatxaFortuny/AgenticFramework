"""
Contract tests for SessionStore. Every implementation must pass the same
tests, so swapping InMemorySessionStore for PostgresSessionStore can't change
behaviour. The Postgres variant needs a live database (TEST_DATABASE_URL) and
is skipped without one, so the default unit-test run stays service-free.
"""
import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

import pytest

from core.persistence import open_pool, run_migrations
from core.session_store import (
    InMemorySessionStore,
    PostgresSessionStore,
    new_session_record,
)


def _run(coro):
    return asyncio.run(coro)


@asynccontextmanager
async def _memory_store():
    yield InMemorySessionStore()


@asynccontextmanager
async def _postgres_store():
    # Pool is opened and closed inside the same event loop as the test body
    # (each test is a single asyncio.run) - a pool can't cross loops.
    pool = await open_pool(os.environ["TEST_DATABASE_URL"])
    try:
        await run_migrations(pool)
        yield PostgresSessionStore(pool)
    finally:
        await pool.close()


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
def open_store(request):
    if request.param == "memory":
        return _memory_store
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    return _postgres_store


def _new_id() -> str:
    # Unique per test: the Postgres table is shared across runs.
    return f"test-{uuid.uuid4()}"


def test_get_missing_returns_none(open_store):
    async def run():
        async with open_store() as store:
            return await store.get(_new_id())

    assert _run(run()) is None


def test_set_then_get_round_trips(open_store):
    conversation_id = _new_id()
    record = new_session_record("greeting_finance_app", "greeting_bot")

    async def run():
        async with open_store() as store:
            await store.set(conversation_id, record)
            return await store.get(conversation_id)

    fetched = _run(run())
    assert fetched.app == "greeting_finance_app"
    assert fetched.functionality == "greeting_bot"
    assert fetched.created_at == pytest.approx(record.created_at)


def test_records_are_independent_per_conversation(open_store):
    id_a, id_b = _new_id(), _new_id()

    async def run():
        async with open_store() as store:
            await store.set(id_a, new_session_record("app", "bot_a"))
            await store.set(id_b, new_session_record("app", "bot_b"))
            return await store.get(id_a), await store.get(id_b)

    a, b = _run(run())
    assert (a.functionality, b.functionality) == ("bot_a", "bot_b")


def test_clear_removes_all_records():
    """InMemorySessionStore-only helper, used to reset state between tests."""
    store = InMemorySessionStore()
    _run(store.set("conv-1", new_session_record("app", "func")))
    store.clear()
    assert _run(store.get("conv-1")) is None


@pytest.mark.postgres
def test_postgres_set_is_first_writer_wins():
    """Documented behaviour of PostgresSessionStore.set(): a second set() for
    an id another replica already bound must not re-point that conversation."""
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    conversation_id = _new_id()

    async def run():
        async with _postgres_store() as store:
            await store.set(conversation_id, new_session_record("app", "first"))
            await store.set(conversation_id, new_session_record("app", "second"))
            return await store.get(conversation_id)

    assert _run(run()).functionality == "first"
