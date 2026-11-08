"""API settings from the environment."""

import pytest

from api.settings import ApiSettings


@pytest.mark.parametrize(
    "name", ["CLERK_SECRET_KEY", "REVENUECAT_SECRET_API_KEY", "REVENUECAT_WEBHOOK_SECRET"]
)
def test_an_empty_secret_is_unset(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    # docker compose passes `${X:-}` as an empty string when X isn't in the .env.
    monkeypatch.setenv(name, "")
    assert getattr(ApiSettings(), name.lower()) is None
    monkeypatch.setenv(name, "  ")
    assert getattr(ApiSettings(), name.lower()) is None
    monkeypatch.setenv(name, "sk_123")
    secret = getattr(ApiSettings(), name.lower())
    assert secret is not None and secret.get_secret_value() == "sk_123"
