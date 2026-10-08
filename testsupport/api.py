"""Shared by the API's integration tests: the API wired to the `make up` services with test
limits, a fresh user per test, and dev tokens."""

from collections.abc import Iterator
from typing import Any

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from api.auth import AuthSettings, TokenVerifier, get_token_verifier, issue_dev_token
from api.deps import (
    get_api_settings,
    get_job_queue,
    get_limiter,
    get_object_store,
    get_redis,
    get_session_factory,
)
from api.limits import Limiter
from api.main import app
from api.settings import ApiSettings
from tabscribe_platform.db import make_session_factory
from tabscribe_platform.jobqueue import RedisJobQueue
from tabscribe_platform.storage import ObjectStore

AUTH = AuthSettings(issuer="https://test", dev_secret="test-secret-that-is-at-least-32-chars")
LIMITS = ApiSettings(max_upload_bytes=1000, free_jobs_per_month=2, job_creates_per_minute=5)
NEW_JOB = {"instrument": "guitar", "content_type": "audio/mp4", "size_bytes": 10}


@pytest.fixture
def api(
    db: Engine,
    object_store: ObjectStore,
    job_queue: RedisJobQueue,
    redis_client: "redis.Redis",
    key_prefix: str,
) -> Iterator[TestClient]:
    # Limiter keys share the queue's prefix, so the job_queue fixture deletes them too.
    overrides: dict[Any, Any] = {
        get_session_factory: lambda: make_session_factory(db),
        get_object_store: lambda: object_store,
        get_job_queue: lambda: job_queue,
        get_redis: lambda: redis_client,
        get_limiter: lambda: Limiter(redis_client, prefix=f"{key_prefix}:limits"),
        get_api_settings: lambda: LIMITS,
        get_token_verifier: lambda: TokenVerifier(AUTH),
    }
    app.dependency_overrides.update(overrides)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def alice(s3_user: str) -> str:
    return s3_user  # a fresh user whose objects are deleted afterwards


def auth(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_dev_token(AUTH, user_id)}"}
