"""Delegated export-archive task (`P2 U11`)."""

import io
import zipfile
from uuid import uuid4

import pytest
from media_sdk_m8 import ExportArchiveEntry, ExportArchiveJobPayload

from worker.tasks import build_export_archive


def _payload(*, size_bytes: int = 6) -> ExportArchiveJobPayload:
    object_id = uuid4()
    return ExportArchiveJobPayload(
        job_id=uuid4(),
        manifest_json='{"category_tree":[],"objects":[]}',
        objects=[
            ExportArchiveEntry(
                object_id=object_id,
                source_bucket="private-media",
                source_object_key="source/report.pdf",
                archive_path=f"files/{object_id}/report.pdf",
                size_bytes=size_bytes,
            )
        ],
        target_bucket="temp-media",
        target_object_key="users/u/exports/result.zip",
        stream_chunk_size=3,
        presigned_expire_seconds=300,
    )


@pytest.mark.anyio
async def test_export_archive_round_trips_objects_and_posts_result(ctx, storage, http):
    payload = _payload()
    storage.stream_object.return_value = [b"abc", b"def"]
    stored: dict[str, object] = {}

    def put_object_stream(**kwargs):
        stored.update(kwargs)
        stored["data_bytes"] = kwargs["data"].read()

    storage.put_object_stream.side_effect = put_object_stream
    storage.presigned_get_object.return_value = "https://media.example/result.zip"

    embedded = await build_export_archive(ctx, payload.model_dump(mode="json"))

    assert embedded == 1
    assert stored["bucket"] == "temp-media"
    assert stored["object_key"] == "users/u/exports/result.zip"
    assert stored["content_type"] == "application/zip"
    assert stored["length"] == len(stored["data_bytes"])
    with zipfile.ZipFile(io.BytesIO(stored["data_bytes"])) as archive:
        assert archive.read("manifest.json") == payload.manifest_json.encode()
        assert archive.read(payload.objects[0].archive_path) == b"abcdef"
    storage.stream_object.assert_called_once_with(
        bucket="private-media", object_key="source/report.pdf", chunk_size=3
    )
    storage.presigned_get_object.assert_called_once()
    assert [call["json"]["status"] for call in http.patches] == [
        "processing",
        "completed",
    ]
    assert http.patches[-1]["json"]["download_url"] == (
        "https://media.example/result.zip"
    )
    storage.remove_object.assert_not_called()


@pytest.mark.anyio
async def test_export_archive_source_failure_cleans_up_and_reports_failed(
    ctx, storage, http
):
    payload = _payload()

    def broken_stream(**_kwargs):
        yield b"abc"
        raise OSError("storage stopped")

    storage.stream_object.side_effect = broken_stream

    embedded = await build_export_archive(ctx, payload)

    assert embedded == 0
    storage.remove_object.assert_called_once_with(
        bucket=payload.target_bucket, object_key=payload.target_object_key
    )
    storage.put_object_stream.assert_not_called()
    storage.presigned_get_object.assert_not_called()
    assert http.patches[-1]["json"] == {
        "status": "failed",
        "error": "Archive assembly failed: OSError",
    }


@pytest.mark.anyio
async def test_export_archive_size_drift_fails_before_upload(ctx, storage, http):
    payload = _payload(size_bytes=7)
    storage.stream_object.return_value = [b"abc", b"def"]

    assert await build_export_archive(ctx, payload) == 0

    storage.put_object_stream.assert_not_called()
    assert http.patches[-1]["json"]["error"] == ("Archive assembly failed: ValueError")


@pytest.mark.anyio
async def test_export_archive_upload_failure_cleans_up(ctx, storage, http):
    payload = _payload()
    storage.stream_object.return_value = [b"abcdef"]
    storage.put_object_stream.side_effect = OSError("upload failed")

    assert await build_export_archive(ctx, payload) == 0

    storage.remove_object.assert_called_once()
    assert http.patches[-1]["json"]["status"] == "failed"


@pytest.mark.anyio
async def test_export_archive_cleanup_failure_does_not_mask_original(
    ctx, storage, http, caplog
):
    payload = _payload()
    storage.stream_object.side_effect = OSError("source failed")
    storage.remove_object.side_effect = OSError("cleanup failed")

    assert await build_export_archive(ctx, payload) == 0

    assert "media.export.cleanup_failed" in caplog.text
    assert http.patches[-1]["json"]["error"] == ("Archive assembly failed: OSError")
