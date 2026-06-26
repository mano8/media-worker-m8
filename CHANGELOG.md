# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- `generate_variants` now refuses a variant job whose source object is not stored
  as an image (`image/*`) before any download or decode (security plan P0.1,
  worker-side defense in depth). The worker stats the source via the SDK and, on a
  non-image content type or a missing/stale object, fails the job terminally
  without spending decode work — a storage-only restatement of media-service's
  scan-readiness gate that adds no service-internal coupling.

### Changed

- Pin **`media-sdk-m8>=0.4.0`** (from `>=0.1.0`) to stay aligned with the latest
  shared SDK. 0.3.0 added the `OutboxEventPayload` webhook contract; 0.4.0 adds
  the chunked `ObjectStorage.stream_object` read primitive (used by
  media-service-m8 for streaming SHA-256 verification, plan item 6.x.3). The
  worker's consumed contracts (`ScanJobPayload` / `VariantJobPayload`) and its
  storage-client usage are unchanged, so this remains a floor bump with no code
  change. Version bumped to 0.2.1.

### Added

- Bootstrapped `media-worker-m8` — the async [ARQ](https://arq-docs.helpmanual.io/)
  worker that runs media-service-m8's background jobs off the media-owned Redis.
  The worker owns no database, is the sole `imgtools_m8` consumer, and reports
  results to media-service over its internal HTTP API (Bearer service token).
- `worker.tasks.scan_object` — antivirus scan task: downloads the object, scans
  it through a pluggable `Scanner`, reports `CLEAN` for clean bytes, and purges +
  reports `QUARANTINED` for infected bytes. Transient errors propagate so ARQ
  retries.
- `worker.tasks.generate_variants` — image-variant task: marks the job
  PROCESSING, renders every `VariantSpec` in one `process_image_async` call,
  matches each `VariantResult` to its spec by `name`, writes the bytes via the
  SDK `put_object`, registers each variant, and marks the job COMPLETED (or
  FAILED + error, terminal — no retry of a partially rendered job).
- `worker.scanner` — `Scanner` protocol, `ScanVerdict`, and the default
  `ClamAVScanner` (a thin clamd TCP client; no ClamAV binary or virus database is
  bundled in the image) plus a `get_scanner` factory.
- `worker.config.WorkerConfig` — self-contained pydantic-settings read from the
  worker's **own** environment (no media-service import); builds the shared-SDK
  `ObjectStorageConfig`. Covers the media Redis, MinIO, the media-service
  internal API URL + service token, the ClamAV daemon, and ARQ tuning.
- `worker.media_types.content_type_for_format` — maps an imgtools output-format
  name to a MIME type for variant uploads (the worker's only format knowledge).
- `worker.settings.WorkerSettings` — ARQ entrypoint (`functions`,
  `redis_settings`, `max_tries`, `job_timeout`, `keep_result`) with
  `on_startup`/`on_shutdown` hooks that build the per-process storage client,
  scanner, and HTTP client.
- `worker/Dockerfile` (`CMD ["arq", "worker.settings.WorkerSettings"]`, no ClamAV
  bundled) and `docker_compose/` with a `clamav` service (clamd on `3310`,
  healthcheck + signature-DB volume) and the `worker` service wired to the
  hardened media stack's networks (media Redis + MinIO + service token).
- Dependencies: `arq`, `redis` (<6 for arq), `httpx`, `clamd`,
  `imgtools_m8>=2.1.0`, `media-sdk-m8`, `minio`, `pydantic`/`pydantic-settings`.
- Code-quality config mirrored from media-service-m8 (`ruff.toml`, `mypy.ini`,
  `pytest.ini`, `.coveragerc`, `setup.cfg`, `.codacy.yml`) and CI
  (`CI.yaml`, `docker-publish.yaml`), targeting the `worker` package.
- Test suite with fakes for every live seam (clamd, imgtools, MinIO, HTTP).
  ruff/mypy/bandit clean; **100% line + branch coverage** (32 tests).
- `worker/.env.example` and `docker_compose/worker.env.example` (all secrets the
  literal `changethis`, with rules in comments).

### Changed

- Bumped `arq>=0.28.0` (from `>=0.26.0`) — adds Python 3.14 support (the
  `worker/Dockerfile` base image) and pulls the cron-freeze (0.26.3) and
  task-retry race-condition (0.26.2) fixes; no API changes. Pinned `redis` to
  `>=5.3.1,<6.0.0`, making arq's hard `redis<6` constraint explicit/fail-closed.
