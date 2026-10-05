import pytest
from pydantic import ValidationError

from tabscribe_platform.settings import MAX_PRESIGN_TTL_S, Settings

pytestmark = pytest.mark.unit

ENV = {
    "DATABASE_URL": "postgresql+psycopg://u:p@localhost:5432/tabscribe",
    "REDIS_URL": "redis://localhost:6379/0",
    "S3_BUCKET": "tabscribe",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_reads_environment(env: pytest.MonkeyPatch) -> None:
    env.setenv("S3_ENDPOINT_URL", "http://seaweedfs:8333")
    settings = Settings()
    assert settings.s3_bucket == "tabscribe"
    assert settings.s3_endpoint_url == "http://seaweedfs:8333"
    assert settings.presign_ttl_s == MAX_PRESIGN_TTL_S


def test_missing_required_setting_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_presigned_urls_live_at_most_15_minutes(env: pytest.MonkeyPatch) -> None:
    env.setenv("PRESIGN_TTL_S", str(MAX_PRESIGN_TTL_S + 1))
    with pytest.raises(ValidationError):
        Settings()


def test_public_endpoint_needs_endpoint(env: pytest.MonkeyPatch) -> None:
    env.setenv("S3_PUBLIC_ENDPOINT_URL", "http://localhost:8333")
    with pytest.raises(ValidationError):
        Settings()
