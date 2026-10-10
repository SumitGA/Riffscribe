from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from api import account as account_module
from api.deps import get_api_settings
from api.main import app
from tabscribe_platform.db import Job, PushToken, User
from tabscribe_platform.storage import ObjectStore, job_key
from testsupport.api import LIMITS, auth

pytestmark = pytest.mark.integration


def make_job(api: TestClient, user: str) -> str:
    body = {"instrument": "guitar", "content_type": "audio/mp4", "size_bytes": 1000}
    return str(api.post("/jobs", json=body, headers=auth(user)).json()["job"]["id"])


def jobs_of(db: Engine, user: str) -> int:
    with Session(db) as session:
        return session.scalar(select(func.count()).where(Job.user_id == user)) or 0


def tokens_of(db: Engine, user: str) -> int:
    with Session(db) as session:
        return session.scalar(select(func.count()).where(PushToken.user_id == user)) or 0


def test_deleting_an_account_removes_everything_and_is_safe_to_repeat(
    api: TestClient, alice: str, db: Engine, object_store: ObjectStore, tmp_path: Path
) -> None:
    job_id = make_job(api, alice)
    other_job = make_job(api, f"{alice}-bob")
    api.put(
        "/me/push-tokens",
        json={"token": "ExponentPushToken[x]", "platform": "android"},
        headers=auth(alice),
    )
    (tmp_path / "f").write_text("score")
    object_store.upload_file(tmp_path / "f", job_key(alice, job_id, "notation", "score.musicxml"))

    assert api.delete("/me", headers=auth(alice)).status_code == 204
    with Session(db) as session:
        assert session.get(User, alice) is None
    assert jobs_of(db, alice) == 0 and tokens_of(db, alice) == 0
    assert object_store.list_keys(f"users/{alice}/") == []
    assert jobs_of(db, f"{alice}-bob") == 1 and other_job  # nobody else's data
    assert api.delete("/me", headers=auth(alice)).status_code == 204  # again: nothing left


def test_the_clerk_sign_in_is_deleted_too_and_a_failure_can_be_retried(
    api: TestClient, alice: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.dependency_overrides[get_api_settings] = lambda: LIMITS.model_copy(
        update={"clerk_secret_key": SecretStr("sk_test_x")}
    )
    calls: list[tuple[str, str]] = []

    def failing(user_id: str, key: str) -> None:
        calls.append((user_id, key))
        raise OSError("clerk unreachable")

    monkeypatch.setattr(account_module, "delete_clerk_user", failing)
    first = api.delete("/me", headers=auth(alice))
    assert first.status_code == 502 and "try again" in first.json()["detail"]

    monkeypatch.setattr(account_module, "delete_clerk_user", lambda u, k: calls.append((u, k)))
    assert api.delete("/me", headers=auth(alice)).status_code == 204
    assert calls == [(alice, "sk_test_x"), (alice, "sk_test_x")]
