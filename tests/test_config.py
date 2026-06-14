"""Tests for worker.config — env-driven settings + SDK config building."""

from pydantic import SecretStr

from media_sdk_m8 import ObjectStorageConfig

from worker.config import DEFAULT_CLAMAV_PORT, WorkerConfig, get_config


def test_storage_config_maps_env_to_sdk_config():
    cfg = WorkerConfig(
        MINIO_HOST="minio",
        MINIO_PORT=9000,
        MINIO_USE_SSL=True,
        MINIO_REGION="eu-west-1",
        MINIO_ACCESS_KEY="ak",
        MINIO_SECRET_KEY=SecretStr("sk"),
        MINIO_PRESIGNED_URL_EXPIRE_SECONDS=600,
    )
    storage_config = cfg.storage_config()
    assert isinstance(storage_config, ObjectStorageConfig)
    assert storage_config.endpoint == "minio:9000"
    assert storage_config.access_key == "ak"
    assert storage_config.secret_key == "sk"
    assert storage_config.secure is True
    assert storage_config.region == "eu-west-1"
    assert storage_config.presigned_expire_seconds == 600


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
