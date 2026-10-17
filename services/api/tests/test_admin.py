import urllib.request
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from api import admin
from api.admin import Account, get_accounts_source
from api.auth import AuthSettings, get_auth_settings
from api.deps import get_api_settings
from api.main import app
from tabscribe_platform.db import Job, JobStatus, PushToken, StageRun, StageStatus, User
from testsupport.api import LIMITS, auth

pytestmark = pytest.mark.integration

ADMIN = "user_admin"
NOW = datetime.now(UTC)


@pytest.fixture
def as_admin(api: TestClient) -> Iterator[TestClient]:
    app.dependency_overrides[get_api_settings] = lambda: LIMITS.model_copy(
        update={"admin_user_ids": f" {ADMIN}, user_other_admin "}
    )
    yield api


def accounts(*items: Account) -> None:
    app.dependency_overrides[get_accounts_source] = lambda: lambda: list(items)


def account(user_id: str, days_ago: float, active_days_ago: float | None = None) -> Account:
    last = NOW - timedelta(days=active_days_ago) if active_days_ago is not None else None
    return Account(
        user_id, f"{user_id}@example.com", NOW - timedelta(days=days_ago), last, "google"
    )


def add_job(
    db: Engine,
    user_id: str,
    days_ago: float,
    status: JobStatus = JobStatus.SUCCEEDED,
    *,
    submitted: bool = True,
    error_code: str | None = None,
) -> uuid.UUID:
    created = NOW - timedelta(days=days_ago)
    with Session(db) as session:
        if session.get(User, user_id) is None:
            session.add(User(id=user_id, terms_version="2026-10-11"))
            session.flush()
        job = Job(
            user_id=user_id,
            status=status,
            config={"instrument": "guitar"},
            source_key=f"users/{user_id}/jobs/x/source/audio",
            source_content_type="audio/mp4",
            source_size_bytes=10,
            created_at=created,
            submitted_at=created if submitted else None,
            finished_at=created + timedelta(seconds=40) if submitted else None,
            error_code=error_code,
        )
        session.add(job)
        session.commit()
        return job.id


def test_only_listed_admins_get_in(as_admin: TestClient) -> None:
    accounts()
    assert as_admin.get("/admin/api/overview").status_code == 401
    refused = as_admin.get("/admin/api/overview", headers=auth("user_mallory"))
    assert refused.status_code == 403
    assert "user_mallory" in refused.json()["detail"]  # how the operator finds the ID to add
    for path in ("overview", "retention", "users", "users/x/jobs"):
        assert as_admin.get(f"/admin/api/{path}", headers=auth(ADMIN)).status_code == 200
    assert as_admin.get("/admin/api/users", headers=auth("user_other_admin")).status_code == 200


def test_nobody_is_an_admin_by_default(api: TestClient) -> None:
    assert api.get("/admin/api/users", headers=auth(ADMIN)).status_code == 403


def test_the_admin_routes_are_not_in_the_apps_api_document(api: TestClient) -> None:
    assert not [p for p in api.get("/openapi.json").json()["paths"] if p.startswith("/admin")]


@pytest.mark.parametrize(
    ("issuer", "key"),
    [
        ("https://clerk.sumitgautam.tech", "pk_live_Y2xlcmsuc3VtaXRnYXV0YW0udGVjaCQ"),
        (
            "https://civil-frog-613.clerk.accounts.dev",
            "pk_test_Y2l2aWwtZnJvZy02MTMuY2xlcmsuYWNjb3VudHMuZGV2JA==",
        ),
    ],
)
def test_the_page_gets_clerks_publishable_key_from_the_issuer(
    api: TestClient, issuer: str, key: str
) -> None:
    settings = AuthSettings(issuer=issuer, jwks_url=f"{issuer}/.well-known/jwks.json")
    app.dependency_overrides[get_auth_settings] = lambda: settings
    config = api.get("/admin/api/config").json()  # no sign-in needed: the sign-in screen uses it
    assert config["publishable_key"].rstrip("=") == key.rstrip("=")
    host = issuer.removeprefix("https://")
    assert config["clerk_js_url"].startswith(f"https://{host}/npm/@clerk/clerk-js@")


def test_overview_counts_accounts_activity_and_transcriptions(
    as_admin: TestClient, db: Engine
) -> None:
    accounts(account("user_a", 20, 0.5), account("user_b", 3, 5), account("user_c", 1))
    add_job(db, "user_a", 10)
    add_job(db, "user_a", 2, JobStatus.FAILED, error_code="bad_audio")
    add_job(db, "user_b", 1)
    add_job(db, "user_b", 1, JobStatus.PENDING_UPLOAD, submitted=False)  # never uploaded
    with Session(db) as session:
        session.add(PushToken(token="ExponentPushToken[a]", user_id="user_a", platform="android"))
        for job_id, seconds in ((add_job(db, "user_c", 0), 30.0), (add_job(db, "user_c", 0), 50.0)):
            session.add(
                StageRun(
                    job_id=job_id,
                    stage="transcribe",
                    status=StageStatus.SUCCEEDED,
                    duration_s=seconds,
                    finished_at=NOW,
                )
            )
        session.commit()

    body = as_admin.get("/admin/api/overview?days=30", headers=auth(ADMIN)).json()
    assert (body["accounts"], body["accounts_from_clerk"]) == (3, True)
    assert (body["active_1d"], body["active_7d"], body["active_30d"]) == (1, 2, 2)
    assert (body["users_started"], body["users_transcribed"]) == (3, 3)
    assert (body["transcriptions"], body["transcriptions_7d"]) == (5, 4)
    assert (body["failed"], body["failed_7d"]) == (1, 1)
    assert body["devices_with_notifications"] == 1
    assert len(body["days"]) == 30
    assert sum(d["signups"] for d in body["days"]) == 3
    assert sum(d["transcriptions"] for d in body["days"]) == 5
    assert body["stages"] == [{"stage": "transcribe", "runs": 2, "median_s": 40.0, "p95_s": 49.0}]
    assert body["errors"] == [{"code": "bad_audio", "count": 1}]
    assert {(q["queue"], q["priority"]) for q in body["queues"]} >= {("ml", "normal")}


def test_without_clerk_the_databases_users_are_counted(as_admin: TestClient, db: Engine) -> None:
    app.dependency_overrides[get_accounts_source] = lambda: None
    add_job(db, "user_a", 1)
    body = as_admin.get("/admin/api/overview", headers=auth(ADMIN)).json()
    assert (body["accounts"], body["accounts_from_clerk"], body["active_7d"]) == (1, False, None)


def test_clerk_down_is_a_bad_gateway(as_admin: TestClient) -> None:
    def down() -> list[Account]:
        raise OSError("unreachable")

    app.dependency_overrides[get_accounts_source] = lambda: down
    assert as_admin.get("/admin/api/users", headers=auth(ADMIN)).status_code == 502


def test_retention_counts_who_transcribed_in_each_week_after_signing_up(
    as_admin: TestClient, db: Engine
) -> None:
    monday = NOW.date() - timedelta(days=NOW.weekday())
    joined = datetime.combine(monday - timedelta(weeks=2), datetime.min.time(), UTC)
    early = [
        Account(f"user_{i}", None, joined + timedelta(hours=1), None, "email") for i in range(3)
    ]
    accounts(*early, account("user_new", 0))
    days_since = (NOW - joined).total_seconds() / 86400
    add_job(db, "user_0", days_since - 0.1)  # week 0
    add_job(db, "user_0", days_since - 8)  # week 1
    add_job(db, "user_1", days_since - 15)  # week 2 (this week)

    cohorts = as_admin.get("/admin/api/retention?weeks=3", headers=auth(ADMIN)).json()["cohorts"]
    assert [c["size"] for c in cohorts] == [3, 0, 1]
    assert cohorts[0]["transcribed"] == [1, 1, 1]
    assert cohorts[1]["transcribed"] == [0, 0]
    assert cohorts[2]["transcribed"] == [0]


def test_users_and_their_jobs(as_admin: TestClient, db: Engine) -> None:
    accounts(account("user_a", 5, 1), account("user_b", 1))
    add_job(db, "user_a", 4)
    failed = add_job(db, "user_a", 2, JobStatus.FAILED, error_code="bad_audio")

    users = as_admin.get("/admin/api/users", headers=auth(ADMIN)).json()["users"]
    assert [u["id"] for u in users] == ["user_b", "user_a"]  # newest first
    a = users[1]
    assert (a["email"], a["transcriptions"], a["failed"], a["terms_accepted"]) == (
        "user_a@example.com",
        2,
        1,
        True,
    )
    assert (users[0]["transcriptions"], users[0]["terms_accepted"]) == (0, False)

    jobs = as_admin.get("/admin/api/users/user_a/jobs", headers=auth(ADMIN)).json()["jobs"]
    assert jobs[0]["id"] == str(failed)  # newest first
    assert (jobs[0]["status"], jobs[0]["error_code"], jobs[0]["instrument"]) == (
        "failed",
        "bad_audio",
        "guitar",
    )
    assert jobs[0]["seconds"] == 40.0


def test_clerk_users_are_read_page_by_page(monkeypatch: pytest.MonkeyPatch) -> None:
    def user(i: int) -> dict[str, object]:
        return {
            "id": f"user_{i}",
            "created_at": 1_700_000_000_000,
            "last_active_at": None,
            "primary_email_address_id": "e1",
            "email_addresses": [
                {"id": "e0", "email_address": "old@x"},
                {"id": "e1", "email_address": f"u{i}@x"},
            ],
            "external_accounts": [{"provider": "oauth_google"}] if i % 2 else [],
        }

    pages = [[user(i) for i in range(2)], [user(2)]]
    offsets: list[str] = []

    class Response:
        def __init__(self, body: list[dict[str, object]]) -> None:
            self.body = body

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: object) -> None: ...

    def urlopen(request: urllib.request.Request, timeout: float) -> Response:
        url = request.full_url
        offsets.append(url.split("offset=")[1].split("&")[0])
        return Response(pages[len(offsets) - 1])

    monkeypatch.setattr(admin, "CLERK_PAGE_SIZE", 2)
    monkeypatch.setattr("api.admin.urllib.request.urlopen", urlopen)
    monkeypatch.setattr("api.admin.json.load", lambda r: r.body)
    found = admin.clerk_accounts("sk_test_x")()
    assert offsets == ["0", "2"]
    assert [(a.id, a.email, a.method) for a in found] == [
        ("user_0", "u0@x", "email"),
        ("user_1", "u1@x", "google"),
        ("user_2", "u2@x", "email"),
    ]
