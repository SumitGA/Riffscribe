import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tabscribe_platform.db import Job, JobStatus, PushToken, User, make_session_factory
from worker.notify import ExpoPushNotifier

pytestmark = pytest.mark.integration


class FakeExpo:
    """Records what would be sent; answers like Expo, optionally losing some devices."""

    def __init__(self, gone: frozenset[str] = frozenset(), fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self._gone = gone
        self._fail = fail

    def __call__(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self._fail:
            raise ConnectionError("exp.host unreachable")
        self.sent.extend(messages)
        return {
            "data": [
                {"status": "error", "details": {"error": "DeviceNotRegistered"}}
                if m["to"] in self._gone
                else {"status": "ok", "id": "ticket"}
                for m in messages
            ]
        }


def add_job(db: Engine, user_id: str, tokens: list[str], name: str | None) -> uuid.UUID:
    job_id = uuid.uuid4()
    with Session(db) as session:
        session.add(User(id=user_id))
        session.flush()
        session.add(
            Job(
                id=job_id,
                user_id=user_id,
                name=name,
                status=JobStatus.SUCCEEDED,
                config={"instrument": "guitar"},
                source_key=f"users/{user_id}/jobs/{job_id}/source/upload.m4a",
                source_content_type="audio/mp4",
                source_size_bytes=10,
            )
        )
        session.add_all(PushToken(token=t, user_id=user_id, platform="android") for t in tokens)
        session.commit()
    return job_id


def test_notifies_every_device_and_forgets_lost_ones(db: Engine) -> None:
    phone, tablet = "ExponentPushToken[phone]", "ExponentPushToken[tablet]"
    job_id = add_job(db, "alice", [phone, tablet], "Blues riff in A")
    expo = FakeExpo(gone=frozenset({tablet}))

    ExpoPushNotifier(make_session_factory(db), expo).job_finished(
        "alice", job_id, JobStatus.SUCCEEDED
    )

    assert sorted(m["to"] for m in expo.sent) == [phone, tablet]
    assert expo.sent[0]["title"] == "Your score is ready"
    assert "“Blues riff in A”" in expo.sent[0]["body"]
    assert expo.sent[0]["data"] == {"jobId": str(job_id)}
    with Session(db) as session:
        assert session.scalars(select(PushToken.token)).all() == [phone]


def test_failure_message_names_the_take(db: Engine) -> None:
    job_id = add_job(db, "alice", ["ExponentPushToken[phone]"], None)
    expo = FakeExpo()
    ExpoPushNotifier(make_session_factory(db), expo).job_finished("alice", job_id, JobStatus.FAILED)
    assert expo.sent[0]["title"] == "Couldn't transcribe “Guitar take”"


def test_nothing_to_send_without_devices(db: Engine) -> None:
    job_id = add_job(db, "alice", [], "Riff")
    expo = FakeExpo()
    ExpoPushNotifier(make_session_factory(db), expo).job_finished(
        "alice", job_id, JobStatus.SUCCEEDED
    )
    assert expo.sent == []


def test_only_the_owners_devices_hear_about_a_job(db: Engine) -> None:
    job_id = add_job(db, "alice", [], "Riff")
    add_job(db, "mallory", ["ExponentPushToken[mallory]"], None)
    expo = FakeExpo()
    # A message naming alice's job but the wrong user finds no job: nothing is sent.
    ExpoPushNotifier(make_session_factory(db), expo).job_finished(
        "mallory", job_id, JobStatus.SUCCEEDED
    )
    assert expo.sent == []


def test_send_errors_never_reach_the_worker(db: Engine) -> None:
    job_id = add_job(db, "alice", ["ExponentPushToken[phone]"], "Riff")
    ExpoPushNotifier(make_session_factory(db), FakeExpo(fail=True)).job_finished(
        "alice", job_id, JobStatus.SUCCEEDED
    )  # logs, doesn't raise
