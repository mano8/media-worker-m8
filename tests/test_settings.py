"""Tests for worker.settings — ARQ WorkerSettings + lifecycle hooks."""

import httpx
import pytest
from arq.connections import RedisSettings
from media_sdk_m8 import ObjectStorage

from worker.config import WorkerConfig
from worker.scanner import Scanner
from worker.settings import (
    WorkerSettings,
    redis_settings_from_config,
    shutdown,
    startup,
)
from worker.tasks import build_export_archive, generate_variants, scan_object


def test_redis_settings_from_config_with_user():
    cfg = WorkerConfig(
        MEDIA_REDIS_HOST="r", MEDIA_REDIS_PORT=6380, MEDIA_REDIS_USER="appuser"
    )
    settings = redis_settings_from_config(cfg)
    assert isinstance(settings, RedisSettings)
    assert settings.host == "r"
    assert settings.port == 6380
    assert settings.username == "appuser"


def test_redis_settings_from_config_blank_user_becomes_none():
    cfg = WorkerConfig(MEDIA_REDIS_USER="")
    assert redis_settings_from_config(cfg).username is None


def test_worker_settings_registers_all_tasks():
    assert WorkerSettings.functions == [
        scan_object,
        generate_variants,
        build_export_archive,
    ]
    assert isinstance(WorkerSettings.redis_settings, RedisSettings)
    assert WorkerSettings.max_tries >= 1
    assert WorkerSettings.job_timeout >= 1
    assert WorkerSettings.keep_result >= 0
    # Concurrency is bounded so peak memory stays within the container limit.
    assert WorkerSettings.max_jobs >= 1


@pytest.mark.anyio
async def test_startup_populates_ctx_and_shutdown_closes_http():
    ctx: dict = {}
    await startup(ctx)
    assert isinstance(ctx["config"], WorkerConfig)
    assert isinstance(ctx["storage"], ObjectStorage)
    assert isinstance(ctx["scanner"], Scanner)
    assert isinstance(ctx["http"], httpx.AsyncClient)

    await shutdown(ctx)
    assert ctx["http"].is_closed


@pytest.mark.anyio
async def test_shutdown_without_http_is_noop():
    await shutdown({})  # no "http" key — must not raise
