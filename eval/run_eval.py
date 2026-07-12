import argparse
import json
import time
from pathlib import Path

from core.build import build_default_pipeline
from eval.cases import EVAL_CASES
from eval.scorer import score

RESULTS_DIR = Path(__file__).parent / "results"


def run(label: str) -> list:
    orchestrator, context = build_default_pipeline()
    scores = []

    for case in EVAL_CASES:
        start = time.perf_counter()
        result = orchestrator.run(case.query, context)
        elapsed = time.perf_counter() - start

        s = score(case, result, elapsed)
        scores.append(s)

        hit_str = "-" if s.retrieval_hit is None else ("HIT" if s.retrieval_hit else "MISS")
        print(f"[{s.case_id:20s}] retrieval={hit_str:4s}  "
              f"keywords={s.keyword_coverage:.0%}  latency={s.latency_seconds:.1f}s")

    n = len(scores)
    retrieval_checked = [s for s in scores if s.retrieval_hit is not None]
    retrieval_hit_rate = (
        sum(s.retrieval_hit for s in retrieval_checked) / len(retrieval_checked)
        if retrieval_checked else None
    )
    avg_keyword_coverage = sum(s.keyword_coverage for s in scores) / n
    avg_latency = sum(s.latency_seconds for s in scores) / n

    print("\n--- summary ---")
    print(f"cases:               {n}")
    if retrieval_hit_rate is not None:
        print(f"retrieval hit rate:  {retrieval_hit_rate:.0%}")
    print(f"avg keyword coverage: {avg_keyword_coverage:.0%}")
    print(f"avg latency:          {avg_latency:.1f}s")

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{label}.json"
    with out_path.open("w") as f:
        json.dump(
            {
                "label": label,
                "cases": n,
                "retrieval_hit_rate": retrieval_hit_rate,
                "avg_keyword_coverage": avg_keyword_coverage,
                "avg_latency_seconds": avg_latency,
                "scores": [vars(s) for s in scores],
            },
            f,
            indent=2,
        )
    print(f"\nsaved -> {out_path}")

    return scores


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="baseline_sequential_tfidf_ollama")
    args = parser.parse_args()
    run(args.label)
