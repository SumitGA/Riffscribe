import urllib.request
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
import redis
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import Engine
from sqlalchemy.orm import Session

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
from tabscribe_platform.db import Job, JobStatus, ScoreVersion, make_session_factory
from tabscribe_platform.jobqueue import JobQueue, QueueName, RedisJobQueue
from tabscribe_platform.storage import ObjectStore, job_key

pytestmark = pytest.mark.integration

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


def create(api: TestClient, user_id: str, **body: Any) -> dict[str, Any]:
    response = api.post("/jobs", json={**NEW_JOB, **body}, headers=auth(user_id))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def upload(created: dict[str, Any], data: bytes = b"fake audio") -> None:
    up = created["upload"]
    request = urllib.request.Request(up["url"], data=data, headers=up["headers"], method="PUT")
    urllib.request.urlopen(request, timeout=10).close()


def test_create_upload_submit_poll(api: TestClient, alice: str, job_queue: JobQueue) -> None:
    created = create(api, alice, tuning="drop_d", capo=2)
    job = created["job"]
    job_id = job["id"]
    assert job["status"] == "pending_upload"
    assert job["options"] == {"instrument": "guitar", "tuning": "drop_d", "capo": 2}
    assert created["upload"]["method"] == "PUT"
    assert f"/users/{alice}/jobs/{job_id}/source/upload.m4a" in created["upload"]["url"]

    response = api.post(f"/jobs/{job_id}/submit", headers=auth(alice))
    assert response.status_code == 409  # nothing uploaded yet

    upload(created)
    response = api.post(f"/jobs/{job_id}/submit", headers=auth(alice))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"

    delivery = job_queue.receive(QueueName.CPU, "test", wait_s=0.1)
    assert delivery is not None
    assert (str(delivery.message.job_id), delivery.message.stage) == (job_id, "normalize")
    assert delivery.message.user_id == alice

    # Submitting again is harmless: no second message, no second quota hit.
    assert api.post(f"/jobs/{job_id}/submit", headers=auth(alice)).json()["status"] == "queued"
    job_queue.ack(delivery)
    assert job_queue.receive(QueueName.CPU, "test", wait_s=0.05) is None
    assert api.get("/me", headers=auth(alice)).json() == {
        "user_id": alice,
        "jobs_this_month": 1,
        "jobs_per_month": LIMITS.free_jobs_per_month,
    }

    polled = api.get(f"/jobs/{job_id}", headers=auth(alice)).json()
    assert polled["status"] == "queued"
    assert polled["submitted_at"] is not None
    assert polled["outputs"] is None


def test_jobs_are_private(api: TestClient, alice: str) -> None:
    job_id = create(api, alice)["job"]["id"]
    assert api.get(f"/jobs/{job_id}", headers=auth("mallory")).status_code == 404
    assert api.post(f"/jobs/{job_id}/submit", headers=auth("mallory")).status_code == 404
    assert api.get("/jobs", headers=auth("mallory")).json()["jobs"] == []
    assert api.get(f"/jobs/{uuid.uuid4()}", headers=auth(alice)).status_code == 404


def test_needs_a_token(api: TestClient) -> None:
    assert api.post("/jobs", json=NEW_JOB).status_code == 401
    assert api.get("/jobs").status_code == 401


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"content_type": "video/mp4"}, 415),
        ({"size_bytes": LIMITS.max_upload_bytes + 1}, 413),
        ({"instrument": "drums"}, 422),
        ({"capo": 13}, 422),
        ({"separation": True}, 422),  # not offered yet
    ],
)
def test_create_rejects(api: TestClient, alice: str, body: dict[str, Any], code: int) -> None:
    response = api.post("/jobs", json={**NEW_JOB, **body}, headers=auth(alice))
    assert response.status_code == code, response.text


def test_upload_larger_than_the_limit_fails_the_job(api: TestClient, alice: str) -> None:
    created = create(api, alice)
    upload(created, b"x" * (LIMITS.max_upload_bytes + 1))
    job_id = created["job"]["id"]
    assert api.post(f"/jobs/{job_id}/submit", headers=auth(alice)).status_code == 413
    job = api.get(f"/jobs/{job_id}", headers=auth(alice)).json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "invalid_input"


def test_monthly_quota(api: TestClient, alice: str) -> None:
    for i in range(LIMITS.free_jobs_per_month + 1):
        created = create(api, alice)
        upload(created)
        response = api.post(f"/jobs/{created['job']['id']}/submit", headers=auth(alice))
        expected = 200 if i < LIMITS.free_jobs_per_month else 429
        assert response.status_code == expected, response.text
    # The refused job stays submittable for next month (or a paid plan).
    job = api.get(f"/jobs/{created['job']['id']}", headers=auth(alice)).json()
    assert job["status"] == "pending_upload"


def test_create_rate_limit(api: TestClient, alice: str) -> None:
    codes = [
        api.post("/jobs", json=NEW_JOB, headers=auth(alice)).status_code
        for _ in range(LIMITS.job_creates_per_minute + 1)
    ]
    assert codes == [201] * LIMITS.job_creates_per_minute + [429]


class BrokenQueue(RedisJobQueue):
    def enqueue(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError("queue down")


def test_failed_enqueue_is_undone(
    api: TestClient, alice: str, redis_client: "redis.Redis", key_prefix: str
) -> None:
    app.dependency_overrides[get_job_queue] = lambda: BrokenQueue(
        redis_client, visibility_timeout_s=1, prefix=key_prefix
    )
    created = create(api, alice)
    upload(created)
    job_id = created["job"]["id"]
    assert api.post(f"/jobs/{job_id}/submit", headers=auth(alice)).status_code == 503
    assert api.get(f"/jobs/{job_id}", headers=auth(alice)).json()["status"] == "pending_upload"
    assert api.get("/me", headers=auth(alice)).json()["jobs_this_month"] == 0


def test_list_jobs_pages_newest_first(api: TestClient, alice: str) -> None:
    ids = [create(api, alice)["job"]["id"] for _ in range(3)]
    first = api.get("/jobs", params={"limit": 2}, headers=auth(alice)).json()
    assert [j["id"] for j in first["jobs"]] == ids[::-1][:2]
    assert first["next_cursor"] is not None
    second = api.get(
        "/jobs", params={"limit": 2, "cursor": first["next_cursor"]}, headers=auth(alice)
    ).json()
    assert [j["id"] for j in second["jobs"]] == [ids[0]]
    assert second["next_cursor"] is None
    bad = api.get("/jobs", params={"cursor": "nonsense"}, headers=auth(alice))
    assert bad.status_code == 422


def test_succeeded_job_has_download_links(api: TestClient, alice: str, db: Engine) -> None:
    job_id = uuid.UUID(create(api, alice)["job"]["id"])
    with Session(db) as session:
        session.get_one(Job, job_id).status = JobStatus.SUCCEEDED
        session.add(
            ScoreVersion(
                job_id=job_id,
                user_id=alice,
                version=0,
                musicxml_key=job_key(alice, str(job_id), "notation", "score.musicxml"),
                midi_key=job_key(alice, str(job_id), "transcribe", "notes.mid"),
            )
        )
        session.commit()
    outputs = api.get(f"/jobs/{job_id}", headers=auth(alice)).json()["outputs"]
    assert outputs["version"] == 0
    assert "/notation/score.musicxml" in outputs["musicxml"]["url"]
    assert outputs["midi"]["method"] == "GET"
    assert outputs["tab_musicxml"] is None


def test_readyz(api: TestClient) -> None:
    assert api.get("/readyz").json() == {"status": "ok"}


def test_metrics(api: TestClient, alice: str) -> None:
    create(api, alice)
    created = create(api, alice)
    upload(created)
    api.post(f"/jobs/{created['job']['id']}/submit", headers=auth(alice))

    text = api.get("/metrics").text
    assert 'tabscribe_queue_messages{priority="normal",queue="cpu",state="ready"} 1.0' in text
    assert "tabscribe_queue_dead_letters 0.0" in text
    # Latency is recorded per route template, not per job ID.
    assert 'route="/jobs/{job_id}/submit"' in text
    assert 'tabscribe_http_request_duration_seconds_count{method="POST",route="/jobs"' in text
    assert 'route="/metrics"' not in text


def test_submit_starts_the_jobs_trace(
    api: TestClient, alice: str, job_queue: JobQueue, spans: InMemorySpanExporter
) -> None:
    created = create(api, alice)
    upload(created)
    api.post(f"/jobs/{created['job']['id']}/submit", headers=auth(alice))
    delivery = job_queue.receive(QueueName.CPU, "test", wait_s=0.1)
    assert delivery is not None

    [submit] = [s for s in spans.get_finished_spans() if s.name.endswith("/submit")]
    assert submit.attributes is not None
    assert submit.attributes["job.id"] == created["job"]["id"]
    trace_id = format(submit.context.trace_id, "032x")
    assert delivery.message.trace["traceparent"].split("-")[1] == trace_id
