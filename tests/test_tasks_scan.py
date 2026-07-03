"""Tests for worker.tasks.scan_object — streaming antivirus scan + callbacks."""

import uuid
from types import SimpleNamespace

import pytest

from media_sdk_m8 import ScanJobPayload

from worker.config import WorkerConfig
from worker.scanner import ScanVerdict
from worker.tasks import scan_object

from tests.conftest import SERVICE_TOKEN, WORKER_CLIENT_ID, FakeScanner


def _payload():
    return ScanJobPayload(
        object_id=uuid.uuid4(),
        bucket="private-media",
        object_key="cat/abc/orig.png",
        owner_user_id=uuid.uuid4(),
    )


def _ctx_with(ctx, **overrides):
    """Return ``ctx`` with a config rebuilt from the test env plus overrides."""
    ctx["config"] = WorkerConfig(**overrides)
    return ctx


@pytest.mark.anyio
async def test_clean_object_streams_and_reports_clean(ctx, storage, http):
    scanner = FakeScanner(ScanVerdict.CLEAN)
    ctx["scanner"] = scanner
    payload = _payload()

    result = await scan_object(ctx, payload)

    assert result == "clean"
    # Sized from metadata, then STREAMED — never read whole via get_object.
    storage.stat_object.assert_called_once_with(
        bucket="private-media", object_key="cat/abc/orig.png"
    )
    storage.stream_object.assert_called_once_with(
        bucket="private-media", object_key="cat/abc/orig.png"
    )
    storage.get_object.assert_not_called()
    storage.remove_object.assert_not_called()
    # The scanner consumed the streamed chunks (joined back to the object bytes).
    assert scanner.scanned == [b"source-bytes"]
    assert len(http.posts) == 1
    call = http.posts[0]
    assert call["url"].endswith(f"/v1/internal/objects/{payload.object_id}/scan-result")
    assert call["json"] == {"scan_status": "clean"}
    assert call["headers"] == {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Worker-Client": WORKER_CLIENT_ID,
    }


@pytest.mark.anyio
async def test_infected_object_is_purged_and_quarantined(ctx, storage, http):
    ctx["scanner"] = FakeScanner(ScanVerdict.INFECTED)
    payload = _payload()

    result = await scan_object(ctx, payload)

    assert result == "quarantined"
    storage.remove_object.assert_called_once_with(
        bucket="private-media", object_key="cat/abc/orig.png"
    )
    assert http.posts[0]["json"] == {"scan_status": "quarantined"}


@pytest.mark.anyio
async def test_oversized_source_is_quarantined_before_stream(ctx, storage, http):
    """A source over the scan ceiling fails closed — quarantined, never streamed."""
    ctx = _ctx_with(ctx, WORKER_MAX_SCAN_BYTES=10)
    ctx["scanner"] = FakeScanner(ScanVerdict.CLEAN)
    storage.stat_object.return_value = SimpleNamespace(
        content_type="application/octet-stream", size=11
    )
    payload = _payload()

    result = await scan_object(ctx, payload)

    assert result == "quarantined"
    storage.stream_object.assert_not_called()  # never streamed
    storage.get_object.assert_not_called()
    storage.remove_object.assert_called_once_with(
        bucket="private-media", object_key="cat/abc/orig.png"
    )
    assert http.posts[0]["json"] == {"scan_status": "quarantined"}


@pytest.mark.anyio
async def test_unknown_source_size_is_quarantined_fail_closed(ctx, storage, http):
    """A source of unknown size fails closed without streaming any bytes."""
    ctx["scanner"] = FakeScanner(ScanVerdict.CLEAN)
    storage.stat_object.return_value = SimpleNamespace(content_type="image/png")
    payload = _payload()

    result = await scan_object(ctx, payload)

    assert result == "quarantined"
    storage.stream_object.assert_not_called()
    storage.remove_object.assert_called_once()
    assert http.posts[0]["json"] == {"scan_status": "quarantined"}


@pytest.mark.anyio
async def test_transient_storage_error_propagates_for_retry(ctx, storage, http):
    ctx["scanner"] = FakeScanner(ScanVerdict.CLEAN)
    storage.stat_object.side_effect = ConnectionError("minio down")

    with pytest.raises(ConnectionError):
        await scan_object(ctx, _payload())

    storage.stream_object.assert_not_called()
    assert http.posts == []  # no verdict reported when the scan never ran
