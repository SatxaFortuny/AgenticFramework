"""
In this file we define the data types and we also handle the translation from a config file to a data type, which are python classes. We accomplish this with pydantic.
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

# Regex that finds placeholders of the form ${NAME} or ${NAME:-default}. NAME
# is an environment variable name: it must begin with a letter or underscore,
# followed by letters, digits or underscores. `default` is the fallback used
# when that environment variable is not set. Captures two groups:
# (1) the name and (2) the default (None if there isn't one).
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env_vars(value):
    """Replaces each ${NAME} / ${NAME:-default} placeholder in a value loaded from YAML
    with the environment variable NAME, or with `default` if NAME isn't set.
    It works recursively on dicts and lists. Only strings are modified, since
    a placeholder is text and only a string can contain one. Dict keys are
    never expanded, only values.
    """

    if isinstance(value, str):
        def _replace(match: re.Match) -> str:
            # Split the placeholder into the variable name and its default.
            var_name, default = match.groups()

            # 1. The variable is set: use its value from the environment.
            if var_name in os.environ:
                return os.environ[var_name]
            # 2. Not set, but there's a default: use the default.
            if default is not None:
                return default

            # 3. Not set and no default: keep the placeholder text as-is, so
            # the config fails loudly later (and shows what was missing)
            # instead of silently becoming an empty string.
            return match.group(0)

        # .sub() scans `value` for every placeholder and calls _replace once
        # per match. Whatever _replace returns takes that placeholder's place.
        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


def _load_yaml(path: Path) -> dict:
    """
    Reads one YAML file and returns its content as a plain dict, with the
    environment-variable placeholders already expanded. Every loader below
    reads its files through this function.

    (The leading underscore is a Python convention: "internal helper, not
    meant to be used from other files".)
    """
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at {path}")
    with open(path, "r") as file:
        # safe_load only builds plain data (dicts, lists, strings...). The
        # non-safe yaml.load can build arbitrary Python objects from a file,
        # which is a security risk. An empty file makes safe_load return None,
        # so `or {}` turns it into an empty dict.
        raw = yaml.safe_load(file) or {}
    return _expand_env_vars(raw)


"""
The configuration is split into 3 tiers:
    - Tier 0. The overall app configuration. Default configurations and functionalities.
    - Tier 1. The functionality. One single app might have different chatbots or internal agents, so in order to account for that we created this second tier. It containts a more concrete configuration.
    - Tier 2. One functionality might have different preset LangGraph graphs, this is what blueprints are. It contains the nodes and the edges.
"""

# --- TIER 2: Graph Blueprint Schemas ---

class NodeDef(BaseModel):
    """One step of the graph."""
    id: str        # unique name of the node.
    action: str    # id of the action the node does. The actions are in ACTION_REGISTRY (core/pipeline.py).


class EdgeDef(BaseModel):
    """
    An edge between two nodes. If is_conditional=False it always chooses that
    edge. If it's true, it calls the condition_action function (looked up in
    CONDITION_REGISTRY, core/pipeline.py) to decide. LangGraph can choose
    multiple edges at the same time and start a parallel execution, which
    means the blueprint declaration doesn't work in a conventional if/else
    order - see the discussion of this in the project notes before relying
    on a node having more than one outgoing edge.

    Known limitation, not yet fixed: a conditional edge's actual destination
    mapping is hardcoded in core/pipeline.py to {"execute_tools": target, END:
    END}, so every condition_action in the whole project is currently forced
    to return exactly "execute_tools" or END. There is no field here yet to
    let an edge declare what its own condition function returns (e.g. a
    condition_value field), which is what would be needed to support more
    than one kind of conditional routing.
    """
    source: str
    target: str
    is_conditional: bool = False        # Must be a bool. Default to False.
    condition_action: str | None = None # Can be a string or None. Default to None.


class GraphBlueprint(BaseModel):
    name: str
    functionality_ref: str    # name of the functionality this graph belongs to
    entry_point: str          # the id of the first node
    nodes: list[NodeDef]
    edges: list[EdgeDef]

    def validate_structure(self) -> None:
        """Basic structural checks. Other checks are also done in pipeline.py"""

        # A set of all node ids. A set can't hold duplicates, so if it is
        # smaller than the list of nodes, some id was used twice.
        node_ids = {node.id for node in self.nodes}

        # Duplicate node id check
        if len(node_ids) != len(self.nodes):
            raise ValueError(f"Blueprint '{self.name}' has duplicate node ids.")
        if self.entry_point not in node_ids:
            raise ValueError(
                f"Blueprint '{self.name}' entry_point '{self.entry_point}' "
                f"is not a defined node."
            )

        for edge in self.edges:
            # Source node check
            if edge.source not in node_ids:
                raise ValueError(
                    f"Blueprint '{self.name}' edge source '{edge.source}' "
                    f"is not a defined node."
                )

            # Target node check
            if edge.target not in node_ids:
                raise ValueError(
                    f"Blueprint '{self.name}' edge target '{edge.target}' "
                    f"is not a defined node."
                )

            # Condition function existence check
            if edge.is_conditional and not edge.condition_action:
                raise ValueError(
                    f"Blueprint '{self.name}' edge {edge.source}->{edge.target} "
                    f"is conditional but has no condition_action."
                )


# --- TIER 1: Infrastructure & Security Schemas ---

class EmbeddingConfig(BaseModel):
    """
    Which embedding backend turns text into vectors (see IEmbeddingModel) and
    which model it runs. Deliberately its own model, separate from
    VectorDBConfig: a vectordb only loads/stores vectors and doesn't need to
    know how they were produced, so coupling the two would contradict the
    whole point of having IEmbeddingModel/IVectorDB as independent
    interfaces. core/factory.py's create_vectordb/create_embedder already
    only ever read their own side of this split.

    No defaults on purpose: a functionality that uses a vectordb must say
    explicitly which embedding backend it relies on, rather than silently
    inheriting a hardcoded default (see also ModelDefaults/AppDefaults below,
    which is the inheritance mechanism used for models instead - embeddings
    don't have an app-level fallback the same way, at least for now).

    Same pair (provider + model) must be used to store documents and to
    query them, since vectors from different models can't be compared. Note
    ":latest"-style tags are moving targets: if the tag ever points to a
    different version, vectors stored earlier no longer match new ones -
    pin a specific version in the YAML to avoid that.
    """
    provider: str
    model_name: str


class VectorDBConfig(BaseModel):
    """
    One vector database a functionality can search (see IVectorDB).

    - provider: which database implementation to use (e.g. "chromadb").
      core/factory.py turns this name into the actual class.
    - collection_name: the named group of documents inside the database
      (roughly like a table). Each bot uses its own, e.g. "financial_reports".
    """
    provider: str
    collection_name: str


class MCPServerConfig(BaseModel):
    """
    In this component of the pipeline, we are leaving MCP as the only possible
    tools provider. This is because MCP is an industry standard and it already
    implements swappability by itself, so we would be doing an unnecessary
    double compatibility layer.
    """
    server_name: str
    url: str
    # No default: a typo here used to pass validation silently (plain str)
    # and only fail later, inside MultiServerMCPClient, with a less clear
    # error. Only "sse" is actually exercised end-to-end today - the MCP
    # servers in src/tools still hardcode mcp.sse_app(), so setting
    # "streamable_http" here would pass config validation but fail at
    # runtime until the servers themselves support it too.
    transport: Literal["sse", "streamable_http"]
    allowed_tools: list[str]    # For security reasons, only the listed tools here will be the ones used by the agents.


class ModelConfig(BaseModel):
    provider: str | None = None
    model_name: str | None = None


class FunctionalityConfig(BaseModel):
    """
    Everything one functionality (one bot) is allowed to use, as read from
    functionalities/{name}.yaml.

    - embedding: the embedding backend(s) available to it (see EmbeddingConfig).
    - vectordb: the vector databases it can search.
    - tools: the MCP servers (and tools) it can call.
    - models: the LLMs it can use.

    All four default to an empty list - not all of them are mandatory for
    every functionality (e.g. greeting_bot has no vectordb). An empty list
    is also the safe choice: code that loops over config.tools/.vectordb/
    etc. just runs zero times on an empty list, whereas a `None` default
    would need a None-check everywhere it's read before iterating.
    (In plain Python a mutable default like [] is a classic trap because it
    is shared between instances; Pydantic gives each instance its own copy,
    so it is safe here.)

    Today the pipeline only uses the first entry of each list; the lists
    leave room for more. vectordb[0] and embedding[0] are assumed to
    correspond to each other positionally - nothing enforces that pairing
    yet, so it only holds because each functionality currently has at most
    one of each.
    """
    embedding: list[EmbeddingConfig] = []
    vectordb: list[VectorDBConfig] = []
    tools: list[MCPServerConfig] = []
    models: list[ModelConfig] = []

    def resolve(self, defaults: "AppDefaults") -> "FunctionalityConfig":
        """
        Fills in the app's default model if this functionality didn't set
        its own. Only models are handled this way today - embedding/vectordb/
        tools have no equivalent app-level fallback, so a functionality that
        needs them must set them itself (see EmbeddingConfig's docstring).

        Never raises: a functionality that ends up with no models after this
        (no own models AND no usable app default) is still returned as-is.
        load_app() is what turns that into an error, since it's the first
        place both the functionality and the app's defaults have already
        been combined.
        """
        if self.models:
            return self
        if defaults.model.provider and defaults.model.model_name:
            # model_copy() clones this object with one field replaced,
            # rather than mutating self in place - the original parsed-from-
            # YAML object may still be referenced elsewhere.
            return self.model_copy(update={
                "models": [ModelConfig(
                    provider=defaults.model.provider,
                    model_name=defaults.model.model_name,
                )]
            })
        return self


class AppConfig(BaseModel):
    """
    The resolved Tier 1 config for every functionality in an app, keyed by
    functionality name. Built by load_app() - not parsed directly from any
    single YAML file. Compare with AppMetaConfig.functionalities, which is
    just the list of names declared in app.yaml, before any functionality
    file has even been read.
    """
    functionalities: dict[str, FunctionalityConfig]


# --- App-level (Tier 0) schema ---

class ModelDefaults(BaseModel):
    provider: str | None = None
    model_name: str | None = None


class AppDefaults(BaseModel):
    model: ModelDefaults = ModelDefaults()


class AppMetaConfig(BaseModel):
    """
    Parsed from configs/{app}/app.yaml. Settings here apply to the whole app.

    - name: the app's name. It is also the key of the app registry and what
      clients send as `app` in a request (it is not the folder name).
    - description: free text for humans.
    - functionalities: the allowlist of functionality names this app exposes,
      each backed by configs/{app}/functionalities/{name}.yaml and
      configs/{app}/blueprints/{name}.yaml. Files in those folders that
      aren't listed here are ignored.
    - defaults: values inherited by the functionalities (see AppDefaults).
    """
    name: str
    description: str = ""
    functionalities: list[str]
    defaults: AppDefaults = AppDefaults()


@dataclass
class AppBundle:
    """
    Everything load_app() produces for one app, bundled together. A plain
    dataclass instead of a Pydantic model because it only holds objects that
    were already validated (AppMetaConfig, AppConfig, each GraphBlueprint) -
    there is nothing left to parse here.
    """
    meta: AppMetaConfig                    # Tier 0
    app_config: AppConfig                  # Tier 1
    blueprints: dict[str, GraphBlueprint]  # Tier 2


# --- Loaders ---

def load_blueprint(yaml_path: str) -> GraphBlueprint:
    """Reads one blueprint file, builds a GraphBlueprint and validates it."""
    raw = _load_yaml(Path(yaml_path))
    blueprint = GraphBlueprint(**raw)
    # Pydantic only checked the fields individually. validate_structure()
    # checks the graph as a whole (duplicate ids, dangling references...).
    blueprint.validate_structure()
    return blueprint


def load_app_config(yaml_path: str) -> AppConfig:
    """
    Legacy loader: reads a single file straight into an AppConfig, with no
    app.yaml, no defaults, no blueprints. Kept for whichever callers/tests
    still use the old one-file-per-app format. New code should use load_app().
    """
    raw = _load_yaml(Path(yaml_path))
    return AppConfig(**raw)


def load_app(app_dir: str) -> AppBundle:
    """
    Loads one app directory end to end: app.yaml (Tier 0), then each
    functionality it lists (Tier 1) with its blueprint (Tier 2), and returns
    everything bundled together, already validated.

    Expected layout:
        {app_dir}/app.yaml
        {app_dir}/functionalities/{name}.yaml
        {app_dir}/blueprints/{name}.yaml

    Only the names listed in app.yaml's `functionalities` are loaded (the
    allowlist); files in those folders that aren't listed are ignored.
    Raises ValueError/FileNotFoundError for anything structurally wrong, so
    a broken app fails at startup instead of mid-request.
    """
    base = Path(app_dir)
    meta = AppMetaConfig(**_load_yaml(base / "app.yaml"))

    # Fail early if the app doesn't even point at any functionality.
    if not meta.functionalities:
        raise ValueError(f"App '{meta.name}' declares no functionalities.")

    resolved_functionalities: dict[str, FunctionalityConfig] = {}
    blueprints: dict[str, GraphBlueprint] = {}

    for functionality_name in meta.functionalities:
        # --- Tier 1: the functionality's resources ---
        func_path = base / "functionalities" / f"{functionality_name}.yaml"
        raw_func = _load_yaml(func_path)
        raw_config = FunctionalityConfig(**raw_func)
        # Merge in the app defaults (e.g. inherit the app's model).
        effective_config = raw_config.resolve(meta.defaults)

        # After merging, the functionality must end up with at least one
        # model, and every model entry must be complete. resolve() itself
        # never raises; this is where the "nothing to fall back to" case
        # from resolve() actually turns into an error.
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

        # --- Tier 2: the functionality's graph ---
        blueprint_path = base / "blueprints" / f"{functionality_name}.yaml"
        blueprint = load_blueprint(str(blueprint_path))

        # The blueprint file lives under this functionality's name, so it
        # should also say so internally. Catches a copy-pasted blueprint
        # whose functionality_ref was never updated.
        if blueprint.functionality_ref != functionality_name:
            raise ValueError(
                f"Blueprint for '{functionality_name}' in app '{meta.name}' has "
                f"functionality_ref='{blueprint.functionality_ref}', which "
                f"doesn't match its own file name/registration."
            )

        # A retrieve_context node needs both something to retrieve from
        # (vectordb) and something to turn the query into a vector with
        # (embedding) - core/pipeline.py's make_retrieve_context_node()
        # calls create_vectordb() and create_embedder() unconditionally once
        # it decides the node is needed, so both have to be present here,
        # not just vectordb. This is the only place the blueprint (Tier 2)
        # and the functionality's own config (Tier 1) are both available
        # together, which is why this check can't live in validate_structure().
        needs_vectordb = any(node.action == "retrieve_context" for node in blueprint.nodes)
        if needs_vectordb and not effective_config.vectordb:
            raise ValueError(
                f"Blueprint '{blueprint.name}' (functionality="
                f"'{functionality_name}') uses a retrieve_context node but "
                f"'{functionality_name}' has no vectordb configured."
            )
        if needs_vectordb and not effective_config.embedding:
            raise ValueError(
                f"Blueprint '{blueprint.name}' (functionality="
                f"'{functionality_name}') uses a retrieve_context node but "
                f"'{functionality_name}' has no embedding configured."
            )

        resolved_functionalities[functionality_name] = effective_config
        blueprints[functionality_name] = blueprint

    app_config = AppConfig(functionalities=resolved_functionalities)
    return AppBundle(meta=meta, app_config=app_config, blueprints=blueprints)


def discover_apps(configs_root: str = "configs") -> dict[str, AppBundle]:
    """
    Scans configs_root for every app directory (any subdir with an app.yaml)
    and calls load_app() on each one. This is what makes "app" a dynamic,
    file-system-driven registry instead of a hardcoded list: dropping a new
    folder with an app.yaml under configs/ is enough to register a new app.

    Returns a dict keyed by each app's `name` (from app.yaml), not by its
    folder name - the two don't have to match.
    """
    root = Path(configs_root)
    if not root.exists():
        raise FileNotFoundError(f"Configs root not found at {root}")

    bundles: dict[str, AppBundle] = {}
    for entry in sorted(root.iterdir()):
        # Only directories that contain an app.yaml count as apps; anything
        # else under configs_root (stray files, unrelated folders) is skipped.
        if entry.is_dir() and (entry / "app.yaml").exists():
            bundle = load_app(str(entry))
            # The registry is keyed by the name written inside app.yaml, not
            # the folder name, so two folders could accidentally declare the
            # same app name. Catch that instead of silently overwriting one.
            if bundle.meta.name in bundles:
                raise ValueError(
                    f"Duplicate app name '{bundle.meta.name}' "
                    f"(directory '{entry.name}')."
                )
            bundles[bundle.meta.name] = bundle
    return bundles
