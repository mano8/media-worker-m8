"""Tests for worker.tasks.generate_variants — render, store, register, report."""

import uuid
from types import SimpleNamespace

import pytest

from media_sdk_m8 import VariantJobPayload, VariantSpec

from worker import tasks
from worker.tasks import generate_variants

from tests.conftest import SERVICE_TOKEN, WORKER_CLIENT_ID, make_variant_result


def _spec(name, ext="webp", bucket="public-media"):
    return VariantSpec(
        variant_name=name,
        output_options={"name": name, "formats": [{"ext": ext.upper()}]},
        target_bucket=bucket,
        target_key=f"cat/abc/variants/{name}/{name}.{ext}",
    )


def _payload(specs):
    return VariantJobPayload(
        job_id=uuid.uuid4(),
        media_object_id=uuid.uuid4(),
        source_bucket="private-media",
        source_object_key="cat/abc/orig.png",
        specs=specs,
    )


@pytest.mark.anyio
async def test_success_renders_stores_registers_and_completes(
    ctx, storage, http, monkeypatch
):
    specs = [_spec("thumb_webp"), _spec("small_jpeg", ext="jpeg")]
    payload = _payload(specs)

    # imgtools returns results out of order to prove match-by-name.
    results = [
        make_variant_result(name="small_jpeg", fmt="JPEG", data=b"jpg", size_bytes=3),
        make_variant_result(name="thumb_webp", fmt="WEBP", data=b"wbp", size_bytes=3),
    ]

    async def fake_process(source, options):
        assert source == b"source-bytes"
        assert options == [s.output_options for s in specs]
        return results

    monkeypatch.setattr(tasks, "process_image_async", fake_process)

    created = await generate_variants(ctx, payload)

    assert created == 2

    # PATCH processing first, PATCH completed last with the count.
    assert http.patches[0]["json"] == {"status": "processing"}
    assert http.patches[-1]["json"] == {"status": "completed", "variants_created": 2}
    assert http.patches[-1]["url"].endswith(
        f"/v1/internal/variant-jobs/{payload.job_id}"
    )

    # Each variant written with the format-derived content type.
    put_calls = {
        c.kwargs["object_key"]: c.kwargs for c in storage.put_object.call_args_list
    }
    thumb = put_calls["cat/abc/variants/thumb_webp/thumb_webp.webp"]
    assert thumb["bucket"] == "public-media"
    assert thumb["data"] == b"wbp"
    assert thumb["content_type"] == "image/webp"
    jpeg = put_calls["cat/abc/variants/small_jpeg/small_jpeg.jpeg"]
    assert jpeg["content_type"] == "image/jpeg"

    # Each variant registered with auth header + dimensions.
    assert len(http.posts) == 2
    reg = http.posts[0]
    assert reg["headers"] == {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
        "X-Worker-Client": WORKER_CLIENT_ID,
    }
    assert reg["url"].endswith(
        f"/v1/internal/objects/{payload.media_object_id}/variants"
    )
    assert reg["json"]["variant_name"] in {"thumb_webp", "small_jpeg"}
    assert reg["json"]["width"] == 10
    assert reg["json"]["size_bytes"] == 3


@pytest.mark.anyio
async def test_render_failure_marks_job_failed_and_is_terminal(
    ctx, storage, http, monkeypatch
):
    payload = _payload([_spec("thumb_webp")])

    async def boom(source, options):
        raise RuntimeError("decode error")

    monkeypatch.setattr(tasks, "process_image_async", boom)

    created = await generate_variants(ctx, payload)

    assert created == 0
    storage.put_object.assert_not_called()
    assert http.posts == []  # nothing registered
    assert http.patches[0]["json"] == {"status": "processing"}
    failed = http.patches[-1]["json"]
    assert failed["status"] == "failed"
    assert "decode error" in failed["error"]


@pytest.mark.anyio
async def test_missing_variant_name_marks_job_failed(ctx, storage, http, monkeypatch):
    payload = _payload([_spec("thumb_webp")])

    async def wrong_name(source, options):
        return [make_variant_result(name="unexpected")]

    monkeypatch.setattr(tasks, "process_image_async", wrong_name)

    created = await generate_variants(ctx, payload)

    assert created == 0
    assert http.patches[-1]["json"]["status"] == "failed"


@pytest.mark.anyio
async def test_non_image_source_fails_before_decode(ctx, storage, http, monkeypatch):
    """A stale job pointing at a non-image object fails without decoding bytes."""
    storage.stat_object.return_value = SimpleNamespace(
        content_type="application/pdf", size=12
    )
    payload = _payload([_spec("thumb_webp")])

    async def must_not_run(source, options):  # pragma: no cover - must not be called
        raise AssertionError("process_image_async must not run for a bad source")

    monkeypatch.setattr(tasks, "process_image_async", must_not_run)

    created = await generate_variants(ctx, payload)

    assert created == 0
    storage.get_object.assert_not_called()  # never downloaded
    storage.put_object.assert_not_called()
    assert http.posts == []
    failed = http.patches[-1]["json"]
    assert failed["status"] == "failed"
    assert "not a processable image" in failed["error"]


@pytest.mark.anyio
async def test_missing_source_object_fails_terminally(ctx, storage, http, monkeypatch):
    """A deleted/stale source raises from stat and fails without decoding."""
    storage.stat_object.side_effect = FileNotFoundError("source gone")
    payload = _payload([_spec("thumb_webp")])

    async def must_not_run(source, options):  # pragma: no cover - must not be called
        raise AssertionError("process_image_async must not run for a missing source")

    monkeypatch.setattr(tasks, "process_image_async", must_not_run)

    created = await generate_variants(ctx, payload)

    assert created == 0
    storage.get_object.assert_not_called()
    assert http.patches[-1]["json"]["status"] == "failed"
