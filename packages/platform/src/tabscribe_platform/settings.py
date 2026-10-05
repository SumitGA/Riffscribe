"""All configuration comes from environment variables (12-factor); there are no config files."""

from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# CLAUDE.md: presigned URLs expire in 15 minutes or less.
MAX_PRESIGN_TTL_S = 15 * 60


class Settings(BaseSettings):
    """Settings shared by the API and the worker.

    S3 credentials are not here: boto3 reads AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY itself.
    """

    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    database_url: PostgresDsn
    redis_url: RedisDsn

    s3_bucket: str = Field(min_length=3)
    # Unset means AWS S3; set it for R2 or the local SeaweedFS server (ADR-0002, ADR-0007).
    s3_endpoint_url: str | None = None
    # The endpoint clients use for presigned URLs, when it differs from the one services use
    # (locally, services reach `seaweedfs:8333` but the host reaches `localhost:8333`).
    s3_public_endpoint_url: str | None = None
    s3_region: str = "auto"
    presign_ttl_s: int = Field(default=MAX_PRESIGN_TTL_S, gt=0, le=MAX_PRESIGN_TTL_S)

    @model_validator(mode="after")
    def _public_endpoint_needs_endpoint(self) -> "Settings":
        if self.s3_public_endpoint_url and not self.s3_endpoint_url:
            raise ValueError("S3_PUBLIC_ENDPOINT_URL needs S3_ENDPOINT_URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
