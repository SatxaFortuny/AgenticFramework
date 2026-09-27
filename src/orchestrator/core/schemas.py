import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel

# Matches ${VAR_NAME} or ${VAR_NAME:-default}. Kept intentionally simple -
# just env var name + an optional default, no nesting.
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}")


def _expand_env_vars(value):
    """
    Recursively resolves ${VAR} / ${VAR:-default} placeholders in a value
    loaded from YAML, using the current environment. Lets committed config
    files (e.g. MCP server URLs) keep their in-cluster Kubernetes DNS names
    as the default, while a local dev environment can override them with a
    plain `export SOMETHING_URL=...` - no forked/edited config file needed.
    """
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            var_name, _, default = match.groups()
            if var_name in os.environ:
                return os.environ[var_name]
            if default is not None:
                return default
            # No env var and no default: leave the placeholder as-is so a
            # missing override fails loudly (bad URL) rather than silently
            # (empty string).
            return match.group(0)

        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at {path}")
    with open(path, "r") as file:
        raw = yaml.safe_load(file) or {}
    return _expand_env_vars(raw)


# --- TIER 2: Graph Blueprint Schemas ---

class NodeDef(BaseModel):
    id: str
    action: str


class EdgeDef(BaseModel):
    source: str
    target: str
    is_conditional: bool = False
    condition_action: str | None = None


class GraphBlueprint(BaseModel):
    name: str
    functionality_ref: str
    entry_point: str
    nodes: list[NodeDef]
    edges: list[EdgeDef]

    def validate_structure(self) -> None:
        """Structural checks that don't require the running process's
        registries (ACTION_REGISTRY/CONDITION_REGISTRY live in core/pipeline.py
        and would create a circular import). Registry-membership checks still
        happen in _build_pipeline; this catches the cheaper, load-time-visible
        mistakes so they fail at startup, not mid-request."""
        node_ids = {node.id for node in self.nodes}

        if len(node_ids) != len(self.nodes):
            raise ValueError(f"Blueprint '{self.name}' has duplicate node ids.")

        if self.entry_point not in node_ids:
            raise ValueError(
                f"Blueprint '{self.name}' entry_point '{self.entry_point}' "
                f"is not a defined node."
            )

        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(
                    f"Blueprint '{self.name}' edge source '{edge.source}' "
                    f"is not a defined node."
                )
            if edge.target not in node_ids:
                raise ValueError(
                    f"Blueprint '{self.name}' edge target '{edge.target}' "
                    f"is not a defined node."
                )
            if edge.is_conditional and not edge.condition_action:
                raise ValueError(
                    f"Blueprint '{self.name}' edge {edge.source}->{edge.target} "
                    f"is conditional but has no condition_action."
                )

        if any(node.action == "retrieve_context" for node in self.nodes):
            # Presence of a vectordb is functionality-specific, so the actual
            # check happens in load_app() where the resolved FunctionalityConfig
            # is available; this flag lets that caller know to check.
            pass


# --- TIER 1: Infrastructure & Security Schemas ---

class VectorDBConfig(BaseModel):
    provider: str
    collection_name: str
    # embedding_provider is independent of the vectordb `provider`, so a
    # vectordb backend and an embedding backend can be swapped independently
    # (e.g. Chroma paired with an OpenAI embedder).
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text:latest"


class MCPServerConfig(BaseModel):
    server_name: str
    url: str
    transport: str = "sse"
    allowed_tools: list[str]


class ModelsConfig(BaseModel):
    # Optional so a functionality can omit `models` entirely and inherit the
    # app-level default model instead (see FunctionalityConfig.resolve()).
    provider: str | None = None
    model_name: str | None = None


class FunctionalityConfig(BaseModel):
    vectordb: list[VectorDBConfig] = []
    tools: list[MCPServerConfig] = []
    models: list[ModelsConfig] = []

    def resolve(self, defaults: "AppDefaults") -> "FunctionalityConfig":
        """Return an *effective* FunctionalityConfig with app-level defaults
        merged in for fields this functionality left unset. Today only
        `models` is inheritable: a functionality with no models of its own
        falls back to a single model built from the app's default provider/
        model_name. Everything else (vectordb, tools) must be set per
        functionality - there's no sane app-wide default for those."""
        if self.models:
            return self
        if defaults.model.provider and defaults.model.model_name:
            return self.model_copy(update={
                "models": [ModelsConfig(
                    provider=defaults.model.provider,
                    model_name=defaults.model.model_name,
                )]
            })
        return self


class AppConfig(BaseModel):
    """Kept intentionally identical in shape to the old flat AppConfig
    (functionality_name -> effective FunctionalityConfig) so core/factory.py
    and core/pipeline.py don't need to change for this batch - only *how*
    this object gets built changes."""
    functionalities: dict[str, FunctionalityConfig]


# --- App-level (Tier 0) schema ---

class ModelDefaults(BaseModel):
    provider: str | None = None
    model_name: str | None = None


class AppDefaults(BaseModel):
    model: ModelDefaults = ModelDefaults()


class AppMetaConfig(BaseModel):
    """Parsed from configs/{app}/app.yaml. Settings here apply to the whole
    app; `functionalities` is the allowlist of functionality names this app
    exposes, each backed by configs/{app}/functionalities/{name}.yaml and
    configs/{app}/blueprints/{name}.yaml."""
    name: str
    description: str = ""
    functionalities: list[str]
    defaults: AppDefaults = AppDefaults()


@dataclass
class AppBundle:
    """Everything resolved for one app: metadata, effective (defaults-merged)
    functionality configs, and validated blueprints - one per functionality."""
    meta: AppMetaConfig
    app_config: AppConfig
    blueprints: dict[str, GraphBlueprint]


# --- Loaders ---

def load_blueprint(yaml_path: str) -> GraphBlueprint:
    raw = _load_yaml(Path(yaml_path))
    blueprint = GraphBlueprint(**raw)
    blueprint.validate_structure()
    return blueprint


def load_app_config(yaml_path: str) -> AppConfig:
    """Legacy loader for a single flat config.yaml (functionality_name ->
    FunctionalityConfig, no app-level defaults). Kept for backwards
    compatibility with configs written before the app/ directory layout;
    prefer load_app() for anything new."""
    raw = _load_yaml(Path(yaml_path))
    return AppConfig(**raw)


def load_app(app_dir: str) -> AppBundle:
    """Load an app from the configs/{app}/ directory layout:

        configs/{app}/app.yaml
        configs/{app}/functionalities/{name}.yaml
        configs/{app}/blueprints/{name}.yaml

    Every name in app.yaml's `functionalities` list must have a matching
    functionality file and blueprint file. Raises ValueError/FileNotFoundError
    at load time (i.e. at process startup, not mid-request) for anything
    structurally wrong - a missing file, a functionality with neither its own
    models nor a usable app default, a blueprint whose entry_point or edges
    reference a node that doesn't exist, or a retrieve_context node with no
    vectordb configured for that functionality.
    """
    base = Path(app_dir)
    meta = AppMetaConfig(**_load_yaml(base / "app.yaml"))

    if not meta.functionalities:
        raise ValueError(f"App '{meta.name}' declares no functionalities.")

    resolved_functionalities: dict[str, FunctionalityConfig] = {}
    blueprints: dict[str, GraphBlueprint] = {}

    for functionality_name in meta.functionalities:
        func_path = base / "functionalities" / f"{functionality_name}.yaml"
        raw_func = _load_yaml(func_path)
        raw_config = FunctionalityConfig(**raw_func)
        effective_config = raw_config.resolve(meta.defaults)

        if not effective_config.models:
            raise ValueError(
                f"Functionality '{functionality_name}' in app '{meta.name}' has "
                f"no models configured and the app defines no default model "
                f"provider/model_name to fall back to."
            )
        for model in effective_config.models:
            if not model.provider or not model.model_name:
                raise ValueError(
                    f"Functionality '{functionality_name}' in app '{meta.name}' "
                    f"has a model entry missing provider/model_name."
                )

        blueprint_path = base / "blueprints" / f"{functionality_name}.yaml"
        blueprint = load_blueprint(str(blueprint_path))

        if blueprint.functionality_ref != functionality_name:
            raise ValueError(
                f"Blueprint for '{functionality_name}' in app '{meta.name}' has "
                f"functionality_ref='{blueprint.functionality_ref}', which "
                f"doesn't match its own file name/registration."
            )

        needs_vectordb = any(node.action == "retrieve_context" for node in blueprint.nodes)
        if needs_vectordb and not effective_config.vectordb:
            raise ValueError(
                f"Blueprint '{blueprint.name}' (functionality="
                f"'{functionality_name}') uses a retrieve_context node but "
                f"'{functionality_name}' has no vectordb configured."
            )

        resolved_functionalities[functionality_name] = effective_config
        blueprints[functionality_name] = blueprint

    app_config = AppConfig(functionalities=resolved_functionalities)
    return AppBundle(meta=meta, app_config=app_config, blueprints=blueprints)


def discover_apps(configs_root: str = "configs") -> dict[str, AppBundle]:
    """
    Scans configs_root for app directories (any subdirectory containing an
    app.yaml) and load_app()'s each one. This is what makes "app" a real,
    multi-valued concept at runtime instead of one hardcoded path - adding a
    new app is just adding a new configs/{app}/ directory, no code change.

    Raises whatever load_app() raises (FileNotFoundError, ValueError) for any
    individual app - one broken app's config fails the whole startup rather
    than silently serving a partial app registry, since a half-loaded
    registry is worse than a clear boot-time error.
    """
    root = Path(configs_root)
    if not root.exists():
        raise FileNotFoundError(f"Configs root not found at {root}")

    bundles: dict[str, AppBundle] = {}
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / "app.yaml").exists():
            bundle = load_app(str(entry))
            if bundle.meta.name in bundles:
                raise ValueError(
                    f"Duplicate app name '{bundle.meta.name}' "
                    f"(directory '{entry.name}')."
                )
            bundles[bundle.meta.name] = bundle
    return bundles
