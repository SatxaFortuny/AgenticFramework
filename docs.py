"""
Sample document corpus for the walking skeleton.

Fictional library "Fetchly" — a small HTTP client library, invented purely
so we have a realistic, non-copyrighted docs Q&A dataset to prototype against.
Swap this for a real scraped docs set later without touching any other file.
"""

DOCUMENTS = [
    {
        "id": "quickstart",
        "title": "Quickstart",
        "text": """
To install Fetchly, run `pip install fetchly`. The core object is the
Client, which manages connection pooling and default headers.

    from fetchly import Client
    client = Client(base_url="https://api.example.com")
    response = client.get("/users/1")
    print(response.json())

By default, Client reuses a single connection pool across requests, which
is significantly faster than creating a new connection per request.
""",
    },
    {
        "id": "timeouts",
        "title": "Timeouts",
        "text": """
Every request method (get, post, put, delete) accepts a `timeout` argument
in seconds. If no timeout is passed, Client falls back to the default
timeout set when the Client was constructed, which is 10 seconds unless
overridden.

    client = Client(base_url="...", default_timeout=5)
    client.get("/slow-endpoint", timeout=30)  # overrides default for this call

If a request exceeds its timeout, Fetchly raises a `FetchlyTimeoutError`.
Fetchly does not retry timed-out requests automatically; use the retry
policy described in the Retries page if you want automatic retries.
""",
    },
    {
        "id": "retries",
        "title": "Retries",
        "text": """
Fetchly supports automatic retries via the `retry_policy` argument on
Client. A retry policy specifies the maximum number of attempts and which
status codes should trigger a retry.

    from fetchly import Client, RetryPolicy
    policy = RetryPolicy(max_attempts=3, retry_on_status=[502, 503, 504])
    client = Client(base_url="...", retry_policy=policy)

Retries use exponential backoff starting at 0.5 seconds by default. This
can be changed with the `backoff_factor` argument on RetryPolicy. Retries
do not apply to connection timeouts by default — set `retry_on_timeout=True`
on the policy to enable that.
""",
    },
    {
        "id": "auth",
        "title": "Authentication",
        "text": """
Fetchly supports three authentication modes: API key, bearer token, and
basic auth. Pass an `auth` object to the Client constructor.

    from fetchly import Client, BearerAuth
    client = Client(base_url="...", auth=BearerAuth(token="abc123"))

For API key auth, use `ApiKeyAuth(header_name="X-API-Key", key="...")`.
Auth objects are applied to every request made by that Client instance;
there is currently no way to override auth on a per-request basis.
""",
    },
    {
        "id": "errors",
        "title": "Error Handling",
        "text": """
Fetchly raises typed exceptions for different failure modes:
`FetchlyTimeoutError` for timeouts, `FetchlyConnectionError` for network
failures, and `FetchlyHTTPError` for 4xx/5xx responses (only raised if
`raise_for_status=True` is passed to the request call).

    try:
        client.get("/users/1", raise_for_status=True)
    except FetchlyHTTPError as e:
        print(e.status_code, e.response.text)

By default `raise_for_status` is False, so a 404 response is returned
normally rather than raised as an exception.
""",
    },
]
