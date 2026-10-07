"""
Tests for api.py's startup/shutdown wiring and its non-chat endpoints, using
FastAPI's TestClient (which runs the lifespan). No model, MCP server or
vector DB is involved: routing errors are raised before any pipeline is
built, and the Postgres test replaces chat_with_bot with a stub.
"""
import os
import sys

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "orchestrator"))

import pytest
from fastapi.testclient import TestClient

import api

REAL_CONFIGS = os.path.abspath(os.path.join(REPO_ROOT, "configs"))
NEW_CONVERSATION = {
    "message": "hi",
    "app": "greeting_finance_app",
    "functionality": "greeting_bot",
}


@pytest.fixture
def in_memory_env(monkeypatch):
    monkeypatch.setenv("CONFIGS_ROOT", REAL_CONFIGS)
    for var in ("DATABASE_URL", "PGHOST", "AUTO_MIGRATE"):
        monkeypatch.delenv(var, raising=False)


def test_health_and_ready_without_postgres(in_memory_env):
    with TestClient(api.app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200


def test_routing_errors_are_still_reported(in_memory_env):
    with TestClient(api.app) as client:
        assert client.post("/chat", json={"message": "hi"}).status_code == 400
        unknown = client.post("/chat", json={**NEW_CONVERSATION, "app": "nope"})
        assert unknown.status_code == 404


def test_readyz_is_503_when_persistence_is_down(in_memory_env):
    class BrokenPersistence:
        async def ping(self):
            raise ConnectionError("db down")

        async def close(self):  # called by the lifespan at shutdown
            pass

    with TestClient(api.app) as client:
        client.app.state.persistence = BrokenPersistence()
        assert client.get("/readyz").status_code == 503
        # Liveness must NOT depend on the database, or an outage restarts pods.
        assert client.get("/healthz").status_code == 200


@pytest.mark.postgres
def test_conversation_routing_survives_an_orchestrator_restart(monkeypatch):
    """Start a conversation, shut the app down completely, start a fresh one
    (new lifespan, new pool) and continue with only the conversation_id."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    monkeypatch.setenv("CONFIGS_ROOT", REAL_CONFIGS)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("AUTO_MIGRATE", "true")

    async def fake_chat(app_registry, checkpointer, message, app, functionality, conversation_id):
        return f"{app}/{functionality}"

    monkeypatch.setattr(api, "chat_with_bot", fake_chat)

    with TestClient(api.app) as first_pod:
        started = first_pod.post("/chat", json=NEW_CONVERSATION)
        assert started.status_code == 200
        conversation_id = started.json()["conversation_id"]

    with TestClient(api.app) as restarted_pod:
        resumed = restarted_pod.post(
            "/chat", json={"message": "again", "conversation_id": conversation_id}
        )

    assert resumed.status_code == 200
    assert resumed.json()["response"] == "greeting_finance_app/greeting_bot"
