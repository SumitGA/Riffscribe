from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """API-only limits, from environment variables. Shared settings are `tabscribe_platform`'s."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    # 5 minutes of 16-bit 48 kHz stereo WAV is ~58 MB; compressed uploads are far smaller.
    max_upload_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    # Free tier (CLAUDE.md): jobs submitted per calendar month (UTC).
    free_jobs_per_month: int = Field(default=10, ge=0)
    # Rate limit on POST /jobs, per user.
    job_creates_per_minute: int = Field(default=10, gt=0)
    # Clerk Backend API key, to delete a user's sign-in with their account (DELETE /me).
    # Unset locally and in tests; set only in the server's .env.
    clerk_secret_key: SecretStr | None = None
