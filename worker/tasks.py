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

from media_sdk_m8 import ScanJobPayload, VariantJobPayload, VariantSpec
from media_sdk_m8 import ObjectStorage

from worker.config import WorkerConfig
from worker.media_types import content_type_for_format
from worker.scanner import Scanner, ScanVerdict

# ── Scan verdict → media-service ScanStatus wire value ────────────────────────
SCAN_STATUS_CLEAN = "clean"
SCAN_STATUS_QUARANTINED = "quarantined"

# ── VariantJob status wire values ─────────────────────────────────────────────
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


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


async def scan_object(ctx: dict[str, Any], payload: ScanJobPayload) -> str:
    """Antivirus-scan an uploaded object and report the verdict.

    Clean objects are reported ``CLEAN`` (media-service flips them to READY).
    Infected objects are purged from storage first, then reported
    ``QUARANTINED``. Transient errors (storage/scanner/HTTP) propagate so ARQ
    retries the job.
    """

    storage: ObjectStorage = ctx["storage"]
    scanner: Scanner = ctx["scanner"]

    data = await asyncio.to_thread(
        storage.get_object, bucket=payload.bucket, object_key=payload.object_key
    )
    verdict = await scanner.scan(data)

    if verdict is ScanVerdict.INFECTED:
        await asyncio.to_thread(
            storage.remove_object,
            bucket=payload.bucket,
            object_key=payload.object_key,
        )
        await _post_scan_result(ctx, payload.object_id, SCAN_STATUS_QUARANTINED)
        return SCAN_STATUS_QUARANTINED

    await _post_scan_result(ctx, payload.object_id, SCAN_STATUS_CLEAN)
    return SCAN_STATUS_CLEAN


async def generate_variants(ctx: dict[str, Any], payload: VariantJobPayload) -> int:
    """Render every spec for one source object and register the results.

    Marks the job PROCESSING, downloads the source, renders all specs in one
    ``process_image_async`` call, matches each :class:`VariantResult` to its spec
    by ``name``, writes the bytes, and registers each variant. On success the job
    is marked COMPLETED with the created count. Any failure marks it FAILED with
    the error message and is **terminal** — a partially rendered job is not
    retried (re-running would duplicate already-written variants).
    """

    storage: ObjectStorage = ctx["storage"]

    await _update_job(ctx, payload.job_id, JOB_STATUS_PROCESSING)
    created = 0
    try:
        source = await asyncio.to_thread(
            storage.get_object,
            bucket=payload.source_bucket,
            object_key=payload.source_object_key,
        )
        results = await process_image_async(
            source, [spec.output_options for spec in payload.specs]
        )
        by_name = {result.name: result for result in results}

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
    except Exception as exc:
        await _update_job(ctx, payload.job_id, JOB_STATUS_FAILED, error=str(exc))
        return created

    await _update_job(
        ctx, payload.job_id, JOB_STATUS_COMPLETED, variants_created=created
    )
    return created
