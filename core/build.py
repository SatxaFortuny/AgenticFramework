"""
Thin convenience wrappers over core/factory.py's config-driven builder.
Kept for backward compatibility with main.py / main_router.py / early
eval runs -- but note these no longer hardcode any wiring themselves,
they just point at a YAML file. The real entry point for new work is
core/factory.build_pipeline_from_file() directly, or run.py.
"""

from pathlib import Path

from core.factory import build_pipeline_from_file

CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def build_default_pipeline():
    return build_pipeline_from_file(CONFIGS_DIR / "default.yaml")


def build_router_pipeline():
    return build_pipeline_from_file(CONFIGS_DIR / "router.yaml")


def build_dense_rag_pipeline():
    return build_pipeline_from_file(CONFIGS_DIR / "dense_rag.yaml")


def build_cloud_pipeline():
    return build_pipeline_from_file(CONFIGS_DIR / "cloud.yaml")


def build_resilient_pipeline():
    return build_pipeline_from_file(CONFIGS_DIR / "resilient.yaml")
