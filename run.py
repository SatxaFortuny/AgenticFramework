"""
The actual "swap a component via a single parameter" demo:

    python run.py --config configs/default.yaml   --query "How do I retry a request?"
    python run.py --config configs/router.yaml     --query "What time is it?"
    python run.py --config configs/dense_rag.yaml  --query "How do I retry a request?"
    python run.py --config configs/cloud.yaml      --query "How do I retry a request?"

Same query, different config file, different orchestration/retrieval/model
strategy -- zero code changes. Every run is logged to logs/<config-name>.jsonl.
"""

import argparse
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # picks up GROQ_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY, etc. from .env

from core import build_pipeline_from_file
from core.observability import log_run

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to a YAML pipeline config")
    parser.add_argument("--query", required=True)
    args = parser.parse_args()

    orchestrator, context = build_pipeline_from_file(args.config)

    start = time.perf_counter()
    result = orchestrator.run(args.query, context)
    latency = time.perf_counter() - start

    print(f"Q: {args.query}\n")
    print("A:", result.answer)
    print("\n--- trace ---")
    for step in result.trace:
        print(" ", step)
    print(f"\nlatency: {latency:.1f}s")

    label = Path(args.config).stem
    log_path = log_run(label, args.query, result.answer, result.trace, latency)
    print(f"logged -> {log_path}")
