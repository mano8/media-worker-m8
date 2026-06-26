"""Tests for worker.tasks.scan_object — antivirus scan + verdict callbacks."""

import uuid

import pytest

from media_sdk_m8 import ScanJobPayload

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


@pytest.mark.anyio
async def test_clean_object_reports_clean_and_keeps_bytes(ctx, storage, http):
    ctx["scanner"] = FakeScanner(ScanVerdict.CLEAN)
    payload = _payload()

    result = await scan_object(ctx, payload)

    assert result == "clean"
    storage.get_object.assert_called_once_with(
        bucket="private-media", object_key="cat/abc/orig.png"
    )
    storage.remove_object.assert_not_called()
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
async def test_transient_storage_error_propagates_for_retry(ctx, storage, http):
    ctx["scanner"] = FakeScanner(ScanVerdict.CLEAN)
    storage.get_object.side_effect = ConnectionError("minio down")

    with pytest.raises(ConnectionError):
        await scan_object(ctx, _payload())

    assert http.posts == []  # no verdict reported when the scan never ran
