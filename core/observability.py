"""
Structured observability: every run gets appended as one JSON line to a
per-pipeline log file. Piggybacks on RunResult.trace (already required by
the Orchestrator interface since Phase 1) rather than building separate
instrumentation -- the trace already has everything worth inspecting.

Deliberately simple: JSONL + grep/jq is enough to debug a handful of
adapters. Swap for OpenTelemetry spans later if this ever needs to be
queried at scale -- same principle as everything else in this project,
don't build it until something needs it.
"""

import json
import time
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"


def log_run(pipeline_label: str, query: str, answer: str, trace: list[dict],
            latency_seconds: float) -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": time.time(),
        "pipeline": pipeline_label,
        "query": query,
        "answer": answer,
        "trace": trace,
        "latency_seconds": latency_seconds,
    }
    path = LOG_DIR / f"{pipeline_label}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return path
