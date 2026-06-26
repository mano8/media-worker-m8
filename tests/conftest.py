"""Shared pytest fixtures for media-worker tests.

The worker owns no database and never reaches the network in tests: the live
seams (clamd socket, imgtools render, MinIO, the media-service HTTP API) are all
replaced with fakes. Env vars are set before importing the worker package so
``WorkerConfig`` resolves to deterministic test values.
"""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

# ── 1. Set env BEFORE importing the worker package ───────────────────────────
_TEST_ENV = {
    "MEDIA_API_URL": "http://media-service:8000/media",
    "MEDIA_INTERNAL_SERVICE_TOKEN": "TestService!Token1secure",
    "MEDIA_REDIS_HOST": "127.0.0.1",
    "MEDIA_REDIS_USER": "appuser",
    "MEDIA_REDIS_PASSWORD": "TestRedis!Pass1secure",
    "MINIO_HOST": "minio",
    "MINIO_ACCESS_KEY": "minioadmin",
    "MINIO_SECRET_KEY": "TestMinio!Secret1",
    "CLAMAV_HOST": "clamav",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

SERVICE_TOKEN = _TEST_ENV["MEDIA_INTERNAL_SERVICE_TOKEN"]
WORKER_CLIENT_ID = "media-worker"  # matches WorkerConfig default

import pytest  # noqa: E402

from media_sdk_m8 import ObjectStorage  # noqa: E402

from worker.config import WorkerConfig, get_config  # noqa: E402
from worker.scanner import ScanVerdict  # noqa: E402


# ── anyio backend — restrict to asyncio (trio not installed) ─────────────────
@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    """Run anyio-marked tests only on the asyncio backend."""
    return request.param


@pytest.fixture(name="config")
def config_fixture():
    """A fresh worker config built from the test environment."""
    get_config.cache_clear()
    return get_config()


# ── Fakes ─────────────────────────────────────────────────────────────────--
class FakeScanner:
    """In-memory scanner returning a preset verdict (and recording calls)."""

    def __init__(self, verdict: ScanVerdict) -> None:
        self.verdict = verdict
        self.scanned: list[bytes] = []

    async def scan(self, data: bytes) -> ScanVerdict:
        self.scanned.append(data)
        return self.verdict


class FakeResponse:
    """Minimal httpx-like response whose ``raise_for_status`` is a no-op."""

    def raise_for_status(self) -> None:  # noqa: D102
        return None


class FakeHTTP:
    """Records POST/PATCH calls instead of issuing real HTTP requests."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.patches: list[dict] = []

    async def post(self, url, *, json=None, headers=None):  # noqa: D102
        self.posts.append({"url": url, "json": json, "headers": headers})
        return FakeResponse()

    async def patch(self, url, *, json=None, headers=None):  # noqa: D102
        self.patches.append({"url": url, "json": json, "headers": headers})
        return FakeResponse()


def make_variant_result(
    *, name, data=b"img", width=10, height=10, size_bytes=3, fmt="WEBP"
):
    """Build a duck-typed imgtools ``VariantResult`` for tests."""
    return SimpleNamespace(
        name=name,
        data=data,
        width=width,
        height=height,
        size_bytes=size_bytes,
        format=fmt,
    )


@pytest.fixture(name="storage")
def storage_fixture():
    """A MagicMock standing in for the SDK ObjectStorage client."""
    storage = MagicMock(spec=ObjectStorage)
    storage.get_object.return_value = b"source-bytes"
    storage.stat_object.return_value = SimpleNamespace(
        content_type="image/png", size=12
    )
    return storage


@pytest.fixture(name="http")
def http_fixture():
    """A recording fake HTTP client."""
    return FakeHTTP()


@pytest.fixture(name="ctx")
def ctx_fixture(config: WorkerConfig, storage, http):
    """ARQ-style context wiring config + fakes (scanner added per test)."""
    return {"config": config, "storage": storage, "http": http}
