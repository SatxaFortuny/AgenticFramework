"""
Tests for core/persistence.py against a live Postgres (TEST_DATABASE_URL).
Skipped without one; CI runs them in a job with a Postgres service container
(`pytest -m postgres`).
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

import psycopg
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from psycopg.conninfo import make_conninfo

from core.persistence import (
    build_persistence,
    get_conninfo,
    open_pool,
    run_migrations,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def database_url():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


def _echo_graph(checkpointer):
    """A tiny graph with no LLM: appends one assistant message per turn."""
    def echo(state: MessagesState):
        return {"messages": [("assistant", "ok")]}

    builder = StateGraph(MessagesState)
    builder.add_node("echo", echo)
    builder.add_edge(START, "echo")
    builder.add_edge("echo", END)
    return builder.compile(checkpointer=checkpointer)


def test_history_survives_a_new_pool(database_url):
    """The point of the whole exercise: a conversation continues with its full
    history after the process that started it is gone. Two separate pools
    (and checkpointer objects) stand in for 'before' and 'after' a restart."""
    config = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}

    async def run():
        pool1 = await open_pool(database_url)
        try:
            await run_migrations(pool1)
            graph1 = _echo_graph(AsyncPostgresSaver(pool1))
            await graph1.ainvoke({"messages": [("user", "one")]}, config)
        finally:
            await pool1.close()

        pool2 = await open_pool(database_url)  # "restarted" process
        try:
            graph2 = _echo_graph(AsyncPostgresSaver(pool2))
            return await graph2.ainvoke({"messages": [("user", "two")]}, config)
        finally:
            await pool2.close()

    result = asyncio.run(run())
    user_turns = [m.content for m in result["messages"] if m.type == "human"]
    assert user_turns == ["one", "two"]
    assert len(result["messages"]) == 4  # user, assistant, user, assistant


def test_threads_do_not_see_each_other(database_url):
    async def run():
        pool = await open_pool(database_url)
        try:
            await run_migrations(pool)
            graph = _echo_graph(AsyncPostgresSaver(pool))
            cfg_a = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}
            cfg_b = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}
            await graph.ainvoke({"messages": [("user", "only in A")]}, cfg_a)
            return await graph.ainvoke({"messages": [("user", "B here")]}, cfg_b)
        finally:
            await pool.close()

    result = asyncio.run(run())
    assert [m.content for m in result["messages"] if m.type == "human"] == ["B here"]


def test_concurrent_migrations_on_an_empty_schema_do_not_hang(database_url):
    """
    Several replicas' init containers start in the same second on a FRESH
    database. Runs in a throwaway schema so it really starts from empty
    (the shared test schema is already migrated after the first test, which is
    how a blocking-lock deadlock once slipped past this test). The timeout is
    the assertion: the old implementation hung here forever.
    """
    schema = f"mig_{uuid.uuid4().hex[:10]}"
    conninfo = make_conninfo(database_url, options=f"-c search_path={schema}")

    async def migrate_once():
        pool = await open_pool(conninfo, max_size=3)
        try:
            await run_migrations(pool)
        finally:
            await pool.close()

    async def run():
        admin = await psycopg.AsyncConnection.connect(database_url, autocommit=True)
        try:
            await admin.execute(f"CREATE SCHEMA {schema}")
            await asyncio.wait_for(
                asyncio.gather(*(migrate_once() for _ in range(6))), timeout=60
            )
            cur = await admin.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = %s",
                (schema,),
            )
            return (await cur.fetchone())[0]
        finally:
            await admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            await admin.close()

    # 4 LangGraph tables + our sessions table
    assert asyncio.run(run()) == 5


def test_build_persistence_uses_postgres_when_configured(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AUTO_MIGRATE", "true")

    async def run():
        persistence = await build_persistence()
        try:
            await persistence.ping()
            return persistence.pool is not None
        finally:
            await persistence.close()

    assert asyncio.run(run()) is True


def test_conninfo_resolution(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    assert get_conninfo() is None  # nothing configured -> in-memory fallback

    monkeypatch.setenv("PGHOST", "postgres-service")
    assert get_conninfo() == ""  # empty conninfo = "use the PG* variables"

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    assert get_conninfo() == "postgresql://u:p@h/db"  # URL wins
