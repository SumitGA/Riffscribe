"""What each plan allows, and where a user's plan comes from (ADR-0016).

The limits are API settings, so they change with a deploy and no app update: the app reads them
from `GET /me`. Store subscriptions (RevenueCat) will become a second source of the plan; until
then a plan other than free can only come from the admin section.
"""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.settings import ApiSettings
from tabscribe_platform.db import Plan, User
from tabscribe_platform.jobqueue import Priority


class PlanSource(StrEnum):
    """Why the user has their plan."""

    DEFAULT = "default"  # nobody changed it: free
    ADMIN = "admin"  # set in the admin section (a grant, or taken back to free)


@dataclass(frozen=True)
class PlanLimits:
    jobs_per_month: int | None  # None: no monthly limit
    max_clip_s: int
    max_upload_bytes: int
    priority: Priority  # where its jobs wait in the queue


@dataclass(frozen=True)
class UserPlan:
    plan: Plan
    source: PlanSource
    limits: PlanLimits


def limits_for(plan: Plan, settings: ApiSettings) -> PlanLimits:
    if plan is Plan.FREE:
        return PlanLimits(
            jobs_per_month=settings.free_jobs_per_month,
            max_clip_s=settings.free_max_clip_s,
            max_upload_bytes=settings.max_upload_bytes,
            priority=Priority.NORMAL,
        )
    # Unlimited is Pro without the monthly limit (granted, never sold).
    return PlanLimits(
        jobs_per_month=settings.pro_jobs_per_month if plan is Plan.PRO else None,
        max_clip_s=settings.pro_max_clip_s,
        max_upload_bytes=settings.pro_max_upload_bytes,
        priority=Priority.HIGH,
    )


def plan_of(session: Session, user_id: str, settings: ApiSettings) -> UserPlan:
    """The user's plan and its limits; free for anyone without a row yet."""
    row = session.execute(select(User.plan, User.plan_changed_by).where(User.id == user_id)).first()
    plan = row.plan if row is not None else Plan.FREE
    changed = row is not None and row.plan_changed_by is not None
    source = PlanSource.ADMIN if changed else PlanSource.DEFAULT
    return UserPlan(plan=plan, source=source, limits=limits_for(plan, settings))
