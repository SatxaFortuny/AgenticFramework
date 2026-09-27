"""
Resolves which (app, functionality) a /chat request is for.

Kept deliberately free of FastAPI/HTTPException so it can be unit tested with
plain dicts and fakes - see tests/test_routing.py. api.py is responsible for
turning RoutingError into an HTTP response.
"""
import uuid
from dataclasses import dataclass

from core.schemas import AppBundle
from core.session_store import SessionStore, new_session_record


class RoutingError(Exception):
    """Carries an HTTP-appropriate status_code so api.py doesn't have to
    re-derive one from the message text."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ResolvedSession:
    app: str
    functionality: str
    conversation_id: str
    is_new: bool


def _validate_app_and_functionality(
    app: str, functionality: str, app_registry: dict[str, AppBundle]
) -> None:
    bundle = app_registry.get(app)
    if bundle is None:
        raise RoutingError(404, f"Unknown app '{app}'.")
    if functionality not in bundle.app_config.functionalities:
        raise RoutingError(
            404, f"Unknown functionality '{functionality}' for app '{app}'."
        )


async def resolve_session(
    *,
    conversation_id: str | None,
    app: str | None,
    functionality: str | None,
    session_store: SessionStore,
    app_registry: dict[str, AppBundle],
) -> ResolvedSession:
    """
    Three cases:

    1. conversation_id given and known: return the stored (app, functionality).
       If the request *also* named an app/functionality, it must match the
       stored one - a mismatch is a client bug (or two callers racing on the
       same conversation_id with different intents) and is rejected rather
       than silently trusting whichever one showed up, per request.
    2. conversation_id missing, or given but unknown (fresh id, expired
       session, restarted in-memory store): this is treated as the start of
       a new conversation, which requires an explicit app + functionality.
       A brand-new conversation_id is minted only in the no-conversation_id
       case; if the caller supplied one, it's honored as-is (lets a client
       pick its own id scheme) as long as it isn't already bound elsewhere.
    3. Anything else missing what it needs: a 4xx RoutingError with a message
       precise enough to fix the request without guessing.
    """
    if conversation_id:
        record = await session_store.get(conversation_id)
        if record is not None:
            if app is not None and app != record.app:
                raise RoutingError(
                    409,
                    f"conversation_id '{conversation_id}' is bound to app "
                    f"'{record.app}', not '{app}'.",
                )
            if functionality is not None and functionality != record.functionality:
                raise RoutingError(
                    409,
                    f"conversation_id '{conversation_id}' is bound to "
                    f"functionality '{record.functionality}', not '{functionality}'.",
                )
            return ResolvedSession(
                app=record.app,
                functionality=record.functionality,
                conversation_id=conversation_id,
                is_new=False,
            )

    # No usable existing session - this is a new conversation.
    if not app or not functionality:
        raise RoutingError(
            400,
            "Starting a new conversation requires both 'app' and "
            "'functionality' (conversation_id alone isn't enough for a "
            "conversation the server doesn't already know).",
        )

    _validate_app_and_functionality(app, functionality, app_registry)

    resolved_conversation_id = conversation_id or str(uuid.uuid4())
    await session_store.set(
        resolved_conversation_id, new_session_record(app, functionality)
    )
    return ResolvedSession(
        app=app,
        functionality=functionality,
        conversation_id=resolved_conversation_id,
        is_new=True,
    )
