"""Plan limits (ADR-0016): monthly jobs, clip length, upload size and queue priority per plan."""

import urllib.request
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tabscribe_platform.db import Job, Plan, User
from tabscribe_platform.jobqueue import JobQueue, Priority, QueueName
from testsupport.api import LIMITS, NEW_JOB, auth

pytestmark = pytest.mark.integration


def create(api: TestClient, user_id: str, **body: Any) -> dict[str, Any]:
    response = api.post("/jobs", json={**NEW_JOB, **body}, headers=auth(user_id))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def upload(created: dict[str, Any]) -> None:
    up = created["upload"]
    request = urllib.request.Request(up["url"], data=b"audio", headers=up["headers"], method="PUT")
    urllib.request.urlopen(request, timeout=10).close()


def give(db: Engine, user_id: str, plan: Plan) -> None:
    with Session(db) as session:
        session.add(User(id=user_id, plan=plan, plan_changed_by="admin_1"))
        session.commit()


def submit(api: TestClient, user_id: str, **body: Any) -> tuple[int, str]:
    created = create(api, user_id, **body)
    upload(created)
    job_id = created["job"]["id"]
    return api.post(f"/jobs/{job_id}/submit", headers=auth(user_id)).status_code, job_id


def stored_limit(db: Engine, job_id: str) -> int | None:
    with Session(db) as session:
        return session.scalar(select(Job.max_duration_s).where(Job.id == uuid.UUID(job_id)))


def test_free_jobs_get_the_free_limits(
    api: TestClient, db: Engine, alice: str, job_queue: JobQueue
) -> None:
    code, job_id = submit(api, alice)
    assert code == 200
    assert stored_limit(db, job_id) == LIMITS.free_max_clip_s
    delivery = job_queue.receive(QueueName.CPU, "test", wait_s=0.1)
    assert delivery is not None
    assert delivery.priority is Priority.NORMAL
    job_queue.ack(delivery)


def test_pro_has_its_own_limits(
    api: TestClient, db: Engine, alice: str, job_queue: JobQueue
) -> None:
    give(db, alice, Plan.PRO)
    me = api.get("/me", headers=auth(alice)).json()
    assert (me["plan"], me["plan_source"]) == ("pro", "admin")
    assert me["limits"] == {
        "jobs_per_month": LIMITS.pro_jobs_per_month,
        "max_clip_s": LIMITS.pro_max_clip_s,
        "max_upload_bytes": LIMITS.pro_max_upload_bytes,
        "priority": True,
    }
    assert me["jobs_per_month"] == LIMITS.pro_jobs_per_month  # what older app builds read

    # Bigger uploads than free allows, up to Pro's limit.
    body = {"size_bytes": LIMITS.max_upload_bytes + 1}
    assert api.post("/jobs", json={**NEW_JOB, **body}, headers=auth(alice)).status_code == 201
    body = {"size_bytes": LIMITS.pro_max_upload_bytes + 1}
    assert api.post("/jobs", json={**NEW_JOB, **body}, headers=auth(alice)).status_code == 413

    codes = [submit(api, alice)[0] for _ in range(LIMITS.pro_jobs_per_month + 1)]
    assert codes == [200] * LIMITS.pro_jobs_per_month + [429]

    delivery = job_queue.receive(QueueName.CPU, "test", wait_s=0.1)
    assert delivery is not None
    assert delivery.priority is Priority.HIGH  # ahead of free jobs
    assert stored_limit(db, str(delivery.message.job_id)) == LIMITS.pro_max_clip_s
    job_queue.ack(delivery)


def test_unlimited_has_no_monthly_limit(api: TestClient, db: Engine, alice: str) -> None:
    give(db, alice, Plan.UNLIMITED)
    me = api.get("/me", headers=auth(alice)).json()
    assert me["limits"]["jobs_per_month"] is None
    assert me["limits"]["max_clip_s"] == LIMITS.pro_max_clip_s
    assert me["jobs_per_month"] == LIMITS.free_jobs_per_month  # older builds show no count
    codes = [submit(api, alice)[0] for _ in range(LIMITS.pro_jobs_per_month + 1)]
    assert codes == [200] * (LIMITS.pro_jobs_per_month + 1)
