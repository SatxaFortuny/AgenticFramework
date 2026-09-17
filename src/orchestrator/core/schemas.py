import yaml
from pathlib import Path
from pydantic import BaseModel
from typing import List, Dict, Optional

# --- TIER 2: Graph Blueprint Schemas ---

class NodeDef(BaseModel):
    id: str
    action: str

class EdgeDef(BaseModel):
    source: str
    target: str
    is_conditional: bool = False
    condition_action: Optional[str] = None

class GraphBlueprint(BaseModel):
    name: str
    functionality_ref: str
    entry_point: str
    nodes: List[NodeDef]
    edges: List[EdgeDef]

# --- TIER 1: Infrastructure & Security Schemas ---

class VectorDBConfig(BaseModel):
    provider: str
    collection_name: str
    # Used by the "retrieve_context" pipeline node to embed the query
    # before hitting the vector store. Optional: only required if a
    # blueprint actually adds a retrieve_context node.
    embedding_model: str = "nomic-embed-text:latest"

class MCPServerConfig(BaseModel):
    server_name: str
    url: str
    transport: str = "sse"
    allowed_tools: List[str]

class ModelsConfig(BaseModel):
    provider: str
    model_name: str

class FunctionalityConfig(BaseModel):
    vectordb: List[VectorDBConfig] = []
    tools: List[MCPServerConfig] = []
    models: List[ModelsConfig]

class AppConfig(BaseModel):
    functionalities: Dict[str, FunctionalityConfig]

# --- Config Loaders ---

def load_app_config(yaml_path: str) -> AppConfig:
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at {yaml_path}")

    with open(path, 'r') as file:
        raw_dict = yaml.safe_load(file)

    return AppConfig(**raw_dict)

def load_blueprint(yaml_path: str) -> GraphBlueprint:
    """Helper function to load your Tier 2 blueprint yaml."""
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Blueprint file not found at {yaml_path}")
    with open(path, 'r') as file:
        raw_dict = yaml.safe_load(file)
    return GraphBlueprint(**raw_dict)
