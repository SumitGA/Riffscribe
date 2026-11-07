from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    """API-only limits, from environment variables. Shared settings are `tabscribe_platform`'s."""

    model_config = SettingsConfigDict(frozen=True, extra="ignore")

    # Plan limits (ADR-0016, `api.plans`). Jobs count per calendar month (UTC); clip lengths are
    # checked by the normalize stage once the audio is decoded.
    # Free: 5 minutes of 16-bit 48 kHz stereo WAV is ~58 MB; compressed uploads are far smaller.
    max_upload_bytes: int = Field(default=64 * 1024 * 1024, gt=0)
    free_jobs_per_month: int = Field(default=10, ge=0)
    free_max_clip_s: int = Field(default=300, gt=0)
    # Pro (and unlimited, which has no monthly limit): 15 minutes of the same WAV is ~173 MB.
    pro_max_upload_bytes: int = Field(default=192 * 1024 * 1024, gt=0)
    pro_jobs_per_month: int = Field(default=100, ge=0)
    pro_max_clip_s: int = Field(default=900, gt=0)
    # Rate limit on POST /jobs, per user.
    job_creates_per_minute: int = Field(default=10, gt=0)
    # Clerk Backend API key, to delete a user's sign-in with their account (DELETE /me).
    # Unset locally and in tests; set only in the server's .env.
    clerk_secret_key: SecretStr | None = None
    # Uploading needs the current terms accepted (PUT /me/terms). Off only in unit tests that
    # aren't about terms.
    require_terms: bool = True
    # Who may use the admin section (/admin): Clerk user IDs, comma-separated. Empty: nobody.
    admin_user_ids: str = ""

    @property
    def admins(self) -> frozenset[str]:
        return frozenset(i.strip() for i in self.admin_user_ids.split(",") if i.strip())
