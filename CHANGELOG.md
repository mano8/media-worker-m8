# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No pending changes.

## [1.0.2] - 2026-09-23

Shipped-library-generation alignment — `B29-align-shipped-library-generation`
(Wave 6d) of the workspace's consumer-alignment closure plan, finding `G22`:
every service in the fleet was tested on a library graph none of them shipped.
CI installs `requirements_dev.txt`'s `>=` floors, which resolve to the current
generation; `requirements_prod.lock` pinned an older one, so the tested graph
and the released graph had never been the same. This repository is the only one
of the five already published at the version the fix would otherwise have
ridden, so it takes its own patch release. No behaviour, job-contract or
payload change.

### Changed

- **The shipped lock moves onto the generation CI already tests against.**
  Exactly one declared pin moves — `pydantic` — plus `pydantic-core`, which is
  its hard `==` peer. The lock was regenerated with
  `pip-compile --generate-hashes --no-emit-index-url --upgrade-package pydantic==2.13.5`,
  never a blanket `--upgrade`, so no other line in the ~50-distribution graph
  moved. Read out of the built images (`python -c "importlib.metadata.version"`;
  the runtime image ships no pip):

  | Package | Published `1.0.1` image | This release |
  | --- | --- | --- |
  | `pydantic` | `2.13.4` | **`2.13.5`** |
  | `pydantic-core` | `2.46.4` | **`2.46.5`** |
  | `pydantic-settings` | `2.14.2` | `2.14.2` (unchanged) |
  | `media-sdk-m8` | `1.0.0` | `1.0.0` (unchanged) |
  | `imgtools-m8` | `2.1.1` | `2.1.1` (unchanged) |

  This worker declares neither SQLAlchemy nor sqlmodel, so the other two pins
  of the fleet-wide target generation (SQLAlchemy `2.0.54`, sqlmodel `0.0.46`)
  have nothing to move here.

### Added

- **`test-shipped-lock` — a CI job that actually runs the shipped set.**
  `pip-audit` and Trivy *scan* the lock; neither *executes* it, so until now
  nothing in this repository ever ran a test against the graph the release
  image installs. The new job installs
  `worker/requirements_prod.lock` with `--require-hashes` exactly as the
  Dockerfile does, derives a constraints file from it
  (`scripts/shipped_lock_env.py --emit-constraints`), adds the test tooling on
  top without dragging any shipped package forward, re-asserts that every lock
  pin is still installed at its locked version (`--verify`), and then runs the
  full suite at the 100 % coverage gate. Copied from `prompt-engine-m8`, the
  one repository in the fleet that already had it.
- **`scripts/shipped_lock_env.py`** — the lock-parsing helper the job above
  needs: `--emit-constraints` writes `name==version` for every pin, `--verify`
  fails if the environment has drifted from the lock in either direction.

## [1.0.1] - 2026-09-20

Debian patch-layer convergence — `B23-converge-patch-layer` (Wave 6) of the
workspace's consumer-alignment closure plan, finding `G18`; the form is
recorded once, in the workspace's `.workspace/context/debian-patch-layer.md`,
and the five service images now carry it byte-for-byte. Image-only patch
release: no job contract, payload, or dependency change; the worker still
consumes `media_sdk_m8`'s contracts unchanged and reports to `media-service-m8`
over the same internal API.

### Security

- **The runtime image's Debian layer is now the fleet's one form:**
  `apt-get update && apt-get upgrade -y`, nothing exact-pinned, nothing
  installed that the base does not already ship. The seven exact `=`
  pins (`openssl`, `libssl3t64`, `openssl-provider-legacy`, `gzip`,
  `libpcre2-8-0`, `libsqlite3-0`, `perl-base`) are gone and `apt-get
  upgrade -y` is back: each of those pins was raised by hand per advisory
  (`1.0.0`'s Security entry is the worked example) and froze the image on
  the pinned version until the next hand-raise, while every *other* Debian
  package moved only when the base digest moved. Now every package is raised
  on every build, and the next advisory needs no commit here.
  Mirrors `media-service-m8` `3.0.2`.
- **Base image raised to the current `python:3.14-slim` digest
  `caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2`**
  (Debian 13.7, Python 3.14.7, created 2026-09-19), from `83ff1d…` (Debian 13.6, which
  "predates the 13.7 point release" — the reason the seven pins existed).
  All five service images now pin this same digest, and from here on base
  digests move together — on advisory or on cadence, never one repository
  alone. Measured inside the new base: every package this fleet had ever
  pinned ships at or above its pinned version (`openssl` `3.5.7-1~deb13u2`,
  `gzip` `1.13-1+deb13u1`, `libpcre2-8-0` `10.46-1~deb13u2`, `libsqlite3-0`
  `3.46.1-7+deb13u2`, `perl-base` `5.40.1-6+deb13u1`), so `upgrade -y` is a
  no-op today and self-heals from the next advisory on.
- **`anyio` `4.14.1` → `4.14.2` in `worker/requirements_prod.lock`** — CVE-2026-63374
  (CRITICAL, TLS certificate spoofing via IDNA 2003 host-name encoding in
  `TLSStream`) and CVE-2026-63349 (HIGH, `run_process`/`open_process`
  retaining the parent's supplementary groups), both published 2026-09-18,
  after this repository's last green `trivy-image` run on `main`. Transitive
  (under `httpx`), so the hash-locked release set is the only place it
  appears; regenerated with `pip-compile --upgrade-package anyio==4.14.2`,
  so exactly one version line moves. Found by this release's own pre-PR
  Trivy read — the gate's freshness limit, not a property of the diff.
- Verified before the change was proposed: `docker build --no-cache` green
  on the new Dockerfile; Trivy at the `trivy-image` gate's own settings
  (`severity: CRITICAL,HIGH`, `ignore-unfixed: true`) reports **0**
  findings; inside the built container `openssl version` reads
  `OpenSSL 3.5.7`, `dpkg-query -W openssl libssl3t64 gzip libpcre2-8-0 libsqlite3-0
  perl-base` reads the 13.7 versions above, and `curl` is not installed.

## [1.0.0] - 2026-09-13

**Major: the `MINIO_*` → `S3_*` rename ships with no shim.** Object-storage backend migration plan, Waves 1-2
(`T9-consumers-repin`, `T11-worker-s3-rename`); folded into one release here
per the workspace's Wave 6c one-bump-per-unpublished-release rule
(`.workspace/context/version-sources.md`) since neither step took a version
number of its own. No Wave 3+ (SeaweedFS backend swap) content applies to
this repository — the worker only consumes `media_sdk_m8`'s storage client,
so the backend swap is invisible here; `T22-hygiene-dir-names` and the rest
of Waves 3-4 touched `media-service-m8`, `fa-ui-m8` and `security-tests-m8`
only.

### Security

- **Patched the runtime image past the Debian 13.7 point-release CVEs.** The
  `trivy-image` gate reported 12 findings (9 HIGH, 3 CRITICAL) against the
  pinned `python:3.14-slim` base: `gzip` (CVE-2026-41992), `libpcre2-8-0`
  (CVE-2026-86145, CVE-2026-89161), `libsqlite3-0` (CVE-2026-11822,
  CVE-2026-11824) and `perl-base` (CVE-2026-13221, CRITICAL). Debian shipped
  all four fixes in the 13.7 point release (2026-09-12) via `trixie` main, but
  the current upstream `python:3.14-slim` digest was built 2026-09-01 and
  still carries the vulnerable versions (verified by reading the new image's
  `/var/lib/dpkg/status`), so a base bump could not collect them. The four
  packages are exact-pinned in `worker/Dockerfile`'s existing apt patch
  layer alongside the OpenSSL pins: `gzip=1.13-1+deb13u1`,
  `libpcre2-8-0=10.46-1~deb13u2`, `libsqlite3-0=3.46.1-7+deb13u2`,
  `perl-base=5.40.1-6+deb13u1`. No `.trivyignore` entry added.

### Changed

- **Renamed the storage settings `MINIO_*` → `S3_*`** (`T11-worker-s3-rename`,
  object-storage backend migration plan, Wave 2). `worker/config.py`'s
  `WorkerConfig` now declares `S3_ENDPOINT`, `S3_USE_SSL`, `S3_REGION`,
  `S3_ACCESS_KEY` and `S3_SECRET_KEY` in place of `MINIO_HOST`/`MINIO_PORT`/
  `MINIO_USE_SSL`/`MINIO_REGION`/`MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`, and
  `S3_PRESIGNED_URL_EXPIRE_SECONDS` in place of
  `MINIO_PRESIGNED_URL_EXPIRE_SECONDS`. `MINIO_HOST`/`MINIO_PORT` collapse into
  the single `S3_ENDPOINT` netloc, mirroring `media-service-m8`'s
  `T10-settings-s3-rename`; a new `_validate_s3_endpoint` field validator
  (ported from that same commit) keeps the port-range guarantee the separate
  `MINIO_PORT: int` field gave and rejects a scheme-carrying value — the
  worker has no separate public endpoint to distinguish this from. Backend is
  still MinIO throughout; nothing observable changes at the storage boundary,
  only the variable names naming it.
  **This is a pure rename, with no deprecation shim** — unlike
  `media-service-m8`'s `Settings` (`extra="forbid"`), `WorkerConfig` already
  uses `extra="ignore"`, so an unmigrated `MINIO_*` deployment falls back to
  this config's own defaults/empty values rather than failing to load; the
  production fail-closed credential gate (`_fail_closed_credentials_in_production`)
  still refuses an empty/placeholder `S3_ACCESS_KEY`/`S3_SECRET_KEY` exactly as
  it refused the `MINIO_*` names before. The `MEDIA_INTERNAL_SERVICE_TOKEN !=
  S3_SECRET_KEY` isolation assertion (S8) and the `_is_unsafe` credential
  checks are unchanged in behaviour, only in the field name they read.
  `worker/.env.example` and `docker_compose/worker.env.example` (this
  repository's own copies) and `README.md`'s settings table move to the new
  names in the same commit, per the workspace env-policy sync rule; the seven
  stack-level `worker.env.example`/`worker.env.production.example` files in
  `media-service-m8` and `fa-ui-m8` are `T12-env-docs-sweep`'s scope, not this
  step's.
  Full suite 110 passed (was 99; 11 new cases cover the endpoint validator's
  accept/reject branches, ported from `media-service-m8`'s own `S3_ENDPOINT`
  test set), 100% coverage; ruff format/check and mypy clean; bandit clean.
  Ruff check's 4 `E402` findings in `tests/conftest.py` are pre-existing and
  unrelated (same finding `T9` recorded).

- **Repointed to `media-sdk-m8` `0.8.0`** (`T9-consumers-repin`, object-storage
  backend migration plan, Wave 1). `worker/requirements_base.txt`'s floor
  moves `>=0.7.0,<0.8.0` → `>=0.8.0,<0.9.0`; the direct `minio>=7.2.18` pin is
  dropped, since `media-sdk-m8` 0.8.0 no longer depends on it and no worker
  code imports it directly (confirmed by grep). `worker/requirements_prod.lock`
  was regenerated with `pip-compile`; the boto3/botocore closure now flows
  through transitively via the SDK. No worker source changed: `worker/config.py`,
  `worker/settings.py` and `worker/tasks.py` still import `ObjectStorageConfig`
  / `ObjectStorage` — both remain valid names in `0.8.0`
  (`T11-worker-s3-rename` owns the `MINIO_*` → `S3_*` vocabulary rename in
  Wave 2). Full suite 99 passed, 100% coverage; ruff/mypy/bandit clean (ruff
  check's 4 `E402` findings in `tests/conftest.py` are pre-existing and
  unrelated, confirmed via `git stash`). Verified against a real, pinned
  MinIO container (`quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z.hotfix.
  7aa24e772`, the same tag every stack in this fleet pins): `storage_config()`
  → `ObjectStorage` round-tripped `HeadBucket`, `PutObject`, `HeadObject`, the
  chunked `stream_object` read, and `DeleteObject` — confirming the SDK swap
  alone changes nothing observable at the worker's storage boundary.
  **`media-sdk-m8@0.8.0` is not yet published to PyPI** at the time of this
  commit (only `0.7.0` is; `pip index versions media-sdk-m8` confirms), so
  this pins ahead of that publish — the same inversion this fleet has
  recorded twice before for Docker image tags
  (`.workspace/context/version-sources.md`, `media-service-m8` `2.1.0` and
  `2.1.1`). `pip install --require-hashes -r worker/requirements_prod.lock`
  and a Docker image build from this branch will fail until
  `media-sdk-m8@0.8.0` is published; the regenerated lock was proven correct
  in the interim by installing it in an isolated venv against a locally built
  `0.8.0` wheel via `--find-links`. The window closed on 2026-09-15 when
  `media-sdk-m8@1.0.0` was published: the wheel PyPI serves does not
  hash-match the locally built one (build metadata differs), so the lock's
  `media-sdk-m8` entry was re-pinned to the published wheel and sdist
  hashes. `pip install --require-hashes` now resolves clean against PyPI.
  The same publish surfaced a leftover from the `minio` drop: the runtime
  stage's post-`pip uninstall` import guard in `worker/Dockerfile` still
  imported `minio`, which no longer ships in the image; it now imports
  `boto3`, the SDK's storage transport, so the guard keeps covering the
  storage path.

## [0.4.1] - 2026-08-26

### Security

- **Raised the runtime OpenSSL pin to `3.5.7-1~deb13u2`** (CVE-2026-14456 —
  denial of service via unbounded memory growth in the QUIC server). The
  published `0.4.0` image ships `3.5.6-1~deb13u2` and is affected; this release
  exists only to replace those bits. No worker code, task registration, payload
  schema or dependency floor changed — `0.4.0` and `0.4.1` are interchangeable
  at runtime.
- The patch block in `worker/Dockerfile` uses exact-equals apt pins, so it
  freezes the image at whatever version it names. That is what held `0.4.0` on
  the vulnerable OpenSSL after the advisory landed: raising the base image
  digest alone would not have moved it. Each new OpenSSL advisory requires this
  block to be raised explicitly.

## [0.4.0] - 2026-08-25

### Added

- **Delegated archive assembly (`P2 U11`).** `build_export_archive` validates the
  SDK-owned `ExportArchiveJobPayload`, streams source objects into a temporary
  ZIP, streams the finished file to storage, presigns it, and reports
  processing/completed/failed through media-service's token-guarded callback.
  Source-size drift and storage failure are terminal, clean up the deterministic
  target, and never publish a partial URL.
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

- **`media-sdk-m8` floor raised `>=0.6.0,<0.7.0` → `>=0.7.0,<0.8.0`.** `0.7.0`
  adds `ObjectStorage.put_object_stream`, the write-side counterpart of
  `stream_object`, for a consumer streaming an already-assembled payload into
  storage. The archive task now calls it; the shared floor keeps both
  `media-sdk-m8` consumers on one SDK version, which the previous `<0.7.0`
  upper bound would otherwise split, since under the SDK's 0.x SemVer a minor
  is breaking and the bound is deliberate.
  - **Reflected in `worker/requirements_prod.lock` after publication.** The
    lock was regenerated with `pip-compile --generate-hashes` on Linux against
    the published `media-sdk-m8` `0.7.0` artifacts. No second SDK release or
    version bump is required for this work.
- **Version bumped `0.3.0` → `0.4.0`** to align with the fleet version matrix.
  The only runtime change in this release is the additive
  `build_export_archive` task above; `scan_object` and `generate_variants`
  are unchanged, and everything else is tooling, lint and documentation.
- `.codacy.yml` excludes the repository's documentation files from analysis.
- **Base image digest bumped** for both `worker/Dockerfile` stages,
  `python:3.14-slim@sha256:c845af93…` → `@sha256:83ff1d24…`. The pinned digest
  was built 2026-05-19 and carried `util-linux` `2.41-5`, which Debian has since
  fixed in `2.41.5-0+deb13u1`; Trivy reported the resulting `CVE-2026-53612`,
  `-53613`, `-53614` and `-53615` 36 times — the same four CVEs across the nine
  binary packages built from that one source — and the `trivy-image` gate blocks
  the PR on HIGH findings. Nothing was added to a `.trivyignore`: the fix
  existed upstream, so the pin moved to collect it.
- **`pip`, `setuptools` and `wheel` removed from the runtime image stage.** The
  newer base bundles `setuptools 70.3.0` (`CVE-2025-47273`), which the previous
  digest did not — so the bump above traded 36 `util-linux` findings for 2
  `setuptools` ones. The entrypoint is `arq` and the image is built from a
  hash-locked set that never installs at run time, so the installer tooling is
  pure attack surface; removing it ends that class of finding rather than
  re-chasing a `setuptools` pin on every base-image bump. The uninstall is
  ordered after `COPY --from=builder` so the builder tree cannot reintroduce it,
  and is followed by an import check of the full runtime dependency graph, which
  fails the build if anything actually needed `pkg_resources` at import time.
- **CI test matrix floor raised to Python 3.12 (3.11 dropped)**, matching the
  fleet's accepted 3.12–3.14 range (`A32` follow-up). The Codecov and Codacy
  coverage uploads were conditioned on the 3.11 leg, so both moved to 3.12 with
  it — dropping the leg alone would have silently stopped every coverage upload.
- **`media-sdk-m8` floor raised `>=0.5.1` → `>=0.6.0,<0.7.0`.** The upper bound
  is new: under the SDK's 0.x SemVer a minor bump is breaking (`0.6.0` itself
  raises its Python floor to 3.12), so an unbounded floor would keep pulling
  breaking minors.
- **`imgtools_m8` floor raised `>=2.1.0` → `>=2.1.1`**, and
  `requirements_prod.lock` regenerated on Linux against the published releases.
  The lock this release ships hash-pins `imgtools_m8==2.1.1` and
  `media-sdk-m8==0.7.0` — the `0.6.0` lock produced by this step was superseded
  within the same release by the floor raise above. The regeneration also drops
  `colorama` — a Windows-only transitive of `click` that entered the lock from a
  Windows host and was never installable in the `python:3.14-slim` image, the
  same correction `media-service-m8` applied to its own lock.
- **4 further `RUF100` findings cleared in `tests/conftest.py`** — the same
  unpinned-ruff drift as the 20 below, surfacing after those were fixed. The
  four `# noqa: E402` directives on the post-env imports are unused, because
  ruff's default set does not enable `E402`. The directives were removed rather
  than suppressed, and the ordering constraint they documented — the worker
  package must not be imported before the deterministic test env is set, since
  `WorkerConfig` resolves at import time — is now stated as a comment above the
  import block, where a rule-set change cannot silently drop it.
- **20 `ruff check` findings fixed** (9 `I001`, 7 `RUF100`, and one each of
  `B017`, `BLE001`, `RUF012`, `SIM102`). All predated this release: `ruff.toml`
  declares only `line-length` and `exclude`, so the repository inherits ruff's
  default rule set, and CI installs ruff unpinned — the default set widening in
  ruff 0.16 turned them red. The two that are not mechanical are recorded here:
  `worker/tasks.py`'s variant-loop `except Exception` is the job-failure
  boundary and keeps its catch-all behaviour under an explicit `noqa` with that
  rationale, and `tests/test_image_guard.py` now asserts the `OSError` that
  `decoded_pixel_count` documents rather than a bare `Exception`.

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
