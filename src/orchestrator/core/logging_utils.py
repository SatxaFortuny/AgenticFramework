import logging
import os
import sys
import time

# These libraries generate too much logs in DEBUG. I we left them we would have problems finding other logs.
_NOISY_LOGGERS = ("httpx", "httpcore")


def setup_logging() -> None:
    level_name = os.getenv(
        "LOG_LEVEL", "INFO"
    ).upper()  # We read the log level. Default is INFO.
    # Each log level is codified into an int. DEBUG(10), INFO(20), WARNING(30)...
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
