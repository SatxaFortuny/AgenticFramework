import logging
import os
import sys
import time

# Third-party loggers that become very chatty at DEBUG (one line per HTTP call).
_NOISY_LOGGERS = ("httpx", "httpcore")


def setup_logging() -> None:
    """
    Configures root logging once at startup. The level comes from the LOG_LEVEL
    env var (DEBUG / INFO / WARNING / ERROR), defaulting to INFO. An invalid
    value falls back to INFO instead of crashing the service.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("orchestrator").info(
        "Logging initialised at level %s", logging.getLevelName(level)
    )


def preview(value, limit: int = 200) -> str:
    """Single-line, truncated rendering of message/context contents (DEBUG use only)."""
    text = str(value).replace("\n", " ")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (+{len(text) - limit} chars)"


def elapsed_ms(start: float) -> float:
    """Milliseconds since `start` (a time.perf_counter() value)."""
    return (time.perf_counter() - start) * 1000
