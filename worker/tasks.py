"""ARQ task functions: antivirus scan and image-variant generation.

Both tasks are async. Object bytes are read/written through the shared-SDK
``ObjectStorage`` client; because those MinIO calls are synchronous they run in a
worker thread (``asyncio.to_thread``) so the event loop never blocks. Results are
reported to media-service over its internal HTTP API (Bearer service token).

Resources (config, storage, scanner, http client) are created once at worker
startup and handed to every task through the ARQ ``ctx`` mapping.
"""

import asyncio
from typing import Any

from imgtools_m8 import process_image_async
from media_sdk_m8 import ObjectStorage, ScanJobPayload, VariantJobPayload, VariantSpec

from worker.config import WorkerConfig
from worker.image_guard import assert_decoded_pixels_within_limit
from worker.media_types import content_type_for_format
from worker.scanner import Scanner, ScanVerdict

# ── Scan verdict → media-service ScanStatus wire value ────────────────────────
SCAN_STATUS_CLEAN = "clean"
SCAN_STATUS_QUARANTINED = "quarantined"

# ── VariantJob status wire values ─────────────────────────────────────────────
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"

# ── Scan-readiness defense (P0.1) ─────────────────────────────────────────────
#: A processable variant source must be stored as an image. media-service only
#: enqueues variant jobs for scanned, ready image objects; this prefix is the
#: worker's storage-only restatement of that contract.
IMAGE_CONTENT_TYPE_PREFIX = "image/"


class UnprocessableSourceError(Exception):
    """A variant job references a source the worker must not decode.

    Raised by the pre-decode readiness guard when a (possibly stale or poisoned)
    job points at an object state media-service no longer considers processable,
    e.g. a non-image content type. Terminal — the job is failed, never retried.
    """


class VariantCostLimitError(Exception):
    """A variant job exceeds a worker safety ceiling.

    Raised by the cost-bound guards (P0.3 defense in depth) when a (possibly
    malformed or stale) job would multiply CPU, memory, queue time, or storage
    writes past this worker's local ceilings — too many outputs, an oversized
    source, an oversized total output, or a render that overran its time budget.
    Terminal — the job is failed, never retried.
    """


def _assert_source_processable(stat: Any) -> None:
    """Refuse a stale/non-processable variant source before any decode.

    Defense in depth for the service-side scan-readiness gate: we inspect only
    storage metadata (never the object bytes), so refusing a stale job costs no
    download or decode work. A missing source raises from ``stat_object`` upstream
    and is handled the same terminal way.
    """
    content_type = getattr(stat, "content_type", None) or ""
    if not content_type.lower().startswith(IMAGE_CONTENT_TYPE_PREFIX):
        raise UnprocessableSourceError(
            f"source object is not a processable image (content_type={content_type!r})"
        )


def _assert_output_count_within_limit(
    payload: VariantJobPayload, config: WorkerConfig
) -> None:
    """Bound output fan-out before any storage work (P0.3).

    Checked first, before stat/download, so an over-fanned job is refused at the
    cheapest possible point.
    """
    count = len(payload.specs)
    if count > config.WORKER_MAX_OUTPUTS_PER_JOB:
        raise VariantCostLimitError(
            f"variant job requests {count} outputs, exceeding the worker ceiling "
            f"of {config.WORKER_MAX_OUTPUTS_PER_JOB}"
        )


def _scan_source_too_large(stat: Any, config: WorkerConfig) -> bool:
    """True when a scan source is too large to stream-scan, or of unknown size.

    Read from storage metadata before any stream (P1.2). Scanning is streamed
    chunk-by-chunk so worker memory stays bounded regardless of object size; this
    ceiling only caps abuse and keeps the stream within clamd's ``StreamMaxLength``.
    An unknown size fails closed — the worker will not stream bytes it cannot
    bound. A ``True`` result is handled by quarantining the object, never marking
    it clean.
    """
    size = getattr(stat, "size", None)
    return size is None or size > config.WORKER_MAX_SCAN_BYTES


def _assert_source_size_within_limit(stat: Any, config: WorkerConfig) -> None:
    """Refuse an oversized (or unsized) source before download (P0.3).

    Inspects only storage metadata, so an oversized source costs no transfer. A
    missing/unknown size fails closed — the worker will not download bytes it
    cannot bound.
    """
    size = getattr(stat, "size", None)
    if size is None:
        raise VariantCostLimitError("source object size is unknown; refusing to fetch")
    if size > config.WORKER_MAX_SOURCE_BYTES:
        raise VariantCostLimitError(
            f"source object is {size} bytes, exceeding the worker ceiling of "
            f"{config.WORKER_MAX_SOURCE_BYTES}"
        )


def _assert_output_bytes_within_budget(total_bytes: int, config: WorkerConfig) -> None:
    """Bound total written output bytes before any variant is stored (P0.3)."""
    if total_bytes > config.WORKER_MAX_OUTPUT_BYTES:
        raise VariantCostLimitError(
            f"variant outputs total {total_bytes} bytes, exceeding the worker "
            f"ceiling of {config.WORKER_MAX_OUTPUT_BYTES}"
        )


def _auth_headers(config: WorkerConfig) -> dict[str, str]:
    """Auth headers for internal media-service callbacks."""
    return {
        "Authorization": f"Bearer {config.service_token}",
        "X-Worker-Client": config.WORKER_CLIENT_ID,
    }


async def _post_scan_result(ctx: dict[str, Any], object_id: Any, status: str) -> None:
    """POST an antivirus verdict to the internal scan-result endpoint."""
    config: WorkerConfig = ctx["config"]
    http = ctx["http"]
    resp = await http.post(
        f"{config.api_base_url}/v1/internal/objects/{object_id}/scan-result",
        json={"scan_status": status},
        headers=_auth_headers(config),
    )
    resp.raise_for_status()


async def _register_variant(
    ctx: dict[str, Any], media_object_id: Any, spec: VariantSpec, result: Any
) -> None:
    """Register a written variant with media-service (idempotent server-side)."""
    config: WorkerConfig = ctx["config"]
    http = ctx["http"]
    resp = await http.post(
        f"{config.api_base_url}/v1/internal/objects/{media_object_id}/variants",
        json={
            "variant_name": spec.variant_name,
            "storage_bucket": spec.target_bucket,
            "object_key": spec.target_key,
            "width": result.width,
            "height": result.height,
            "size_bytes": result.size_bytes,
            "format": result.format,
        },
        headers=_auth_headers(config),
    )
    resp.raise_for_status()


async def _update_job(
    ctx: dict[str, Any],
    job_id: Any,
    status: str,
    *,
    variants_created: int | None = None,
    error: str | None = None,
) -> None:
    """PATCH a variant job's status/progress on media-service."""
    config: WorkerConfig = ctx["config"]
    http = ctx["http"]
    body: dict[str, Any] = {"status": status}
    if variants_created is not None:
        body["variants_created"] = variants_created
    if error is not None:
        body["error"] = error
    resp = await http.patch(
        f"{config.api_base_url}/v1/internal/variant-jobs/{job_id}",
        json=body,
        headers=_auth_headers(config),
    )
    resp.raise_for_status()


async def _quarantine(ctx: dict[str, Any], payload: ScanJobPayload) -> str:
    """Purge an unsafe object and report it ``QUARANTINED``."""
    storage: ObjectStorage = ctx["storage"]
    await asyncio.to_thread(
        storage.remove_object,
        bucket=payload.bucket,
        object_key=payload.object_key,
    )
    await _post_scan_result(ctx, payload.object_id, SCAN_STATUS_QUARANTINED)
    return SCAN_STATUS_QUARANTINED


async def scan_object(ctx: dict[str, Any], payload: ScanJobPayload) -> str:
    """Antivirus-scan an uploaded object and report the verdict.

    The source is **streamed** to the scanner chunk-by-chunk (it is never read
    whole into worker memory): the object is first sized from storage metadata,
    refused as unsafe (fail-closed, quarantined — never clean) when it exceeds
    ``WORKER_MAX_SCAN_BYTES`` or has an unknown size, then streamed via the SDK
    ``stream_object`` primitive (security plan P1.2). Clean objects are reported
    ``CLEAN`` (media-service flips them to READY). Infected (or unscannable)
    objects are purged from storage first, then reported ``QUARANTINED``.
    Transient errors (storage/scanner/HTTP) propagate so ARQ retries the job.
    """

    storage: ObjectStorage = ctx["storage"]
    scanner: Scanner = ctx["scanner"]
    config: WorkerConfig = ctx["config"]

    stat = await asyncio.to_thread(
        storage.stat_object, bucket=payload.bucket, object_key=payload.object_key
    )
    if _scan_source_too_large(stat, config):
        return await _quarantine(ctx, payload)

    chunks = storage.stream_object(bucket=payload.bucket, object_key=payload.object_key)
    verdict = await scanner.scan(chunks)

    if verdict is ScanVerdict.INFECTED:
        return await _quarantine(ctx, payload)

    await _post_scan_result(ctx, payload.object_id, SCAN_STATUS_CLEAN)
    return SCAN_STATUS_CLEAN


async def generate_variants(ctx: dict[str, Any], payload: VariantJobPayload) -> int:
    """Render every spec for one source object and register the results.

    Marks the job PROCESSING, bounds the output fan-out, verifies the source is
    still a processable image and within the worker's size ceiling (pre-decode,
    storage-only defenses against stale/poisoned or oversized jobs), downloads
    the source, refuses a decompression bomb via a header-only pixel preflight
    before the full decode (``WORKER_MAX_DECODED_PIXELS``, security plan P1.2),
    renders all specs in one ``process_image_async`` call under a
    wall-clock budget, matches each :class:`VariantResult` to its spec by
    ``name``, checks the total output budget, then writes the bytes and registers
    each variant. On success the job is marked COMPLETED with the created count.
    Any failure marks it FAILED with the error message and is **terminal** — a
    partially rendered job is not retried (re-running would duplicate
    already-written variants). The cost ceilings (P0.3) are local worker
    defense in depth; media-service remains the request-policy owner.
    """

    storage: ObjectStorage = ctx["storage"]
    config: WorkerConfig = ctx["config"]

    await _update_job(ctx, payload.job_id, JOB_STATUS_PROCESSING)
    created = 0
    try:
        _assert_output_count_within_limit(payload, config)
        stat = await asyncio.to_thread(
            storage.stat_object,
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )
        _assert_source_processable(stat)
        _assert_source_size_within_limit(stat, config)
        source = await asyncio.to_thread(
            storage.get_object,
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )
        assert_decoded_pixels_within_limit(source, config)
        try:
            async with asyncio.timeout(config.WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS):
                results = await process_image_async(
                    source, [spec.output_options for spec in payload.specs]
                )
        except TimeoutError as exc:
            raise VariantCostLimitError(
                "image processing exceeded the worker time budget of "
                f"{config.WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS}s"
            ) from exc
        by_name = {result.name: result for result in results}

        total_output_bytes = sum(
            by_name[spec.variant_name].size_bytes for spec in payload.specs
        )
        _assert_output_bytes_within_budget(total_output_bytes, config)

        for spec in payload.specs:
            result = by_name[spec.variant_name]
            await asyncio.to_thread(
                storage.put_object,
                bucket=spec.target_bucket,
                object_key=spec.target_key,
                data=result.data,
                content_type=content_type_for_format(result.format),
            )
            await _register_variant(ctx, payload.media_object_id, spec, result)
            created += 1
    except Exception as exc:  # noqa: BLE001 — job-failure boundary
        # Any render/storage failure marks the job FAILED and reports the
        # variants already created; nothing may escape into the ARQ loop.
        await _update_job(ctx, payload.job_id, JOB_STATUS_FAILED, error=str(exc))
        return created

    await _update_job(
        ctx, payload.job_id, JOB_STATUS_COMPLETED, variants_created=created
    )
    return created
