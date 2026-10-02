# ADR 0001: Functionalities can override the app's default model

## Status

Accepted.

## Context

`app.yaml` declares an app-wide default model (`defaults.model`), and
`FunctionalityConfig.resolve()` (`core/schemas.py`) fills in that default for
any functionality that doesn't declare its own `models:` list. This is what
lets most functionalities omit `models:` entirely.

Not every functionality should use the same model, though. In the demo app,
`finance_bot` is fine running on the app's Ollama default
(`llama3.1:8b`), but `greeting_bot` is a lighter, higher-volume
conversational bot where a faster hosted model (Groq, `openai/gpt-oss-20b`)
is a better fit.

## Decision

A functionality's own `models:` entry always wins over the app default -
`resolve()` only fills in the default when `self.models` is empty. So
`greeting_bot`'s functionality YAML sets `models` explicitly:

```yaml
models:
  - provider: "groq"
    model_name: "openai/gpt-oss-20b"
```

while `finance_bot`'s YAML has no `models:` key at all, and inherits the
app's Ollama default.

## Consequences

- Per-functionality overrides mean each functionality's config file is the
  single source of truth for "what model does this bot actually use" -
  no need to cross-reference `app.yaml` to know, unless the functionality
  file itself is silent on it.
- Any functionality that overrides the model with a different *provider*
  takes on that provider's own requirements. Groq needs `GROQ_API_KEY` set
  in the environment; Ollama doesn't. This isn't checked anywhere at
  startup - a missing `GROQ_API_KEY` currently only surfaces as a runtime
  500 the first time `greeting_bot` is actually invoked (see
  `docs/postmortems/2026-09-27-crio-configmap-nested-paths.md`, Incident 3).
- Follow-up noted in that postmortem: a pre-flight check at orchestrator
  startup (fail fast if a functionality's chosen provider is missing its
  required env var) would turn this into an immediate startup failure
  instead of a runtime surprise. Not yet implemented.
