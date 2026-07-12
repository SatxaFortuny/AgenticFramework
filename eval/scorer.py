from core.eval_types import EvalCase, EvalScore
from core.types import RunResult


def score(case: EvalCase, result: RunResult, latency_seconds: float) -> EvalScore:
    retrieval_hit = None
    if case.expected_source_id is not None:
        retrieve_steps = [s for s in result.trace if s.get("step") == "retrieve"]
        retrieved_ids = {
            r["id"] for s in retrieve_steps for r in s.get("results", [])
        }
        retrieval_hit = case.expected_source_id in retrieved_ids

    if case.required_keywords:
        answer_lower = result.answer.lower()
        found = sum(1 for kw in case.required_keywords if kw.lower() in answer_lower)
        keyword_coverage = found / len(case.required_keywords)
    else:
        keyword_coverage = 1.0  # nothing required = trivially satisfied

    return EvalScore(
        case_id=case.id,
        query=case.query,
        retrieval_hit=retrieval_hit,
        keyword_coverage=keyword_coverage,
        latency_seconds=latency_seconds,
        answer=result.answer,
    )
