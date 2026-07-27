"""
Server-side identity resolution.

The whole point: the client never says who it is. The API key is the only
credential, and the key deterministically maps to an app_id + which pipeline
config that app is wired to. Swap this file's backing store (yaml -> DB/Vault)
without touching main.py.
"""
from dataclasses import dataclass
from pathlib import Path
import yaml
from fastapi import Header, HTTPException, status

API_KEYS_FILE = Path(__file__).parent / "api_keys.yaml"


@dataclass(frozen=True)
class AppIdentity:
    app_id: str
    config_path: str


def _load_keys() -> dict[str, AppIdentity]:
    raw = yaml.safe_load(API_KEYS_FILE.read_text()) or {}
    return {
        key: AppIdentity(app_id=v["app_id"], config_path=v["config_path"])
        for key, v in raw.items()
    }


# Loaded once at import time. Restart to pick up new keys, or swap for a
# live-lookup (DB) if you need hot rotation.
_KEYS = _load_keys()


def resolve_identity(authorization: str = Header(...)) -> AppIdentity:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Expected 'Bearer <api_key>'")
    api_key = authorization.removeprefix("Bearer ").strip()
    identity = _KEYS.get(api_key)
    if identity is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return identity
