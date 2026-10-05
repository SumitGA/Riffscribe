"""JWT authentication. The API only validates tokens; the auth provider issues them.

Production: RS256 tokens from a managed provider (AWS Cognito by default), checked against its
JWKS. Local dev and tests: HS256 tokens signed with a throwaway shared secret by `issue_dev_token`
(`make token`), so no provider account is needed (TD-17). Exactly one mode is configured, and
each accepts only its own algorithm, so an HS256 token can't pass in production.
"""

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tabscribe_platform.storage import user_prefix


class AuthSettings(BaseSettings):
    """`JWT_*` environment variables. Only the API reads them."""

    model_config = SettingsConfigDict(env_prefix="JWT_", frozen=True, extra="ignore")

    issuer: str = Field(min_length=1)  # Cognito: https://cognito-idp.{region}.amazonaws.com/{pool}
    # Cognito access tokens carry the app client ID in `client_id` rather than `aud`; either
    # matches. Unset: not checked.
    audience: str | None = None
    jwks_url: str | None = None  # production: the provider's public signing keys
    dev_secret: SecretStr | None = Field(default=None, min_length=32)  # local dev and tests only
    leeway_s: int = Field(default=30, ge=0)  # clock skew allowed on exp/iat

    @model_validator(mode="after")
    def _exactly_one_key_source(self) -> "AuthSettings":
        if (self.jwks_url is None) == (self.dev_secret is None):
            raise ValueError("set exactly one of JWT_JWKS_URL and JWT_DEV_SECRET")
        return self


@dataclass(frozen=True)
class CurrentUser:
    id: str  # the token's `sub`; also the users table key and the object-key prefix


class InvalidTokenError(Exception):
    """The token is malformed, expired, wrongly signed or not meant for us (HTTP 401)."""


class AuthUnavailableError(Exception):
    """The provider's signing keys can't be fetched (HTTP 503: not the client's fault)."""


class TokenVerifier:
    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings
        self._jwks: jwt.PyJWKClient | None = None
        if settings.jwks_url:
            # Keys are cached for an hour; an unknown `kid` (key rotation) triggers a refetch.
            self._jwks = jwt.PyJWKClient(settings.jwks_url, lifespan=3600, timeout=5)

    def verify(self, token: str) -> CurrentUser:
        settings = self._settings
        try:
            if self._jwks is not None:
                key: Any = self._jwks.get_signing_key_from_jwt(token).key
                algorithm = "RS256"
            else:
                assert settings.dev_secret is not None
                key, algorithm = settings.dev_secret.get_secret_value(), "HS256"
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                issuer=settings.issuer,
                leeway=settings.leeway_s,
                options={"require": ["exp", "iss", "sub"], "verify_aud": False},
            )
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthUnavailableError(str(exc)) from exc
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(str(exc)) from exc

        if settings.audience is not None:
            aud = claims.get("aud", [])
            audiences = [aud] if isinstance(aud, str) else list(aud)
            if settings.audience not in [*audiences, claims.get("client_id")]:
                raise InvalidTokenError("token is for another audience")
        # Cognito ID tokens also verify; they're meant for the client, not for APIs.
        if claims.get("token_use", "access") != "access":
            raise InvalidTokenError("not an access token")
        user_id = claims["sub"]
        try:
            user_prefix(user_id)  # it becomes an object-key prefix: same rules
        except ValueError as exc:
            raise InvalidTokenError("unsupported subject") from exc
        return CurrentUser(user_id)


def issue_dev_token(settings: AuthSettings, user_id: str, *, ttl_s: int = 3600) -> str:
    """An access token for local dev (`make token`). Needs JWT_DEV_SECRET."""
    if settings.dev_secret is None:
        raise RuntimeError("dev tokens need JWT_DEV_SECRET (local dev only)")
    user_prefix(user_id)
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": settings.issuer,
        "sub": user_id,
        "iat": now,
        "exp": now + ttl_s,
        "token_use": "access",
    }
    if settings.audience:
        claims["aud"] = settings.audience
    return jwt.encode(claims, settings.dev_secret.get_secret_value(), algorithm="HS256")


@lru_cache
def get_token_verifier() -> TokenVerifier:
    return TokenVerifier(AuthSettings())


_bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> CurrentUser:
    """FastAPI dependency: the authenticated user, or 401."""
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verifier.verify(credentials.credentials)
    except InvalidTokenError as exc:
        # The reason stays out of the response; it only helps someone forging tokens.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc
    except AuthUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "auth unavailable") from exc


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
