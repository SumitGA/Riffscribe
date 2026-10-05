"""Redis and S3 fixtures shared by the platform, API and worker tests. They need `make up` running.

Each test gets its own key prefix, so tests never see each other's data and leave none behind.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
import redis
from botocore.exceptions import EndpointConnectionError

from tabscribe_platform.jobqueue import RedisJobQueue
from tabscribe_platform.settings import Settings
from tabscribe_platform.storage import ObjectStore
from testsupport.postgres import DEFAULT_TEST_DATABASE_URL

# The docker-compose services; CI uses the same ones.
DEFAULT_TEST_REDIS_URL = "redis://localhost:6379/15"
DEFAULT_TEST_S3_ENDPOINT_URL = "http://localhost:8333"
# The throwaway identity in infra/local/seaweedfs-s3.json.
DEV_S3_CREDENTIALS = {
    "AWS_ACCESS_KEY_ID": "dev-access-key",
    "AWS_SECRET_ACCESS_KEY": "dev-secret-key",
}


@pytest.fixture(scope="session")
def settings() -> Iterator[Settings]:
    with pytest.MonkeyPatch.context() as mp:
        for name, value in DEV_S3_CREDENTIALS.items():
            mp.setenv(name, os.environ.get(name, value))
        yield Settings(
            database_url=os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
            redis_url=os.environ.get("TEST_REDIS_URL", DEFAULT_TEST_REDIS_URL),
            s3_bucket=os.environ.get("TEST_S3_BUCKET", "tabscribe"),
            s3_endpoint_url=os.environ.get("TEST_S3_ENDPOINT_URL", DEFAULT_TEST_S3_ENDPOINT_URL),
            s3_region="us-east-1",
        )


@pytest.fixture(scope="session")
def redis_client(settings: Settings) -> Iterator["redis.Redis"]:
    client = redis.Redis.from_url(str(settings.redis_url), decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError as exc:
        pytest.fail(f"cannot reach Redis at {settings.redis_url}; run `make up` first ({exc})")
    yield client
    client.close()


@pytest.fixture
def key_prefix() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def job_queue(redis_client: "redis.Redis", key_prefix: str) -> Iterator[RedisJobQueue]:
    """A queue under its own prefix with a 0.2 s visibility timeout."""
    yield RedisJobQueue(redis_client, visibility_timeout_s=0.2, prefix=key_prefix)
    keys = list(redis_client.scan_iter(f"{key_prefix}:*"))
    if keys:
        redis_client.delete(*keys)


@pytest.fixture(scope="session")
def object_store(settings: Settings) -> ObjectStore:
    store = ObjectStore(settings)
    try:
        store.list_keys("users/nobody/")
    except EndpointConnectionError as exc:
        pytest.fail(f"cannot reach S3 at {settings.s3_endpoint_url}; run `make up` first ({exc})")
    return store


@pytest.fixture
def s3_user(object_store: ObjectStore) -> Iterator[str]:
    """A fresh user ID; everything stored under its prefix is deleted afterwards."""
    user_id = f"test-{uuid.uuid4().hex[:12]}"
    yield user_id
    object_store.delete_prefix(f"users/{user_id}/")
