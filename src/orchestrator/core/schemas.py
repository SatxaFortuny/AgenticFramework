import os
import re
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

# --- TIER 1: Infrastructure & Security Schemas ---

class VectorDBConfig(BaseModel):
    provider: str
    collection_name: str
    # CHANGED: embedding_provider is now independent of the vectordb `provider`.
    # Previously EMBEDDING_REGISTRY was keyed by `provider` (e.g. "chromadb"),
    # which meant the vectordb backend and the embedding backend couldn't vary
    # independently (you couldn't pair, say, Qdrant with an Ollama embedder).
    # Defaults to "ollama" to match previous behaviour for existing configs.
    embedding_provider: str = "ollama"
    # Used by the "retrieve_context" pipeline node to embed the query
    # before hitting the vector store. Optional: only required if a
    # blueprint actually adds a retrieve_context node.
    embedding_model: str = "nomic-embed-text:latest"

class MCPServerConfig(BaseModel):
    server_name: str
    url: str
    transport: str = "sse"
    allowed_tools: list[str]

class ModelsConfig(BaseModel):
    provider: str
    model_name: str

class FunctionalityConfig(BaseModel):
    vectordb: list[VectorDBConfig] = []
    tools: list[MCPServerConfig] = []
    models: list[ModelsConfig]

class AppConfig(BaseModel):
    functionalities: dict[str, FunctionalityConfig]

# --- Config Loaders ---

def load_app_config(yaml_path: str) -> AppConfig:
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at {yaml_path}")

    with open(path, 'r') as file:
        raw_dict = yaml.safe_load(file)

    raw_dict = _expand_env_vars(raw_dict)
    return AppConfig(**raw_dict)

def load_blueprint(yaml_path: str) -> GraphBlueprint:
    """Helper function to load your Tier 2 blueprint yaml."""
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Blueprint file not found at {yaml_path}")
    with open(path, 'r') as file:
        raw_dict = yaml.safe_load(file)
    return GraphBlueprint(**raw_dict)
