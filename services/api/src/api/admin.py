"""The admin section's API (ADR-0015): sign-ups, activity, retention and each user's jobs, and
each user's plan (free or unlimited), whose changes go to an audit log (admin_actions). The
page is `infra/site/admin.html`, served by Caddy at /admin; these routes sit under /admin/api so
one Cloudflare Access rule guards both.

Only the Clerk user IDs in ADMIN_USER_IDS get past `require_admin`; anyone else signed in gets
403 with their own ID, which is how the operator finds the ID to add. Accounts come from Clerk's
Backend API (who signed in, when, how, last active); usage comes from our database. The routes
are left out of the OpenAPI document: the app never calls them (TD-21).
"""

import base64
import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.account import CLERK_API, USER_AGENT
from api.auth import AuthSettings, CurrentUser, CurrentUserDep, get_auth_settings
from api.deps import ApiSettingsDep, QueueDep, SessionDep
from tabscribe_platform.db import (
    AdminAction,
    Job,
    JobStatus,
    Plan,
    PushToken,
    StageRun,
    StageStatus,
    User,
)

# Clerk's browser SDK, served by each instance's Frontend API (the page loads it from there):
# the client, and since clerk-js 6 its sign-in screens as a separate package, released with it.
CLERK_JS_VERSION = "6.38.0"
CLERK_UI_VERSION = "1.39.0"
CLERK_PAGE_SIZE = 500  # Clerk's maximum per request


def require_admin(user: CurrentUserDep, settings: ApiSettingsDep) -> CurrentUser:
    if user.id not in settings.admins:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"not an admin: add {user.id} to ADMIN_USER_IDS on the server to allow this account",
        )
    return user


logger = logging.getLogger(__name__)
AdminDep = Annotated[CurrentUser, Depends(require_admin)]

router = APIRouter(
    prefix="/admin/api", include_in_schema=False, dependencies=[Depends(require_admin)]
)
config_router = APIRouter(prefix="/admin/api", include_in_schema=False)


@dataclass(frozen=True)
class Account:
    """A Clerk user: no names; the email is shown to the admin only."""

    id: str
    email: str | None
    joined: datetime
    last_active: datetime | None
    method: str  # "google" or "email"


AccountsSource = Callable[[], list[Account]]


def clerk_accounts(secret_key: str) -> AccountsSource:
    def fetch() -> list[Account]:
        accounts: list[Account] = []
        while True:
            query = urllib.parse.urlencode(
                {"limit": CLERK_PAGE_SIZE, "offset": len(accounts), "order_by": "-created_at"}
            )
            request = urllib.request.Request(
                f"{CLERK_API}/users?{query}",
                headers={"Authorization": f"Bearer {secret_key}", "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                page: list[dict[str, Any]] = json.load(response)
            accounts += [_account(u) for u in page]
            if len(page) < CLERK_PAGE_SIZE:
                return accounts

    return fetch


def _account(user: dict[str, Any]) -> Account:
    primary = user.get("primary_email_address_id")
    emails = user.get("email_addresses") or []
    email = next((e["email_address"] for e in emails if e.get("id") == primary), None)
    google = any("google" in a.get("provider", "") for a in user.get("external_accounts") or [])
    last = user.get("last_active_at") or user.get("last_sign_in_at")
    return Account(
        id=user["id"],
        email=email,
        joined=_from_ms(user["created_at"]),
        last_active=_from_ms(last) if last else None,
        method="google" if google else "email",
    )


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


def get_accounts_source(settings: ApiSettingsDep) -> AccountsSource | None:
    """Clerk's accounts, or None without CLERK_SECRET_KEY (local runs): the database's users."""
    if settings.clerk_secret_key is None:
        return None
    return clerk_accounts(settings.clerk_secret_key.get_secret_value())


AccountsDep = Annotated[AccountsSource | None, Depends(get_accounts_source)]


def accounts_or_db(source: AccountsSource | None, session: Session) -> list[Account]:
    if source is not None:
        try:
            return source()
        except OSError as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Clerk can't be reached") from exc
    rows = session.execute(select(User.id, User.created_at)).all()
    return [Account(i, None, _utc(c), None, "unknown") for i, c in rows]


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# --- the page's configuration (no admin check: it's what the sign-in screen needs) ---


class AdminConfig(BaseModel):
    publishable_key: str | None  # None: no Clerk (local dev tokens), so no sign-in screen
    clerk_js_url: str | None
    clerk_ui_url: str | None


@config_router.get("/config")
def admin_config(
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> AdminConfig:
    """Clerk's publishable key, which the page needs before anyone signs in. It is public (the
    app ships it) and is the instance's Frontend API host, base64-encoded with a `$`, so it is
    derived from JWT_ISSUER instead of being configured twice."""
    if settings.jwks_url is None:
        return AdminConfig(publishable_key=None, clerk_js_url=None, clerk_ui_url=None)
    host = urllib.parse.urlparse(settings.issuer).netloc
    kind = "test" if host.endswith(".clerk.accounts.dev") else "live"
    key = f"pk_{kind}_" + base64.b64encode(f"{host}$".encode()).decode().rstrip("=")
    npm = f"https://{host}/npm"
    return AdminConfig(
        publishable_key=key,
        clerk_js_url=f"{npm}/@clerk/clerk-js@{CLERK_JS_VERSION}/dist/clerk.browser.js",
        clerk_ui_url=f"{npm}/@clerk/ui@{CLERK_UI_VERSION}/dist/ui.browser.js",
    )


# --- overview ---


class DayCount(BaseModel):
    day: date
    signups: int
    transcriptions: int
    failed: int


class StageTime(BaseModel):
    stage: str
    runs: int
    median_s: float
    p95_s: float


class ErrorCount(BaseModel):
    code: str
    count: int


class QueueRow(BaseModel):
    queue: str
    priority: str
    ready: int
    in_flight: int
    delayed: int


class Overview(BaseModel):
    accounts: int
    accounts_from_clerk: bool
    active_1d: int | None  # last active in Clerk (None without Clerk)
    active_7d: int | None
    active_30d: int | None
    users_started: int  # accepted the terms or uploaded (rows in our users table)
    users_transcribed: int
    transcriptions: int
    transcriptions_7d: int
    failed: int
    failed_7d: int
    devices_with_notifications: int
    days: list[DayCount]
    stages: list[StageTime]
    errors: list[ErrorCount]
    queues: list[QueueRow]
    dead_letters: int


@router.get("/overview")
def overview(
    session: SessionDep,
    accounts_source: AccountsDep,
    queue: QueueDep,
    days: Annotated[int, Query(ge=7, le=365)] = 30,
) -> Overview:
    now = datetime.now(UTC)
    accounts = accounts_or_db(accounts_source, session)
    from_clerk = accounts_source is not None

    def active(within: timedelta) -> int | None:
        if not from_clerk:
            return None
        return sum(1 for a in accounts if a.last_active and now - a.last_active <= within)

    submitted = Job.submitted_at.is_not(None)
    failed = Job.status == JobStatus.FAILED
    week_ago = now - timedelta(days=7)
    totals = session.execute(
        select(
            func.count(),
            func.count().filter(Job.created_at >= week_ago),
            func.count().filter(failed),
            func.count().filter(failed, Job.created_at >= week_ago),
            func.count(func.distinct(Job.user_id)),
        ).where(submitted)
    ).one()

    first_day = (now - timedelta(days=days - 1)).date()
    day = func.date_trunc("day", Job.created_at)
    per_day = {
        _utc(d).date(): (n, f)
        for d, n, f in session.execute(
            select(day, func.count(), func.count().filter(failed))
            .where(submitted, Job.created_at >= first_day)
            .group_by(day)
        ).all()
    }
    signups: dict[date, int] = {}
    for account in accounts:
        signups[account.joined.date()] = signups.get(account.joined.date(), 0) + 1
    series = []
    for offset in range(days):
        d = first_day + timedelta(days=offset)
        n, f = per_day.get(d, (0, 0))
        series.append(DayCount(day=d, signups=signups.get(d, 0), transcriptions=n, failed=f))

    month_ago = now - timedelta(days=30)
    stages = [
        StageTime(stage=s, runs=n, median_s=round(m, 2), p95_s=round(p, 2))
        for s, n, m, p in session.execute(
            select(
                StageRun.stage,
                func.count(),
                func.percentile_cont(0.5).within_group(StageRun.duration_s),
                func.percentile_cont(0.95).within_group(StageRun.duration_s),
            )
            .where(
                StageRun.status == StageStatus.SUCCEEDED,
                StageRun.duration_s.is_not(None),
                StageRun.finished_at >= month_ago,
            )
            .group_by(StageRun.stage)
        ).all()
    ]
    errors = [
        ErrorCount(code=code or "unknown", count=n)
        for code, n in session.execute(
            select(Job.error_code, func.count())
            .where(failed, Job.created_at >= month_ago)
            .group_by(Job.error_code)
            .order_by(func.count().desc())
        ).all()
    ]
    return Overview(
        accounts=len(accounts),
        accounts_from_clerk=from_clerk,
        active_1d=active(timedelta(days=1)),
        active_7d=active(timedelta(days=7)),
        active_30d=active(timedelta(days=30)),
        users_started=session.scalar(select(func.count()).select_from(User)) or 0,
        users_transcribed=totals[4],
        transcriptions=totals[0],
        transcriptions_7d=totals[1],
        failed=totals[2],
        failed_7d=totals[3],
        devices_with_notifications=session.scalar(select(func.count()).select_from(PushToken)) or 0,
        days=series,
        stages=sorted(stages, key=lambda s: _STAGE_ORDER.get(s.stage, 99)),
        errors=errors,
        queues=[
            QueueRow(
                queue=d.queue.value,
                priority=d.priority.name.lower(),
                ready=d.ready,
                in_flight=d.in_flight,
                delayed=d.delayed,
            )
            for d in queue.depth()
        ],
        dead_letters=queue.dead_letter_count(),
    )


_STAGES = ("normalize", "separate", "transcribe", "quantize", "notation", "tab")
_STAGE_ORDER = {stage: i for i, stage in enumerate(_STAGES)}


# --- retention ---


class Cohort(BaseModel):
    week: date  # the Monday of the week they signed up (UTC)
    size: int
    transcribed: list[int]  # [i]: how many made a transcription in week i after signing up


class Retention(BaseModel):
    cohorts: list[Cohort]


@router.get("/retention")
def retention(
    session: SessionDep,
    accounts_source: AccountsDep,
    weeks: Annotated[int, Query(ge=1, le=52)] = 8,
) -> Retention:
    """Weekly sign-up cohorts and, per later week, how many of them transcribed something.
    Transcribing is the activity we record; opening the app to read a score isn't (yet)."""
    today = datetime.now(UTC).date()
    this_week = today - timedelta(days=today.weekday())
    first_week = this_week - timedelta(weeks=weeks - 1)
    joined = {a.id: _monday(a.joined.date()) for a in accounts_or_db(accounts_source, session)}
    week = func.date_trunc("week", Job.created_at)
    active: set[tuple[str, date]] = {
        (user_id, _utc(w).date())
        for user_id, w in session.execute(
            select(Job.user_id, week).where(Job.submitted_at.is_not(None)).distinct()
        ).all()
    }
    cohorts = []
    for offset in range(weeks):
        start = first_week + timedelta(weeks=offset)
        members = [u for u, w in joined.items() if w == start]
        later = (this_week - start).days // 7 + 1
        cohorts.append(
            Cohort(
                week=start,
                size=len(members),
                transcribed=[
                    sum((u, start + timedelta(weeks=i)) in active for u in members)
                    for i in range(later)
                ],
            )
        )
    return Retention(cohorts=cohorts)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


# --- users ---


class UserRow(BaseModel):
    id: str
    email: str | None
    method: str
    joined: datetime
    last_active: datetime | None
    terms_accepted: bool
    transcriptions: int
    failed: int
    last_transcription: datetime | None
    notification_devices: int
    plan: Plan
    plan_changed_at: datetime | None


class UserList(BaseModel):
    users: list[UserRow]


@router.get("/users")
def users(session: SessionDep, accounts_source: AccountsDep) -> UserList:
    accounts = accounts_or_db(accounts_source, session)
    jobs = {
        user_id: (n, f, last)
        for user_id, n, f, last in session.execute(
            select(
                Job.user_id,
                func.count(),
                func.count().filter(Job.status == JobStatus.FAILED),
                func.max(Job.created_at),
            )
            .where(Job.submitted_at.is_not(None))
            .group_by(Job.user_id)
        ).all()
    }
    devices = dict(
        session.execute(select(PushToken.user_id, func.count()).group_by(PushToken.user_id)).all()
    )
    known = {
        row.id: row
        for row in session.execute(
            select(User.id, User.terms_version, User.plan, User.plan_changed_at)
        ).all()
    }
    rows = []
    for a in sorted(accounts, key=lambda a: a.joined, reverse=True):
        n, f, last = jobs.get(a.id, (0, 0, None))
        rows.append(
            UserRow(
                id=a.id,
                email=a.email,
                method=a.method,
                joined=a.joined,
                last_active=a.last_active,
                terms_accepted=a.id in known and known[a.id].terms_version is not None,
                transcriptions=n,
                failed=f,
                last_transcription=_utc(last) if last else None,
                notification_devices=devices.get(a.id, 0),
                plan=known[a.id].plan if a.id in known else Plan.FREE,
                plan_changed_at=(
                    _utc(changed)
                    if a.id in known and (changed := known[a.id].plan_changed_at)
                    else None
                ),
            )
        )
    return UserList(users=rows)


class SetPlanRequest(BaseModel):
    plan: Plan
    note: str | None = Field(default=None, max_length=200)  # why, e.g. "paid for October"


class UserPlan(BaseModel):
    id: str
    plan: Plan
    plan_changed_at: datetime


@router.put("/users/{user_id}/plan")
def set_plan(
    user_id: Annotated[str, Path(max_length=128)],
    body: SetPlanRequest,
    admin: AdminDep,
    session: SessionDep,
) -> UserPlan:
    """Grant (unlimited) or take back (free) a user's plan, recorded in the audit log. Works for
    someone who signed up but never transcribed: their row is created."""
    before = session.scalar(select(User.plan).where(User.id == user_id)) or Plan.FREE
    now = datetime.now(UTC)
    values = {"plan": body.plan, "plan_changed_at": now, "plan_changed_by": admin.id}
    session.execute(
        insert(User)
        .values(id=user_id, **values)
        .on_conflict_do_update(index_elements=[User.id], set_=values)
    )
    session.add(
        AdminAction(
            admin_id=admin.id,
            action="set_plan",
            target_user_id=user_id,
            detail={"from": before.value, "to": body.plan.value, "note": body.note},
        )
    )
    session.commit()
    logger.info(
        "plan changed",
        extra={"target_user_id": user_id, "from": before.value, "to": body.plan.value},
    )
    return UserPlan(id=user_id, plan=body.plan, plan_changed_at=now)


class AdminActionRow(BaseModel):
    at: datetime
    admin_id: str
    action: str
    target_user_id: str
    detail: dict[str, Any]


class AdminActionList(BaseModel):
    actions: list[AdminActionRow]


@router.get("/actions")
def actions(
    session: SessionDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> AdminActionList:
    """The audit log, newest first."""
    rows = session.scalars(
        select(AdminAction).order_by(AdminAction.created_at.desc()).limit(limit)
    ).all()
    return AdminActionList(
        actions=[
            AdminActionRow(
                at=_utc(r.created_at),
                admin_id=r.admin_id,
                action=r.action,
                target_user_id=r.target_user_id,
                detail=r.detail,
            )
            for r in rows
        ]
    )


class JobRow(BaseModel):
    id: str
    name: str | None
    instrument: str | None
    status: str
    created_at: datetime
    finished_at: datetime | None
    seconds: float | None  # submitted to finished
    error_code: str | None
    error_message: str | None


class UserJobs(BaseModel):
    jobs: list[JobRow]


@router.get("/users/{user_id}/jobs")
def user_jobs(user_id: str, session: SessionDep) -> UserJobs:
    finished_s = func.extract("epoch", Job.finished_at - Job.submitted_at)
    rows = session.execute(
        select(Job, case((Job.finished_at.is_not(None), finished_s), else_=None))
        .where(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
        .limit(200)
    ).all()
    return UserJobs(
        jobs=[
            JobRow(
                id=str(job.id),
                name=job.name,
                instrument=job.config.get("instrument"),
                status=job.status.value,
                created_at=_utc(job.created_at),
                finished_at=_utc(job.finished_at) if job.finished_at else None,
                seconds=round(float(seconds), 1) if seconds is not None else None,
                error_code=job.error_code,
                error_message=(job.error_message or "")[:300] or None,
            )
            for job, seconds in rows
        ]
    )
