# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] - 2026-08-16

### Added

- `tests/test_changelog_version_parity.py` — asserts `worker.__version__` has a
  matching `## [x.y.z]` heading in `CHANGELOG.md` and that those headings are
  unique, so a release can no longer ship undocumented
  (`A32-changelog-version-parity`).
- `.markdownlint.yaml` — the fleet-baseline `MD024` `siblings_only` rule, so the
  Keep a Changelog format (which repeats `### Added` / `### Changed` across
  releases) stops failing Codacy (`A34-changelog-md024-baseline`).
- `.gitattributes` enforcing LF line endings and marking binary files.
- `AGENTS.md` and `REPOSITORY_CONTEXT.md` documenting the worker's role,
  boundaries, and the `imgtools_m8`-consumer-of-record rule.

### Changed

- **Version bumped `0.3.0` → `0.4.0`** to align with the fleet version matrix.
  No runtime behavior change: everything above is tooling, lint and
  documentation.
- `.codacy.yml` excludes the repository's documentation files from analysis.

## [0.3.0] - 2026-07-03

### Security

- The AV scan path now **streams** the source object to ClamAV chunk-by-chunk
  instead of buffering the whole object in worker memory (security plan P1.2).
  `scan_object` sizes the object from storage metadata first — failing closed
  (quarantine, never `CLEAN`) when it exceeds `WORKER_MAX_SCAN_BYTES` or has an
  unknown size — then feeds the SDK `stream_object` iterator straight to the
  clamd `INSTREAM` socket via a small `_ChunkReader` file-like adapter, so worker
  memory stays bounded regardless of object size.
- `generate_variants` now refuses **decompression-bomb** images before the full
  decode (security plan P1.2): a header-only pixel preflight (`worker/image_guard.py`,
  Pillow `Image.open(...).size` — no raster is decoded) fails the job terminally
  when the source's `width × height` exceeds `WORKER_MAX_DECODED_PIXELS` (default
  50 MP). Pillow is used for the header read only; all rendering stays delegated
  to `imgtools_m8`.
- Worker concurrency is now bounded via `WORKER_MAX_CONCURRENT_JOBS` (ARQ
  `max_jobs`, default 4) so peak memory ≈ that count × the per-job source/decoded
  ceilings; documented alongside a container memory-limit recommendation.
- `WorkerConfig` now **fails closed** for unsafe runtime credentials (security
  plan P1.1). New `ENVIRONMENT` (`local`/`development`/`staging`/`production`)
  and `STRICT_PRODUCTION_MODE` settings mirror the auth/media services; under the
  production/strict posture the worker refuses to boot — at config import, not
  only behind the compose preflight — when `MEDIA_INTERNAL_SERVICE_TOKEN`,
  `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, or (whenever `MEDIA_REDIS_USER` is set)
  `MEDIA_REDIS_PASSWORD` is empty or still the `changethis` placeholder. `local`
  (the home-lab default) keeps tolerating the placeholders so the example stack
  boots; `.env.example` placeholders stay the literal `changethis`.
- `generate_variants` now refuses a variant job whose source object is not stored
  as an image (`image/*`) before any download or decode (security plan P0.1,
  worker-side defense in depth). The worker stats the source via the SDK and, on a
  non-image content type or a missing/stale object, fails the job terminally
  without spending decode work — a storage-only restatement of media-service's
  scan-readiness gate that adds no service-internal coupling.
- `generate_variants` now enforces local variant cost ceilings as defense in depth
  (security plan P0.3, worker-side). Even if a malformed or stale job bypasses
  media-service's request bounds, the worker refuses unsafe workloads at its own
  trust boundary and fails the job terminally: output fan-out per job
  (`WORKER_MAX_OUTPUTS_PER_JOB`, checked before any storage work), source object
  size (`WORKER_MAX_SOURCE_BYTES`, from metadata before download — an unknown size
  fails closed), total written output bytes (`WORKER_MAX_OUTPUT_BYTES`, before any
  variant is written), and a render wall-clock budget
  (`WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS`, validated `<= WORKER_JOB_TIMEOUT_SECONDS`
  so the job fails cleanly before ARQ kills and retries it). media-service remains
  the request-policy owner; these are runtime-local safety ceilings. Source-byte
  streaming and decoded-pixel limits are addressed in plan item P1.2 (above).

### Added

- **Hash-locked production dependencies** (`worker/requirements_prod.lock`,
  finding 11.8): `pip-compile --generate-hashes` pins every transitive dep to an
  exact version + `sha256`; Dockerfile non-dev install enforces
  `pip install --require-hashes -r requirements_prod.lock`; `test_dependency_lock.py`
  locks the invariants in CI.
- **Supply-chain attestations** (`docker-publish.yaml`, finding 11.5): OIDC
  `id-token:write` + `attestations:write` permissions, `anchore/sbom-action` (SPDX
  JSON), `--provenance=mode=max`, and keyless `cosign sign` on every published
  image; SBOM + Trivy JSON uploaded as release assets. `test_ci_policy.py` guards
  digest pins, permissions, SBOM, provenance, cosign, and SHA-pinned action refs.
- **Single CI gate** (finding 11.7): stale `ci.yml` (unpinned refs, no
  attestation permissions) removed; `CI.yaml` is the sole CI gate. Policy tests
  `test_no_duplicate_ci_yml` / `test_ci_yaml_exists` / `test_ci_yaml_actions_are_sha_pinned`
  lock the invariant.
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

- Pin **`media-sdk-m8>=0.5.1`** (from `>=0.4.0`) to align with the fleet release
  train (SDK 0.5.1 → worker 0.3.0 → service 0.0.11). 0.5.0 added the
  `public_endpoint` flag to `ObjectMetadata`; 0.5.1 is a release-hygiene cut.
  The worker's consumed contracts and storage-client usage are unchanged; this is
  a floor-only bump. Lock regen deferred until 0.5.1 publishes to the index (lock
  stays self-consistent at 0.5.0 — dep-lock tests check name presence, not
  version). Version bumped to **0.3.0**.
- Pin **`media-sdk-m8>=0.4.0`** (from `>=0.1.0`) to stay aligned with the latest
  shared SDK. 0.3.0 added the `OutboxEventPayload` webhook contract; 0.4.0 adds
  the chunked `ObjectStorage.stream_object` read primitive. Version bumped to
  0.2.1.
- Bumped `arq>=0.28.0` (from `>=0.26.0`) — adds Python 3.14 support (the
  `worker/Dockerfile` base image) and pulls the cron-freeze (0.26.3) and
  task-retry race-condition (0.26.2) fixes; no API changes. Pinned `redis` to
  `>=5.3.1,<6.0.0`, making arq's hard `redis<6` constraint explicit/fail-closed.
