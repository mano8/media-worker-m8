"""Self-contained worker configuration.

The worker reads its **own** environment (it never imports media-service): the
media-owned Redis, the MinIO/object-storage connection, the media-service
internal API base URL + shared service token, and the ClamAV daemon address.

It builds the shared-SDK :class:`~media_sdk_m8.ObjectStorageConfig` from that
env so the storage client stays settings-agnostic.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from media_sdk_m8 import ObjectStorageConfig

#: Default clamd TCP port (the ``clamav`` compose service listens here).
DEFAULT_CLAMAV_PORT = 3310


class WorkerConfig(BaseSettings):
    """Environment-driven settings for the media worker."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # ── Media-service internal API ────────────────────────────────────────────
    #: Base URL of media-service including its API prefix (e.g. ``…:8000/media``).
    #: The worker appends ``/v1/internal/…`` to reach the service-token routes.
    MEDIA_API_URL: str = "http://media-service:8000/media"
    #: Bearer token presented on every internal callback. Compared with
    #: ``secrets.compare_digest`` on the service side; high-entropy in prod.
    #: Must not equal MEDIA_REDIS_PASSWORD or MINIO_SECRET_KEY.
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

    # ── MinIO / object storage ────────────────────────────────────────────────
    MINIO_HOST: str = "minio"
    MINIO_PORT: int = Field(default=9000, ge=1, le=65535)
    MINIO_USE_SSL: bool = False
    MINIO_REGION: str = "eu-west-1"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: SecretStr = SecretStr("")
    MINIO_PRESIGNED_URL_EXPIRE_SECONDS: int = Field(default=300, ge=1)

    # ── ClamAV daemon ─────────────────────────────────────────────────────────
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = Field(default=DEFAULT_CLAMAV_PORT, ge=1, le=65535)
    #: Socket timeout (seconds) for the clamd ``INSTREAM`` scan call.
    CLAMAV_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)

    # ── ARQ tuning ────────────────────────────────────────────────────────────
    WORKER_MAX_TRIES: int = Field(default=5, ge=1)
    WORKER_JOB_TIMEOUT_SECONDS: int = Field(default=300, ge=1)
    WORKER_KEEP_RESULT_SECONDS: int = Field(default=3600, ge=0)

    @model_validator(mode="after")
    def _assert_token_not_reused(self) -> "WorkerConfig":
        token = self.MEDIA_INTERNAL_SERVICE_TOKEN.get_secret_value()
        if self.MEDIA_REDIS_PASSWORD is not None:
            if token == self.MEDIA_REDIS_PASSWORD.get_secret_value():
                raise ValueError(
                    "MEDIA_INTERNAL_SERVICE_TOKEN must not equal MEDIA_REDIS_PASSWORD"
                )
        minio_key = self.MINIO_SECRET_KEY.get_secret_value()
        if minio_key and token == minio_key:
            raise ValueError(
                "MEDIA_INTERNAL_SERVICE_TOKEN must not equal MINIO_SECRET_KEY"
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
            endpoint=f"{self.MINIO_HOST}:{self.MINIO_PORT}",
            access_key=self.MINIO_ACCESS_KEY,
            secret_key=self.MINIO_SECRET_KEY.get_secret_value(),
            secure=self.MINIO_USE_SSL,
            region=self.MINIO_REGION,
            presigned_expire_seconds=self.MINIO_PRESIGNED_URL_EXPIRE_SECONDS,
        )


@lru_cache
def get_config() -> WorkerConfig:
    """Return the process-wide worker config (cached)."""
    return WorkerConfig()
