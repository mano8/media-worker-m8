"""Tests for worker.config — env-driven settings + SDK config building."""

import pytest
from media_sdk_m8 import ObjectStorageConfig
from pydantic import SecretStr, ValidationError

from worker.config import (
    DEFAULT_CLAMAV_PORT,
    PLACEHOLDER_SECRET,
    WorkerConfig,
    get_config,
)


def test_storage_config_maps_env_to_sdk_config():
    cfg = WorkerConfig(
        S3_ENDPOINT="minio:9000",
        S3_USE_SSL=True,
        S3_REGION="eu-west-1",
        S3_ACCESS_KEY="ak",
        S3_SECRET_KEY=SecretStr("sk"),
        S3_PRESIGNED_URL_EXPIRE_SECONDS=600,
    )
    storage_config = cfg.storage_config()
    assert isinstance(storage_config, ObjectStorageConfig)
    assert storage_config.endpoint == "minio:9000"
    assert storage_config.access_key == "ak"
    assert storage_config.secret_key == "sk"
    assert storage_config.secure is True
    assert storage_config.region == "eu-west-1"
    assert storage_config.presigned_expire_seconds == 600


def test_s3_endpoint_default_matches_the_legacy_host_port_pair():
    """The default netloc is exactly what MINIO_HOST/MINIO_PORT defaulted to."""
    assert WorkerConfig().S3_ENDPOINT == "minio:9000"


def test_s3_endpoint_with_scheme_rejected():
    with pytest.raises(ValidationError, match="scheme-less"):
        WorkerConfig(S3_ENDPOINT="https://storage.example.com:9000")


def test_s3_endpoint_empty_rejected():
    with pytest.raises(ValidationError, match="must not be empty"):
        WorkerConfig(S3_ENDPOINT="  ")


@pytest.mark.parametrize("endpoint", ["storage:0", "storage:65536", "storage:nine"])
def test_s3_endpoint_invalid_port_rejected(endpoint):
    with pytest.raises(ValidationError, match="port must be a number"):
        WorkerConfig(S3_ENDPOINT=endpoint)


def test_s3_endpoint_without_host_rejected():
    with pytest.raises(ValidationError, match="must include a host"):
        WorkerConfig(S3_ENDPOINT=":9000")


@pytest.mark.parametrize("endpoint", ["storage", "storage:9000", "[::1]", "[::1]:9000"])
def test_s3_endpoint_accepted_forms(endpoint):
    assert WorkerConfig(S3_ENDPOINT=endpoint).S3_ENDPOINT == endpoint


def test_api_base_url_strips_trailing_slash():
    cfg = WorkerConfig(MEDIA_API_URL="http://host:8000/media/")
    assert cfg.api_base_url == "http://host:8000/media"


def test_service_token_unwraps_secret():
    cfg = WorkerConfig(MEDIA_INTERNAL_SERVICE_TOKEN=SecretStr("s3cr3t"))
    assert cfg.service_token == "s3cr3t"


def test_redis_password_none_when_unset():
    cfg = WorkerConfig(MEDIA_REDIS_PASSWORD=None)
    assert cfg.redis_password is None


def test_redis_password_unwrapped_when_set():
    cfg = WorkerConfig(MEDIA_REDIS_PASSWORD=SecretStr("pw"))
    assert cfg.redis_password == "pw"


def test_default_clamav_port_constant():
    cfg = WorkerConfig()
    assert cfg.CLAMAV_PORT == DEFAULT_CLAMAV_PORT == 3310


def test_get_config_is_cached():
    get_config.cache_clear()
    first = get_config()
    second = get_config()
    assert first is second


def test_worker_client_id_default():
    cfg = WorkerConfig()
    assert cfg.WORKER_CLIENT_ID == "media-worker"


def test_credential_isolation_token_not_redis_password():
    with pytest.raises(ValidationError, match="MEDIA_INTERNAL_SERVICE_TOKEN"):
        WorkerConfig(
            MEDIA_INTERNAL_SERVICE_TOKEN=SecretStr("SharedSecret!1secure"),
            MEDIA_REDIS_PASSWORD=SecretStr("SharedSecret!1secure"),
        )


def test_credential_isolation_token_not_s3_key():
    with pytest.raises(ValidationError, match="MEDIA_INTERNAL_SERVICE_TOKEN"):
        WorkerConfig(
            MEDIA_INTERNAL_SERVICE_TOKEN=SecretStr("SharedSecret!1secure"),
            S3_SECRET_KEY=SecretStr("SharedSecret!1secure"),
        )


def test_image_process_timeout_must_not_exceed_job_timeout():
    with pytest.raises(ValidationError, match="WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS"):
        WorkerConfig(
            WORKER_JOB_TIMEOUT_SECONDS=30,
            WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS=31,
        )


def test_variant_cost_ceiling_defaults():
    cfg = WorkerConfig()
    assert cfg.WORKER_MAX_SOURCE_BYTES == 64 * 1024 * 1024
    assert cfg.WORKER_MAX_OUTPUTS_PER_JOB == 32
    assert cfg.WORKER_MAX_OUTPUT_BYTES == 128 * 1024 * 1024
    assert cfg.WORKER_IMAGE_PROCESS_TIMEOUT_SECONDS == 120.0


def test_memory_guard_and_concurrency_defaults():
    cfg = WorkerConfig()
    assert cfg.WORKER_MAX_SCAN_BYTES == 256 * 1024 * 1024
    assert cfg.WORKER_MAX_DECODED_PIXELS == 50_000_000
    assert cfg.WORKER_MAX_CONCURRENT_JOBS == 4


def test_credential_isolation_distinct_credentials_accepted():
    cfg = WorkerConfig(
        MEDIA_INTERNAL_SERVICE_TOKEN=SecretStr("ServiceToken!1secure"),
        MEDIA_REDIS_PASSWORD=SecretStr("RedisPass!1secure"),
        S3_SECRET_KEY=SecretStr("S3Key!1secure"),
    )
    assert cfg.service_token == "ServiceToken!1secure"


# ── Fail-closed production credential gate (P1.1) ─────────────────────────────
def test_environment_defaults_to_local():
    cfg = WorkerConfig()
    assert cfg.ENVIRONMENT == "local"
    assert cfg.STRICT_PRODUCTION_MODE is False
    assert cfg.is_production is False


def test_is_production_under_production_environment():
    cfg = WorkerConfig(ENVIRONMENT="production")
    assert cfg.is_production is True


def test_is_production_under_strict_mode():
    cfg = WorkerConfig(ENVIRONMENT="local", STRICT_PRODUCTION_MODE=True)
    assert cfg.is_production is True


def test_local_mode_tolerates_placeholder_credentials():
    cfg = WorkerConfig(
        ENVIRONMENT="local",
        MEDIA_INTERNAL_SERVICE_TOKEN=SecretStr(PLACEHOLDER_SECRET),
        S3_ACCESS_KEY="",
        S3_SECRET_KEY=SecretStr(""),
        MEDIA_REDIS_PASSWORD=None,
    )
    assert cfg.service_token == PLACEHOLDER_SECRET


def test_production_rejects_placeholder_service_token():
    with pytest.raises(ValidationError, match="MEDIA_INTERNAL_SERVICE_TOKEN"):
        WorkerConfig(
            ENVIRONMENT="production",
            MEDIA_INTERNAL_SERVICE_TOKEN=SecretStr(PLACEHOLDER_SECRET),
        )


def test_strict_mode_rejects_placeholder_service_token():
    with pytest.raises(ValidationError, match="MEDIA_INTERNAL_SERVICE_TOKEN"):
        WorkerConfig(
            ENVIRONMENT="local",
            STRICT_PRODUCTION_MODE=True,
            MEDIA_INTERNAL_SERVICE_TOKEN=SecretStr(PLACEHOLDER_SECRET),
        )


def test_production_rejects_empty_s3_access_key():
    with pytest.raises(ValidationError, match="S3_ACCESS_KEY"):
        WorkerConfig(ENVIRONMENT="production", S3_ACCESS_KEY="")


def test_production_rejects_placeholder_s3_secret_key():
    with pytest.raises(ValidationError, match="S3_SECRET_KEY"):
        WorkerConfig(
            ENVIRONMENT="production",
            S3_SECRET_KEY=SecretStr(PLACEHOLDER_SECRET),
        )


def test_production_rejects_missing_redis_password_when_user_set():
    with pytest.raises(ValidationError, match="MEDIA_REDIS_PASSWORD"):
        WorkerConfig(
            ENVIRONMENT="production",
            MEDIA_REDIS_USER="appuser",
            MEDIA_REDIS_PASSWORD=None,
        )


def test_production_rejects_placeholder_redis_password_when_user_set():
    with pytest.raises(ValidationError, match="MEDIA_REDIS_PASSWORD"):
        WorkerConfig(
            ENVIRONMENT="production",
            MEDIA_REDIS_USER="appuser",
            MEDIA_REDIS_PASSWORD=SecretStr(PLACEHOLDER_SECRET),
        )


def test_production_allows_missing_redis_password_when_auth_disabled():
    cfg = WorkerConfig(
        ENVIRONMENT="production",
        MEDIA_REDIS_USER="",
        MEDIA_REDIS_PASSWORD=None,
    )
    assert cfg.redis_password is None
    assert cfg.is_production is True


def test_production_accepts_real_credentials():
    cfg = WorkerConfig(
        ENVIRONMENT="production",
        MEDIA_INTERNAL_SERVICE_TOKEN=SecretStr("ServiceToken!1secure"),
        S3_ACCESS_KEY="s3-admin",
        S3_SECRET_KEY=SecretStr("S3Key!1secure"),
        MEDIA_REDIS_USER="appuser",
        MEDIA_REDIS_PASSWORD=SecretStr("RedisPass!1secure"),
    )
    assert cfg.is_production is True
    assert cfg.service_token == "ServiceToken!1secure"
