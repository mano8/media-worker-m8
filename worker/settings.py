"""ARQ worker entrypoint.

``arq worker.settings.WorkerSettings`` boots the worker: it connects to the
media-owned Redis, registers the two task functions, and — once per process —
builds the shared resources (object-storage client, scanner, HTTP client) that
every task reads from the ARQ ``ctx`` mapping.
"""

from typing import Any, ClassVar

import httpx
from arq.connections import RedisSettings
from media_sdk_m8 import ObjectStorage

from worker.config import WorkerConfig, get_config
from worker.scanner import get_scanner
from worker.tasks import generate_variants, scan_object


def redis_settings_from_config(config: WorkerConfig) -> RedisSettings:
    """Build ARQ ``RedisSettings`` from the media-owned Redis env."""
    return RedisSettings(
        host=config.MEDIA_REDIS_HOST,
        port=config.MEDIA_REDIS_PORT,
        username=config.MEDIA_REDIS_USER or None,
        password=config.redis_password,
    )


async def startup(ctx: dict[str, Any]) -> None:
    """Create per-process resources and stash them on the ARQ context."""
    config = get_config()
    ctx["config"] = config
    ctx["storage"] = ObjectStorage(config.storage_config())
    ctx["scanner"] = get_scanner(config)
    ctx["http"] = httpx.AsyncClient(timeout=config.MEDIA_API_TIMEOUT_SECONDS)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Dispose of resources created in :func:`startup`."""
    http = ctx.get("http")
    if http is not None:
        await http.aclose()


_config = get_config()


class WorkerSettings:
    """ARQ ``WorkerSettings`` consumed by the ``arq`` CLI."""

    functions: ClassVar[list] = [scan_object, generate_variants]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings_from_config(_config)
    max_tries = _config.WORKER_MAX_TRIES
    job_timeout = _config.WORKER_JOB_TIMEOUT_SECONDS
    keep_result = _config.WORKER_KEEP_RESULT_SECONDS
    # Bound how many jobs decode/render at once so peak memory stays within the
    # container limit (≈ max_jobs × per-job source/decoded ceilings, P1.2).
    max_jobs = _config.WORKER_MAX_CONCURRENT_JOBS
