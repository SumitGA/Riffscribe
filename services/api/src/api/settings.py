from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tabscribe_platform.db import BillingEnvironment


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
    # Store subscriptions through RevenueCat (ADR-0016, `api.billing`). Both secrets unset:
    # billing is off (the webhook answers 404). The secret API key (sk_..., RevenueCat >
    # Project settings > API keys) reads customers; the webhook secret is what RevenueCat sends
    # in the Authorization header.
    revenuecat_secret_api_key: SecretStr | None = None
    revenuecat_webhook_secret: SecretStr | None = None
    # Which purchases count here: staging takes the stores' test purchases (sandbox), production
    # only real ones. Production by default, so a forgotten setting never makes test purchases
    # unlock Pro for free.
    billing_environment: BillingEnvironment = BillingEnvironment.PRODUCTION
    # The RevenueCat entitlement that means Pro.
    revenuecat_entitlement: str = "pro"
    # Who may use the admin section (/admin): Clerk user IDs, comma-separated. Empty: nobody.
    admin_user_ids: str = ""

    @field_validator(
        "clerk_secret_key", "revenuecat_secret_api_key", "revenuecat_webhook_secret", mode="before"
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        # compose passes an unset variable as "" (`${X:-}`); that must mean "not configured",
        # never a secret that is the empty string.
        if isinstance(value, str | SecretStr):
            raw = value.get_secret_value() if isinstance(value, SecretStr) else value
            if not raw.strip():
                return None
        return value

    @property
    def admins(self) -> frozenset[str]:
        return frozenset(i.strip() for i in self.admin_user_ids.split(",") if i.strip())
