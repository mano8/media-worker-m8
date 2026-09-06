"""Self-contained worker configuration.

The worker reads its **own** environment (it never imports media-service): the
media-owned Redis, the S3/object-storage connection, the media-service
internal API base URL + shared service token, and the ClamAV daemon address.

It builds the shared-SDK :class:`~media_sdk_m8.ObjectStorageConfig` from that
env so the storage client stays settings-agnostic.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from media_sdk_m8 import ObjectStorageConfig
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: ``S3_ENDPOINT`` default (matches the compose stacks' storage service name).
_DEFAULT_S3_ENDPOINT = "minio:9000"

#: Default clamd TCP port (the ``clamav`` compose service listens here).
DEFAULT_CLAMAV_PORT = 3310

#: Placeholder value used in ``*.env.example`` (fail-closed). Production/strict
#: boot refuses any required secret still set to this literal.
PLACEHOLDER_SECRET = "changethis"  # nosec B105


class WorkerConfig(BaseSettings):
    """Environment-driven settings for the media worker."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # ── Runtime posture ───────────────────────────────────────────────────────
    #: Deployment environment, aligned with the auth/media service settings
    #: (``auth_sdk_m8`` / ``media_service`` use the same Literal). ``local`` is
    #: the home-lab default that intentionally tolerates placeholder credentials.
    ENVIRONMENT: Literal["local", "development", "staging", "production"] = "local"
    #: Force the production trust posture regardless of ``ENVIRONMENT``. Mirrors
    #: the service-side ``STRICT_PRODUCTION_MODE`` flag.
    STRICT_PRODUCTION_MODE: bool = False

    # ── Media-service internal API ────────────────────────────────────────────
    #: Base URL of media-service including its API prefix (e.g. ``…:8000/media``).
    #: The worker appends ``/v1/internal/…`` to reach the service-token routes.
    MEDIA_API_URL: str = "http://media-service:8000/media"
    #: Bearer token presented on every internal callback. Compared with
    #: ``secrets.compare_digest`` on the service side; high-entropy in prod.
    #: Must not equal MEDIA_REDIS_PASSWORD or S3_SECRET_KEY.
    MEDIA_INTERNAL_SERVICE_TOKEN: SecretStr = SecretStr("changethis")
    #: Stable identity sent as ``X-Worker-Client`` on every callback so
    #: media-service can attribute requests to this specific worker instance.
    WORKER_CLIENT_ID: str = "media-worker"
    #: Per-request timeout (seconds) for internal HTTP callbacks.
    MEDIA_API_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)

    # ── Media Redis (ARQ queue) ───────────────────────────────────────────────
    MEDIA_REDIS_HOST: str = "media_redis_cache"
    MEDIA_REDIS_PORT: int = Field(default=6379, ge=1, le=65535)
    MEDIA_REDIS_USER: str = "appuser"
    MEDIA_REDIS_PASSWORD: SecretStr | None = None
    MEDIA_REDIS_NAMESPACE: str = "media"

    # ── S3 / object storage ───────────────────────────────────────────────────
    #: Scheme-less ``host[:port]``; TLS is selected by ``S3_USE_SSL``, never by
    #: a URL scheme here.
    S3_ENDPOINT: str = _DEFAULT_S3_ENDPOINT
    S3_USE_SSL: bool = False
    S3_REGION: str = "eu-west-1"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: SecretStr = SecretStr("")
    S3_PRESIGNED_URL_EXPIRE_SECONDS: int = Field(default=300, ge=1)

    @field_validator("S3_ENDPOINT")
    @classmethod
    def _validate_s3_endpoint(cls, value: str) -> str:
        """Require a scheme-less ``host[:port]`` endpoint.

        Keeps the port-range guarantee the previous separate ``MINIO_PORT``
        field gave, and rejects a URL early rather than letting the S3 client
        build ``https://https://host`` at the first request. The worker has
        no public-facing endpoint to distinguish this from, unlike
        ``media_service``'s ``S3_PUBLIC_ENDPOINT``.
        """
        endpoint = value.strip()
        if not endpoint:
            raise ValueError(
                "CONFIG: S3_ENDPOINT must not be empty (expected 'host:port')."
            )
        if "://" in endpoint:
            raise ValueError(
                f"CONFIG: S3_ENDPOINT must be a scheme-less 'host[:port]' value; "
                f"got {endpoint!r} — use S3_USE_SSL for TLS."
            )
        host, separator, port = endpoint.rpartition(":")
        # ``endswith(']')`` is a bracketed IPv6 literal with no port.
        if separator and not endpoint.endswith("]"):
            if not port.isdigit() or not 1 <= int(port) <= 65535:
                raise ValueError(
                    f"CONFIG: S3_ENDPOINT port must be a number between 1 and "
                    f"65535; got {port!r}."
                )
            if not host:
                raise ValueError(
                    f"CONFIG: S3_ENDPOINT must include a host; got {endpoint!r}."
                )
        return endpoint

    # ── ClamAV daemon ─────────────────────────────────────────────────────────
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = Field(default=DEFAULT_CLAMAV_PORT, ge=1, le=65535)
    #: Socket timeout (seconds) for the clamd ``INSTREAM`` scan call.
    CLAMAV_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)

    # ── ARQ tuning ────────────────────────────────────────────────────────────
    WORKER_MAX_TRIES: int = Field(default=5, ge=1)
    WORKER_JOB_TIMEOUT_SECONDS: int = Field(default=300, ge=1)
    WORKER_KEEP_RESULT_SECONDS: int = Field(default=3600, ge=0)
    #: Max jobs this worker process runs concurrently (ARQ ``max_jobs``). Bounds
    #: peak worker memory together with the per-job source/decoded ceilings:
    #: roughly ``WORKER_MAX_CONCURRENT_JOBS × (decoded image + output budget)``.
    #: Pair with a container memory limit sized for that ceiling.
    WORKER_MAX_CONCURRENT_JOBS: int = Field(default=4, ge=1)

    # ── Variant cost ceilings (P0.3 defense in depth) ─────────────────────────
    # Local safety ceilings for an independent runtime: even if a malformed or
    # stale job bypasses media-service's request-policy bounds, the worker
    # refuses unsafe workloads at its own trust boundary. media-service remains
    # the request-policy owner; these are not user-facing policy.
    #: Max source object size (bytes) accepted from storage metadata before any
    #: download. Refused pre-download so an oversized source costs no transfer.
    WORKER_MAX_SOURCE_BYTES: int = Field(default=64 * 1024 * 1024, ge=1)
    #: Max number of variant specs rendered per job (output fan-out bound).
    WORKER_MAX_OUTPUTS_PER_JOB: int = Field(default=32, ge=1)
    #: Max total written output bytes per job (storage-write amplification bound).
    WORKER_MAX_OUTPUT_BYTES: int = Field(default=128 * 1024 * 1024, ge=1)
    #: Wall-clock ceiling (seconds) for the single image-processing render call.
    #: Must stay <= WORKER_JOB_TIMEOUT_SECONDS so the worker fails the job
    #: terminally (clean FAILED status) before ARQ kills and retries it.
    WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)

    # ── Memory guards (P1.2 — streaming scan + decode bomb defense) ────────────
    #: Max source object size (bytes) accepted on the **scan** path, read from
    #: storage metadata before any stream. Scanning is streamed chunk-by-chunk so
    #: worker memory stays bounded regardless of object size; this ceiling caps
    #: abuse and must stay <= the clamd ``StreamMaxLength``. An object over the
    #: ceiling (or of unknown size) is failed closed — quarantined, never marked
    #: clean. Larger than the variant ceiling because scanning also covers
    #: non-image uploads, which need no in-memory decode.
    WORKER_MAX_SCAN_BYTES: int = Field(default=256 * 1024 * 1024, ge=1)
    #: Max decoded pixel count (width × height) accepted for a variant source,
    #: read from the image header before the full decode. Defends against
    #: decompression-bomb images whose encoded bytes are small but whose decoded
    #: raster would exhaust memory. 50 MP ≈ 200 MB at RGBA; pair with the
    #: concurrency bound and a container memory limit. Stays under Pillow's own
    #: ``MAX_IMAGE_PIXELS`` (~89 MP) so this explicit gate fires first.
    WORKER_MAX_DECODED_PIXELS: int = Field(default=50_000_000, ge=1)

    @model_validator(mode="after")
    def _assert_process_timeout_within_job_timeout(self) -> "WorkerConfig":
        if self.WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS > self.WORKER_JOB_TIMEOUT_SECONDS:
            raise ValueError(
                "WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS must not exceed "
                "WORKER_JOB_TIMEOUT_SECONDS"
            )
        return self

    @property
    def is_production(self) -> bool:
        """True when the worker runs under the production/strict trust posture."""
        return self.ENVIRONMENT == "production" or self.STRICT_PRODUCTION_MODE

    @model_validator(mode="after")
    def _fail_closed_credentials_in_production(self) -> "WorkerConfig":
        """Refuse to boot with default/empty/placeholder secrets in production.

        ``local`` (the home-lab default) intentionally tolerates the
        ``changethis`` placeholders so the example stack still boots; under
        ``ENVIRONMENT == "production"`` or ``STRICT_PRODUCTION_MODE`` every
        required secret must be a real, non-placeholder value or the process
        fails closed at import — not only behind the compose preflight.
        """
        if not self.is_production:
            return self

        def _is_unsafe(value: str) -> bool:
            return value == "" or value == PLACEHOLDER_SECRET

        unsafe: list[str] = []
        if _is_unsafe(self.MEDIA_INTERNAL_SERVICE_TOKEN.get_secret_value()):
            unsafe.append("MEDIA_INTERNAL_SERVICE_TOKEN")
        if _is_unsafe(self.S3_ACCESS_KEY):
            unsafe.append("S3_ACCESS_KEY")
        if _is_unsafe(self.S3_SECRET_KEY.get_secret_value()):
            unsafe.append("S3_SECRET_KEY")
        # Redis auth is required whenever a Redis username is configured (the
        # compose stack always sets ``appuser``); an unset/placeholder password
        # then fails closed too.
        if self.MEDIA_REDIS_USER:
            password = self.redis_password
            if password is None or _is_unsafe(password):
                unsafe.append("MEDIA_REDIS_PASSWORD")

        if unsafe:
            raise ValueError(
                "Worker refuses to boot under production/strict mode with "
                "default, empty, or placeholder credentials: " + ", ".join(unsafe)
            )
        return self

    @model_validator(mode="after")
    def _assert_token_not_reused(self) -> "WorkerConfig":
        token = self.MEDIA_INTERNAL_SERVICE_TOKEN.get_secret_value()
        if (
            self.MEDIA_REDIS_PASSWORD is not None
            and token == self.MEDIA_REDIS_PASSWORD.get_secret_value()
        ):
            raise ValueError(
                "MEDIA_INTERNAL_SERVICE_TOKEN must not equal MEDIA_REDIS_PASSWORD"
            )
        s3_key = self.S3_SECRET_KEY.get_secret_value()
        if s3_key and token == s3_key:
            raise ValueError(
                "MEDIA_INTERNAL_SERVICE_TOKEN must not equal S3_SECRET_KEY"
            )
        return self

    @property
    def redis_password(self) -> str | None:
        """Plain Redis password, or ``None`` when unset."""
        return (
            self.MEDIA_REDIS_PASSWORD.get_secret_value()
            if self.MEDIA_REDIS_PASSWORD
            else None
        )

    @property
    def service_token(self) -> str:
        """Plain shared service token for internal callbacks."""
        return self.MEDIA_INTERNAL_SERVICE_TOKEN.get_secret_value()

    @property
    def api_base_url(self) -> str:
        """Media-service base URL with any trailing slash removed."""
        return self.MEDIA_API_URL.rstrip("/")

    def storage_config(self) -> ObjectStorageConfig:
        """Build the shared-SDK object-storage config from this env."""
        return ObjectStorageConfig(
            endpoint=self.S3_ENDPOINT,
            access_key=self.S3_ACCESS_KEY,
            secret_key=self.S3_SECRET_KEY.get_secret_value(),
            secure=self.S3_USE_SSL,
            region=self.S3_REGION,
            presigned_expire_seconds=self.S3_PRESIGNED_URL_EXPIRE_SECONDS,
        )


@lru_cache
def get_config() -> WorkerConfig:
    """Return the process-wide worker config (cached)."""
    return WorkerConfig()
