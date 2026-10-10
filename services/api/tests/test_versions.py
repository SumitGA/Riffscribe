import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tabscribe_platform.db import Job, JobStatus, ScoreVersion, User, VersionStatus
from tabscribe_platform.jobqueue import RENDER, QueueName, RedisJobQueue
from tabscribe_platform.storage import job_key
from testsupport.api import auth

pytestmark = pytest.mark.integration

DELETE = {"op": "delete", "note": {"onset_beats": "0", "pitch": 64}}


def finished_job(db: Engine, user: str) -> uuid.UUID:
    """A succeeded job with the pipeline's version 0."""
    job_id = uuid.uuid4()
    with Session(db) as session:
        if session.get(User, user) is None:
            session.add(User(id=user))
            session.flush()
        session.add(
            Job(
                id=job_id,
                user_id=user,
                status=JobStatus.SUCCEEDED,
                config={"instrument": "guitar"},
                source_key=job_key(user, str(job_id), "source", "upload.m4a"),
                source_content_type="audio/mp4",
                source_size_bytes=1000,
            )
        )
        session.flush()
        session.add(
            ScoreVersion(
                job_id=job_id,
                user_id=user,
                version=0,
                musicxml_key=job_key(user, str(job_id), "notation", "score.musicxml"),
            )
        )
        session.commit()
    return job_id


def set_status(db: Engine, job_id: uuid.UUID, number: int, status: VersionStatus) -> None:
    with Session(db) as session:
        version = session.scalars(
            select(ScoreVersion).where(
                ScoreVersion.job_id == job_id, ScoreVersion.version == number
            )
        ).one()
        version.status = status
        if status is VersionStatus.READY:
            version.musicxml_key = f"users/x/jobs/{job_id}/versions/{number}/score.musicxml"
        session.commit()


def test_saving_edits_queues_a_pending_version(
    api: TestClient, alice: str, db: Engine, job_queue: RedisJobQueue
) -> None:
    job_id = finished_job(db, alice)
    response = api.post(
        f"/jobs/{job_id}/versions", json={"base_version": 0, "edits": [DELETE]}, headers=auth(alice)
    )

    assert response.status_code == 202
    assert response.json() | {"created_at": None} == {
        "version": 1, "status": "pending", "base_version": 0, "error_message": None,
        "created_at": None, "outputs": None,
    }  # fmt: skip
    delivery = job_queue.receive(QueueName.CPU, "test", wait_s=0.1)
    assert delivery is not None
    assert (delivery.message.stage, delivery.message.version) == (RENDER, 1)
    with Session(db) as session:
        saved = session.scalars(
            select(ScoreVersion).where(ScoreVersion.version == 1, ScoreVersion.job_id == job_id)
        ).one()
        assert saved.edits == {"edits": [DELETE], "saved_on": 0}


def test_a_save_on_an_old_version_or_during_a_save_is_a_conflict(
    api: TestClient, alice: str, db: Engine
) -> None:
    job_id = finished_job(db, alice)
    url, headers = f"/jobs/{job_id}/versions", auth(alice)
    assert api.post(url, json={"base_version": 0, "edits": []}, headers=headers).status_code == 202

    still_saving = api.post(url, json={"base_version": 1, "edits": []}, headers=headers)
    assert (still_saving.status_code, still_saving.json()["detail"]) == (
        409, "the last changes are still being saved",
    )  # fmt: skip
    set_status(db, job_id, 1, VersionStatus.READY)
    stale = api.post(url, json={"base_version": 0, "edits": []}, headers=headers)
    assert (stale.status_code, stale.json()["detail"]) == (409, "version 1 is newer than your copy")
    assert api.post(url, json={"base_version": 1, "edits": []}, headers=headers).status_code == 202


def test_restoring_starts_a_new_version_from_an_old_one(
    api: TestClient, alice: str, db: Engine
) -> None:
    job_id = finished_job(db, alice)
    url, headers = f"/jobs/{job_id}/versions", auth(alice)
    api.post(url, json={"base_version": 0, "edits": [DELETE]}, headers=headers)
    set_status(db, job_id, 1, VersionStatus.READY)

    restored = api.post(
        url, json={"base_version": 1, "edits": [], "from_version": 0}, headers=headers
    )
    assert restored.status_code == 202
    assert (restored.json()["version"], restored.json()["base_version"]) == (2, 0)
    missing = api.post(
        url, json={"base_version": 1, "edits": [], "from_version": 7}, headers=headers
    )
    assert missing.status_code == 409  # version 2 is pending now; checked before the source


def test_versions_are_private_and_validated(api: TestClient, alice: str, db: Engine) -> None:
    job_id = finished_job(db, alice)
    url = f"/jobs/{job_id}/versions"
    body = {"base_version": 0, "edits": [DELETE]}

    assert api.post(url, json=body, headers=auth(f"{alice}-mallory")).status_code == 404
    assert api.get(url, headers=auth(f"{alice}-mallory")).status_code == 404
    unknown = {"base_version": 0, "edits": [{"op": "transpose"}]}
    assert api.post(url, json=unknown, headers=auth(alice)).status_code == 422
    assert (
        api.post(
            url, json={"base_version": 0, "edits": [DELETE] * 501}, headers=auth(alice)
        ).status_code
        == 422
    )


def test_listing_and_reading_versions(api: TestClient, alice: str, db: Engine) -> None:
    job_id = finished_job(db, alice)
    api.post(f"/jobs/{job_id}/versions", json={"base_version": 0, "edits": []}, headers=auth(alice))

    listed = api.get(f"/jobs/{job_id}/versions", headers=auth(alice)).json()["versions"]
    assert [(v["version"], v["status"]) for v in listed] == [(1, "pending"), (0, "ready")]
    original = api.get(f"/jobs/{job_id}/versions/0", headers=auth(alice)).json()
    assert "/notation/score.musicxml" in original["outputs"]["musicxml"]["url"]
    assert api.get(f"/jobs/{job_id}/versions/1", headers=auth(alice)).json()["outputs"] is None
    # The job itself still serves the latest *ready* version.
    assert api.get(f"/jobs/{job_id}", headers=auth(alice)).json()["outputs"]["version"] == 0
