"""
Unit tests for core.routing.resolve_session. No FastAPI, no real pipeline -
just the session store and a fake app registry, so these run in milliseconds
and don't need any live service.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "orchestrator"))

import pytest

from core.routing import RoutingError, resolve_session
from core.schemas import AppBundle, AppConfig, AppMetaConfig, FunctionalityConfig
from core.session_store import InMemorySessionStore


def _fake_registry() -> dict:
    """A two-app registry with no real blueprints needed - resolve_session
    only looks at app_config.functionalities, never at blueprints."""
    def bundle(app_name: str, functionality_names: list[str]) -> AppBundle:
        return AppBundle(
            meta=AppMetaConfig(name=app_name, functionalities=functionality_names),
            app_config=AppConfig(
                functionalities={name: FunctionalityConfig() for name in functionality_names}
            ),
            blueprints={},
        )

    return {
        "greeting_finance_app": bundle("greeting_finance_app", ["greeting_bot", "finance_bot"]),
        "support_app": bundle("support_app", ["support_bot"]),
    }


@pytest.fixture
def store():
    return InMemorySessionStore()


@pytest.fixture
def registry():
    return _fake_registry()


def _run(coro):
    return asyncio.run(coro)


def test_new_conversation_requires_app_and_functionality(store, registry):
    with pytest.raises(RoutingError) as exc:
        _run(resolve_session(
            conversation_id=None, app=None, functionality=None,
            session_store=store, app_registry=registry,
        ))
    assert exc.value.status_code == 400


def test_new_conversation_with_app_and_functionality_mints_id(store, registry):
    session = _run(resolve_session(
        conversation_id=None, app="greeting_finance_app", functionality="greeting_bot",
        session_store=store, app_registry=registry,
    ))
    assert session.is_new
    assert session.app == "greeting_finance_app"
    assert session.functionality == "greeting_bot"
    assert session.conversation_id  # non-empty, generated


def test_unknown_app_rejected(store, registry):
    with pytest.raises(RoutingError) as exc:
        _run(resolve_session(
            conversation_id=None, app="does_not_exist", functionality="greeting_bot",
            session_store=store, app_registry=registry,
        ))
    assert exc.value.status_code == 404


def test_unknown_functionality_for_known_app_rejected(store, registry):
    with pytest.raises(RoutingError) as exc:
        _run(resolve_session(
            conversation_id=None, app="greeting_finance_app", functionality="not_a_functionality",
            session_store=store, app_registry=registry,
        ))
    assert exc.value.status_code == 404


def test_existing_conversation_id_resolves_without_app_or_functionality(store, registry):
    async def run():
        first = await resolve_session(
            conversation_id=None, app="greeting_finance_app", functionality="finance_bot",
            session_store=store, app_registry=registry,
        )
        second = await resolve_session(
            conversation_id=first.conversation_id, app=None, functionality=None,
            session_store=store, app_registry=registry,
        )
        return first, second

    first, second = _run(run())
    assert second.app == "greeting_finance_app"
    assert second.functionality == "finance_bot"
    assert second.conversation_id == first.conversation_id
    assert not second.is_new


def test_existing_conversation_id_with_matching_app_functionality_is_fine(store, registry):
    async def run():
        first = await resolve_session(
            conversation_id=None, app="support_app", functionality="support_bot",
            session_store=store, app_registry=registry,
        )
        second = await resolve_session(
            conversation_id=first.conversation_id, app="support_app", functionality="support_bot",
            session_store=store, app_registry=registry,
        )
        return second

    second = _run(run())
    assert second.app == "support_app"


def test_existing_conversation_id_with_mismatched_app_is_rejected(store, registry):
    async def run():
        first = await resolve_session(
            conversation_id=None, app="greeting_finance_app", functionality="greeting_bot",
            session_store=store, app_registry=registry,
        )
        with pytest.raises(RoutingError) as exc:
            await resolve_session(
                conversation_id=first.conversation_id, app="support_app", functionality=None,
                session_store=store, app_registry=registry,
            )
        return exc.value

    error = _run(run())
    assert error.status_code == 409


def test_existing_conversation_id_with_mismatched_functionality_is_rejected(store, registry):
    async def run():
        first = await resolve_session(
            conversation_id=None, app="greeting_finance_app", functionality="greeting_bot",
            session_store=store, app_registry=registry,
        )
        with pytest.raises(RoutingError) as exc:
            await resolve_session(
                conversation_id=first.conversation_id, app=None, functionality="finance_bot",
                session_store=store, app_registry=registry,
            )
        return exc.value

    error = _run(run())
    assert error.status_code == 409


def test_unknown_conversation_id_without_app_functionality_is_rejected(store, registry):
    """A conversation_id the store has never seen (fresh client-generated id,
    expired session, restarted in-memory store) can't be resolved on its
    own - the caller must re-supply app/functionality to (re)start it."""
    with pytest.raises(RoutingError) as exc:
        _run(resolve_session(
            conversation_id="some-id-nobody-has-seen",
            app=None, functionality=None,
            session_store=store, app_registry=registry,
        ))
    assert exc.value.status_code == 400


def test_unknown_conversation_id_with_app_and_functionality_starts_it(store, registry):
    """A client-chosen conversation_id is honored as-is (not overwritten with
    a server-generated uuid) as long as it comes with app/functionality."""
    session = _run(resolve_session(
        conversation_id="client-chosen-id",
        app="greeting_finance_app", functionality="greeting_bot",
        session_store=store, app_registry=registry,
    ))
    assert session.conversation_id == "client-chosen-id"
    assert session.is_new
