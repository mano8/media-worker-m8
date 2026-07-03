# media-worker-m8

Async [ARQ](https://arq-docs.helpmanual.io/) worker for background media jobs in
the M8 platform. It consumes jobs enqueued by **media-service-m8** from the
media-owned Redis and runs two tasks:

| Task | Trigger | What it does |
| --- | --- | --- |
| `scan_object` | object upload completes | Antivirus-scan the bytes (ClamAV), **streamed** chunk-by-chunk so the object is never read whole into memory. Clean → report `CLEAN`; infected (or unscannable by size) → purge the object and report `QUARANTINED`. |
| `generate_variants` | a variant job is requested | Verify the source is still a processable image, render image variants with `imgtools_m8`, write them to object storage, and register each one. |

The worker owns **no database**. It reads/writes object bytes through the shared
[`media-sdk-m8`](../media-sdk-m8) storage client and reports results to
media-service over its internal HTTP API using a shared bearer service token.
It is the **sole `imgtools_m8` consumer** — neither media-service nor the SDK
import imgtools.

---

## Architecture

```
                     enqueue (ARQ / media Redis)
 media-service-m8  ───────────────────────────────▶  media-worker-m8
        ▲                                                   │
        │  POST /v1/internal/objects/{id}/scan-result       │ get/put/remove bytes
        │  POST /v1/internal/objects/{id}/variants          ▼
        │  PATCH /v1/internal/variant-jobs/{id}          MinIO  (via media-sdk-m8)
        └───────────────  (Bearer service token)  ──────────┘
                                                            │ INSTREAM (TCP 3310)
                                                            ▼
                                                    clamav (clamd daemon)
```

* **Async everywhere.** Tasks are coroutines; the synchronous MinIO calls run in
  a thread via `asyncio.to_thread` so the event loop never blocks (mirroring
  `imgtools_m8.process_image_async`, which offloads the CPU pipeline to a
  threadpool).
* **Pluggable scanner.** `scan_object` depends only on the `Scanner` protocol;
  the default `ClamAVScanner` is a thin clamd *client* (no virus DB or ClamAV
  binary bundled in the image — the `clamav` service owns those).
* **Worker needs no preset/key knowledge.** media-service builds every
  `VariantSpec` (imgtools-shaped `output_options` + `target_bucket`/`target_key`)
  inside the `VariantJobPayload`; the worker just renders, stores, and registers.
* **Pre-decode scan-readiness defense.** Before downloading or decoding a source,
  `generate_variants` stats the object and refuses anything that is not stored as
  an image (`image/*`) — defense in depth for media-service's scan-readiness gate
  so a stale or poisoned job is failed terminally without spending decode work.
* **Local cost ceilings.** The worker also bounds its own workload as defense in
  depth: it caps outputs per job, source object size (from metadata, pre-download),
  total written output bytes (before any write), and the render wall-clock time.
  A job over any ceiling fails terminally even if a malformed or stale job bypasses
  media-service — which remains the request-policy owner; these are safety ceilings,
  not user-facing policy.
* **Bounded memory.** The scan path **streams** the source to clamd chunk-by-chunk
  (`stream_object`) instead of buffering it whole, after a metadata size gate
  (`WORKER_MAX_SCAN_BYTES`, fail-closed). Before rendering, a header-only pixel
  preflight (`WORKER_MAX_DECODED_PIXELS`) refuses decompression-bomb images before
  the full decode allocates a raster. Concurrency is bounded
  (`WORKER_MAX_CONCURRENT_JOBS` → ARQ `max_jobs`) so peak memory ≈ that count ×
  the per-job source/decoded ceilings — size the container memory limit to match.

---

## Package layout

| Module | Responsibility |
| --- | --- |
| `worker/config.py` | `WorkerConfig` (pydantic-settings) read from the worker's **own** env; builds the SDK `ObjectStorageConfig`. |
| `worker/scanner.py` | `Scanner` protocol, `ScanVerdict`, `ClamAVScanner` (streams chunks to clamd via `_ChunkReader`), `get_scanner` factory. |
| `worker/image_guard.py` | Pre-decode decompression-bomb guard (header-only pixel preflight; Pillow used for the header read only). |
| `worker/media_types.py` | `content_type_for_format` — imgtools format name → MIME type. |
| `worker/tasks.py` | `scan_object` / `generate_variants` task functions + internal HTTP callbacks. |
| `worker/settings.py` | ARQ `WorkerSettings` + `on_startup`/`on_shutdown` resource wiring. |

---

## Configuration

Copy `worker/.env.example` to `worker/.env`. Every secret stays the literal
`changethis` in the example (fail-closed); set real values only in `.env`.

| Variable | Default | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | Trust posture (`local`/`development`/`staging`/`production`), aligned with the auth/media services. |
| `STRICT_PRODUCTION_MODE` | `false` | Force the production posture regardless of `ENVIRONMENT`. |
| `MEDIA_API_URL` | `http://media-service:8000/media` | Base URL **including** the API prefix; the worker appends `/v1/internal/…`. |
| `MEDIA_INTERNAL_SERVICE_TOKEN` | `changethis` | Must match media-service; high-entropy in prod. |
| `MEDIA_REDIS_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_NAMESPACE` | `media_redis_cache` / `6379` / `appuser` / – / `media` | Media-owned Redis (ARQ queue). |
| `MINIO_HOST` / `_PORT` / `_USE_SSL` / `_REGION` / `_ACCESS_KEY` / `_SECRET_KEY` | `minio` / `9000` / `false` / `eu-west-1` / – / – | Object storage. |
| `CLAMAV_HOST` / `_PORT` / `_TIMEOUT_SECONDS` | `clamav` / `3310` / `120` | clamd daemon address. |
| `WORKER_MAX_TRIES` / `_JOB_TIMEOUT_SECONDS` / `_KEEP_RESULT_SECONDS` | `5` / `300` / `3600` | ARQ tuning. |
| `WORKER_MAX_CONCURRENT_JOBS` | `4` | Max jobs run at once (ARQ `max_jobs`); bounds peak memory with the per-job ceilings. |
| `WORKER_MAX_SOURCE_BYTES` | `67108864` (64 MiB) | Max variant source object size accepted from storage metadata before download. |
| `WORKER_MAX_OUTPUTS_PER_JOB` | `32` | Max variant outputs rendered per job (fan-out bound). |
| `WORKER_MAX_OUTPUT_BYTES` | `134217728` (128 MiB) | Max total written output bytes per job (storage-write amplification bound). |
| `WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS` | `120` | Wall-clock ceiling for one render call; must be ≤ `WORKER_JOB_TIMEOUT_SECONDS`. |
| `WORKER_MAX_SCAN_BYTES` | `268435456` (256 MiB) | Max scan source size (from metadata, pre-stream); over-ceiling/unknown-size objects fail closed (quarantined). Keep ≤ clamd `StreamMaxLength`. |
| `WORKER_MAX_DECODED_PIXELS` | `50000000` (50 MP) | Max decoded pixels for a variant source; header-only preflight that refuses decompression bombs before the full decode. |

**Fail-closed credentials.** Under `ENVIRONMENT=production` (or
`STRICT_PRODUCTION_MODE=true`) the worker refuses to boot — at config import,
not only behind the compose preflight — when any required secret is empty or
still the `changethis` placeholder: `MEDIA_INTERNAL_SERVICE_TOKEN`,
`MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, and (whenever `MEDIA_REDIS_USER` is set)
`MEDIA_REDIS_PASSWORD`. `local` keeps tolerating the placeholders so the
home-lab example stack still boots.

---

## Running

### Locally

```bash
pip install -r worker/requirements_dev.txt
arq worker.settings.WorkerSettings
```

### Docker Compose

Brings up the `clamav` daemon + the worker, attached to the hardened media
stack's networks (bring that stack up first). On first boot ClamAV downloads its
signature database via freshclam, so the daemon may be unhealthy for a few
minutes.

```bash
cd docker_compose
cp worker.env.example worker.env   # then set real secrets
docker compose --env-file worker.env up -d --build
```

---

## Reproducible builds

The production Docker image installs from a fully pinned, hash-verified lock
(`worker/requirements_prod.lock`). Every transitive dependency is exact-pinned
(`==`) and carries a `sha256` hash; `pip install --require-hashes` refuses to
install anything not in the lock.

To regenerate the lock (Python 3.12, matching the fleet baseline):

```bash
pip-compile --generate-hashes --no-emit-index-url \
    --output-file=worker/requirements_prod.lock worker/requirements_prod.txt
```

`tests/test_dependency_lock.py` and `tests/test_ci_policy.py` assert the lock
integrity and the publish-workflow supply-chain invariants (SBOM, provenance,
cosign, SHA-pinned action refs) in CI so neither can silently regress.

---

## Development

```bash
ruff format . && ruff check . && bandit -r worker
pytest tests/ -v --cov=worker --cov-report=term-missing --cov-fail-under=100
```

Tests are self-contained: the live seams (clamd socket, imgtools render, MinIO,
the media-service HTTP API) are replaced with fakes, so no running stack is
needed. Line **and** branch coverage are held at **100%**.
