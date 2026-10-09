import json
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.auth import (
    AuthSettings,
    AuthUnavailableError,
    InvalidTokenError,
    TokenVerifier,
    get_token_verifier,
    issue_dev_token,
)
from api.deps import get_limiter
from api.devtoken import main as devtoken_main
from api.main import app

pytestmark = pytest.mark.unit

ISSUER = "https://issuer.example"
SECRET = "test-secret-that-is-at-least-32-chars"
DEV = AuthSettings(issuer=ISSUER, dev_secret=SECRET)


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": "alice", "iat": now, "exp": now + 60, **overrides}
    return {k: v for k, v in claims.items() if v is not None}


def _hs256(**overrides: Any) -> str:
    return jwt.encode(_claims(**overrides), SECRET, algorithm="HS256")


class NoQuotaUsed:
    def monthly_jobs_used(self, user_id: str) -> int:
        return 0


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(DEV)
    app.dependency_overrides[get_limiter] = NoQuotaUsed  # /me shows quota; no Redis here
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_settings_need_exactly_one_key_source() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        AuthSettings(issuer=ISSUER)
    with pytest.raises(ValidationError, match="exactly one"):
        AuthSettings(issuer=ISSUER, dev_secret=SECRET, jwks_url="https://x/jwks.json")
    with pytest.raises(ValidationError):
        AuthSettings(issuer=ISSUER, dev_secret="short")


def test_dev_token_round_trip() -> None:
    assert TokenVerifier(DEV).verify(issue_dev_token(DEV, "alice")).id == "alice"


@pytest.mark.parametrize(
    "token",
    [
        _hs256(exp=int(time.time()) - 3600),  # expired
        _hs256(iss="https://evil.example"),
        _hs256(exp=None),  # never expires
        _hs256(sub=None),
        _hs256(sub="../bob"),  # would escape the object-key prefix
        _hs256(token_use="id"),
        jwt.encode(_claims(), "another-secret-that-is-32-chars-long!", algorithm="HS256"),
        jwt.encode(_claims(), "", algorithm="none"),
        "not.a.jwt",
    ],
    ids=["expired", "issuer", "no-exp", "no-sub", "bad-sub", "id-token", "secret", "none", "junk"],
)
def test_rejected_tokens(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        TokenVerifier(DEV).verify(token)


def test_audience_matches_aud_or_cognito_client_id() -> None:
    verifier = TokenVerifier(AuthSettings(issuer=ISSUER, dev_secret=SECRET, audience="app"))
    assert verifier.verify(_hs256(aud="app")).id == "alice"
    assert verifier.verify(_hs256(aud=["other", "app"])).id == "alice"
    assert verifier.verify(_hs256(client_id="app")).id == "alice"
    with pytest.raises(InvalidTokenError, match="audience"):
        verifier.verify(_hs256(aud="other"))
    with pytest.raises(InvalidTokenError, match="audience"):
        verifier.verify(_hs256())


class TestJwks:
    """Production mode: RS256 with keys from the provider's JWKS endpoint."""

    @pytest.fixture
    def key(self) -> rsa.RSAPrivateKey:
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @pytest.fixture
    def verifier(self, key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch) -> TokenVerifier:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwks = {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}
        monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda _self: jwks)
        return TokenVerifier(AuthSettings(issuer=ISSUER, jwks_url="https://idp/jwks.json"))

    def test_valid_token(self, key: rsa.RSAPrivateKey, verifier: TokenVerifier) -> None:
        token = jwt.encode(_claims(), key, algorithm="RS256", headers={"kid": "k1"})
        assert verifier.verify(token).id == "alice"

    def test_clerk_session_token(self, key: rsa.RSAPrivateKey, verifier: TokenVerifier) -> None:
        # The claims of a Clerk (v2) session token: no `aud` or `token_use`, a `user_...` sub.
        clerk = _claims(
            sub="user_2xQd8ZbLwQjVYxN1fB7kq3",
            azp="riffscribe-app",
            sid="sess_2xQd9",
            nbf=int(time.time()) - 5,
            v=2,
        )
        token = jwt.encode(clerk, key, algorithm="RS256", headers={"kid": "k1"})
        assert verifier.verify(token).id == "user_2xQd8ZbLwQjVYxN1fB7kq3"

    def test_unknown_key(self, verifier: TokenVerifier) -> None:
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode(_claims(), other, algorithm="RS256", headers={"kid": "k2"})
        with pytest.raises(InvalidTokenError):
            verifier.verify(token)

    def test_dev_tokens_are_rejected(self, verifier: TokenVerifier) -> None:
        token = jwt.encode(_claims(), SECRET, algorithm="HS256", headers={"kid": "k1"})
        with pytest.raises(InvalidTokenError):
            verifier.verify(token)

    def test_unreachable_jwks(
        self, key: rsa.RSAPrivateKey, verifier: TokenVerifier, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def down(_self: jwt.PyJWKClient) -> None:
            raise jwt.PyJWKClientConnectionError("connection refused")

        monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", down)
        token = jwt.encode(_claims(), key, algorithm="RS256", headers={"kid": "k1"})
        with pytest.raises(AuthUnavailableError):
            verifier.verify(token)


def test_me(client: TestClient) -> None:
    response = client.get("/me", headers={"Authorization": f"Bearer {_hs256()}"})
    assert response.status_code == 200
    assert response.json()["user_id"] == "alice"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer junk"}])
def test_me_needs_a_valid_token(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get("/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")
    assert response.json() == {"detail": "missing bearer token" if not headers else "invalid token"}


def test_devtoken_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("JWT_ISSUER", ISSUER)
    monkeypatch.setenv("JWT_DEV_SECRET", SECRET)
    monkeypatch.delenv("JWT_JWKS_URL", raising=False)
    devtoken_main(["bob", "--ttl", "60"])
    assert TokenVerifier(DEV).verify(capsys.readouterr().out.strip()).id == "bob"
