# ADR 0003: Conversation state lives in Postgres, shared by all orchestrator replicas

## Status

Accepted.

## Context

Two pieces of per-conversation state lived in orchestrator process memory:

- the LangGraph checkpointer (`InMemorySaver`): the message history, keyed by
  `thread_id == conversation_id`;
- the session store (`InMemorySessionStore`): `conversation_id -> (app,
  functionality)`, so a client names app/functionality only on its first message.

Consequences: every restart or redeploy dropped every conversation, and the
orchestrator could not run more than one replica (a request landing on a
replica that hadn't seen the conversation got a 400, or silently lost history).
Both TODOs were already written down in `core/pipeline.py` and
`core/session_store.py`, and the two stores are keyed by the same
`conversation_id`, so they have to be upgraded together - one stale without the
other is worse than both stale.

## Decision

1. **Postgres for both**, one database, one shared connection pool
   (`core/persistence.py`): `AsyncPostgresSaver` for checkpoints and a new
   `PostgresSessionStore` behind the existing `SessionStore` interface. Postgres
   is a plain backing service (StatefulSet + PVC, `k8s/01-postgres.yaml`), not
   a service we write. The orchestrator becomes stateless.

2. **Setup moves out of import time into a FastAPI `lifespan`**, because the
   async pool must be opened and closed inside the running event loop. The
   checkpointer is *injected* into `get_or_create_pipeline()` (required
   argument) instead of being a module global, so no graph can be compiled
   without deciding where its history goes.

3. **Schema migration runs in an init container** (`migrate.py`), not in the
   app, so N replicas don't all race to create tables. They still can start at
   the same moment on a rollout, so migrations are serialised with a Postgres
   advisory lock. **The lock is acquired by polling `pg_try_advisory_lock`, not
   by blocking in `pg_advisory_lock`**: LangGraph's migrations run
   `CREATE INDEX CONCURRENTLY`, which waits for every other open transaction,
   and a process blocked inside `pg_advisory_lock` is one. With the blocking
   call, concurrent migrations on an empty database deadlocked (found by
   testing, not in production; `tests/test_persistence.py` now covers it from a
   throwaway empty schema). `AUTO_MIGRATE=true` runs the same code at app
   startup, for local dev only.

4. **Connection settings use the libpq `PG*` variables** (with `DATABASE_URL`
   as an override) so the password is never URL-encoded into a string.

5. **In-memory fallback is kept** when neither is set, so unit tests and bare
   `uvicorn` dev need no database. It logs a warning.

6. **Health endpoints with different meanings.** `/healthz` (liveness) checks
   nothing external, so a database outage cannot get pods restarted into a
   thundering herd. `/readyz` (readiness) pings Postgres with a 2 s timeout, so
   a pod that can't reach its database leaves the Service and rejoins by
   itself.

7. **`PostgresSessionStore.set()` is first-writer-wins** (`ON CONFLICT DO
   NOTHING`). `resolve_session()` only calls `set()` for an id it just found
   missing, so a conflict means another replica bound that id first; keeping
   the first binding stops a later request from re-pointing an existing
   conversation at a different app/functionality.

## Alternatives considered

- **Redis for sessions, Postgres for checkpoints** - rejected: two stateful
  services to run and back up for one logical piece of state.
- **Run migrations from the app at startup (all replicas)** - rejected as the
  default for the race reasons above; kept behind `AUTO_MIGRATE` for dev.
- **pgvector instead of ChromaDB** - deliberately not done here (one change at
  a time); it is a natural follow-up that would remove a component.

## Consequences

- Existing in-memory conversations are not migrated: the first deploy starts
  with an empty history.
- **No retention yet.** `checkpoints`/`checkpoint_blobs`/`checkpoint_writes`
  grow without bound; a periodic cleanup of old threads is needed before this
  runs for long. The `sessions` table has only `created_at`, so it can't yet
  express "last active"; add a column when retention is designed.
- A single Postgres pod is a single point of failure and has no backups. Fine
  for this demo cluster; use an operator (e.g. CloudNativePG) or a managed
  database before relying on it.
- Each replica holds up to `DB_POOL_MAX` (default 10) connections. Size
  Postgres' `max_connections` for `replicas x DB_POOL_MAX`, and put PgBouncer in
  front once replicas multiply (the pool already disables prepared statements
  so that works).
- Changing the embedding model is unrelated to this ADR but note the same
  rule applies as in ADR 0002: Chroma's PVC survives restarts, so stale vectors
  do too.
