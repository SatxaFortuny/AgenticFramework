import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

from core.session_store import InMemorySessionStore, new_session_record


def _run(coro):
    return asyncio.run(coro)


def test_get_missing_returns_none():
    store = InMemorySessionStore()
    assert _run(store.get("nope")) is None


def test_set_then_get_round_trips():
    store = InMemorySessionStore()
    record = new_session_record("greeting_finance_app", "greeting_bot")

    async def run():
        await store.set("conv-1", record)
        return await store.get("conv-1")

    fetched = _run(run())
    assert fetched.app == "greeting_finance_app"
    assert fetched.functionality == "greeting_bot"


def test_clear_removes_all_records():
    store = InMemorySessionStore()
    _run(store.set("conv-1", new_session_record("app", "func")))
    store.clear()
    assert _run(store.get("conv-1")) is None
