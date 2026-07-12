from dataclasses import dataclass, field


@dataclass
class EvalCase:
    id: str
    query: str
    expected_source_id: str | None = None
    required_keywords: list[str] = field(default_factory=list)


@dataclass
class EvalScore:
    case_id: str
    query: str
    retrieval_hit: bool | None       
    keyword_coverage: float          
    latency_seconds: float
    answer: str
