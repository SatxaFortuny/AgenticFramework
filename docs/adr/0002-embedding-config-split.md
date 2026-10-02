# ADR 0002: Embedding config is separate from vectordb config

## Status

Accepted.

## Context

`VectorDBConfig` originally held both vectordb fields (`provider`,
`collection_name`) *and* embedding fields (`embedding_provider`,
`embedding_model`). Functionally this wasn't actually coupled -
`core/factory.py`'s `create_vectordb()` only ever read the vectordb fields,
and `create_embedder()` only ever read the embedding fields, each keyed off
its own registry (`VECTORDB_REGISTRY`, `EMBEDDING_REGISTRY`) - but the
*schema* implied a coupling that the project's own interfaces
(`IVectorDB`, `IEmbeddingModel`) were explicitly designed to avoid: a
vectordb only loads and stores vectors, and shouldn't need to know which
embedding backend produced them, so either should be swappable
independently.

A related, separate question came up alongside this: should a missing
embedding provider/model silently fall back to a hardcoded default
(`"ollama"` / `"nomic-embed-text:latest"`), the way models fall back to an
app-level default via `AppDefaults`/`resolve()`?

## Decision

1. **Split `EmbeddingConfig` out as its own Pydantic model**, separate from
   `VectorDBConfig`. `FunctionalityConfig` now has two independent lists,
   `vectordb` and `embedding`, instead of one list carrying both concerns.
   `create_vectordb()` takes a `VectorDBConfig`; `create_embedder()` takes an
   `EmbeddingConfig`. Neither needs to know the other exists.

2. **No fallback default for embedding config.** Unlike models, `provider`
   and `model_name` on `EmbeddingConfig` have no default value - a
   functionality that uses a vectordb must declare its embedding backend
   explicitly in its own YAML. Omitting it is a validation error at
   config-load time, not a silent default.

## Alternatives considered

- **Centralized fallback (an `embedding:` block under `app.yaml`'s
  `defaults:`, mirroring how `model` defaults already work)** - rejected for
  now, in favor of "required, no fallback." Revisit if a second embedding
  backend is ever added and the boilerplate of repeating the same
  provider/model in every functionality's YAML becomes a real pain point,
  since today there's exactly one embedding backend registered
  (`EMBEDDING_REGISTRY = {"ollama": EmbedModelOllama}`), making a fallback
  mechanism solve a problem that doesn't exist yet.
- **A single global `configs/defaults.yaml`, layered under each app's own
  `defaults:`** - a reasonable idea in general (reduces per-app
  boilerplate for values that are expected to usually agree across apps),
  but a larger structural change than this cleanup pass intended, and not
  specific to embeddings. Noted as a possible future direction, not
  pursued here.

## Consequences

- `vectordb[i]` and `embedding[i]` are two separate lists with no explicit
  link between entries. The pipeline (`core/pipeline.py`) currently only
  uses `vectordb[0]` and `embedding[0]` together, matched purely by index -
  nothing enforces that pairing. This is fine while each functionality has
  at most one of each, and would need an explicit link (e.g. an id/ref
  field) if a functionality ever needs more than one vectordb.
- `core/schemas.py`'s `load_app()` now checks that a functionality with a
  `retrieve_context` node has *both* a `vectordb` entry and an `embedding`
  entry, not just a `vectordb` entry - this check was previously
  incomplete (it only verified `vectordb`, since `embedding_provider`/
  `embedding_model` living inside `VectorDBConfig` made "has a vectordb"
  and "has embedding config" look like the same check before the split).
- Every functionality YAML that uses a vectordb needs an `embedding:` block
  added (both existing ones, `finance_bot` and `greeting_bot`, already do).
