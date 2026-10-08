"""
One-shot schema migration, run as an init container before each orchestrator
pod starts (see k8s/05-orchestrator.yaml). Safe to run concurrently from
several pods - run_migrations() serialises them with an advisory lock.

    python migrate.py
"""

import asyncio
import logging
import sys

from core.logging_utils import setup_logging
from core.persistence import get_conninfo, open_pool, run_migrations

setup_logging()
logger = logging.getLogger("migrate")


async def main() -> int:
    conninfo = get_conninfo()
    if conninfo is None:
        logger.error("Neither DATABASE_URL nor PGHOST is set; nothing to migrate.")
        return 1
    # Generous wait: on a cold `kubectl apply` Postgres can still be starting.
    pool = await open_pool(conninfo, max_size=3, wait_timeout=120)
    try:
        await run_migrations(pool)
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
