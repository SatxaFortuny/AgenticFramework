from core.eval_types import EvalCase

EVAL_CASES = [
    EvalCase(
        id="install",
        query="How do I install Fetchly and make my first request?",
        expected_source_id="quickstart",
        required_keywords=["pip install", "base_url"],
    ),
    EvalCase(
        id="default_timeout",
        query="What's the default timeout for requests if I don't set one?",
        expected_source_id="timeouts",
        required_keywords=["10 seconds"],
    ),
    EvalCase(
        id="retry_basic",
        query="How can I make requests retry automatically on server errors?",
        expected_source_id="retries",
        required_keywords=["RetryPolicy", "max_attempts"],
    ),
    EvalCase(
        id="bearer_auth",
        query="How do I authenticate using a bearer token?",
        expected_source_id="auth",
        required_keywords=["BearerAuth"],
    ),
    EvalCase(
        id="timeout_exception",
        query="What exception does Fetchly raise when a request times out?",
        expected_source_id="timeouts",
        required_keywords=["FetchlyTimeoutError"],
    ),
    EvalCase(
        id="retry_on_timeout",
        query="Does Fetchly retry connection timeouts by default?",
        expected_source_id="retries",
        required_keywords=["retry_on_timeout"],
    ),
    EvalCase(
        id="raise_for_status",
        query="How do I get Fetchly to raise an exception on a 404 response?",
        expected_source_id="errors",
        required_keywords=["raise_for_status"],
    ),
]
