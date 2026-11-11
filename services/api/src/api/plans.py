"""What each plan allows, and where a user's plan comes from (ADR-0016).

The limits are API settings, so they change with a deploy and no app update: the app reads them
from `GET /me`. A plan comes from a store subscription (synced from RevenueCat, `api.billing`)
or from the admin section, whichever gives more.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.revenuecat import PROMOTIONAL
from api.settings import ApiSettings
from tabscribe_platform.db import Plan, Subscription, User
from tabscribe_platform.jobqueue import Priority


class PlanSource(StrEnum):
    """Why the user has their plan."""

    DEFAULT = "default"  # nobody changed it: free
    ADMIN = "admin"  # set in the admin section (a grant, or taken back to free)
    STORE = "store"  # an active store subscription (or Pro granted in RevenueCat)


_RANK = {Plan.FREE: 0, Plan.PRO: 1, Plan.UNLIMITED: 2}


@dataclass(frozen=True)
class PlanLimits:
    jobs_per_month: int | None  # None: no monthly limit
    max_clip_s: int
    max_upload_bytes: int
    priority: Priority  # where its jobs wait in the queue


@dataclass(frozen=True)
class SubscriptionState:
    """The user's latest Pro subscription, active or not, for the app's Account screen."""

    row: Subscription
    active: bool  # it gives Pro now (paid up, or in the store's grace period)


@dataclass(frozen=True)
class UserPlan:
    plan: Plan
    source: PlanSource
    limits: PlanLimits
    subscription: SubscriptionState | None


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


def gives_access(sub: Subscription, now: datetime) -> bool:
    if sub.refunded_at is not None:
        return False
    if sub.expires_at is None:  # never expires (e.g. a lifetime promotional grant)
        return True
    grace = sub.grace_period_expires_at
    return sub.expires_at > now or (grace is not None and grace > now)


def subscription_of(
    session: Session, user_id: str, settings: ApiSettings, *, now: datetime | None = None
) -> SubscriptionState | None:
    """The user's Pro subscription in this environment: an active one if any (the one lasting
    longest), else the one that ended last. Promotional grants count in every environment, and
    test purchases count for the accounts in BILLING_SANDBOX_USER_IDS."""
    now = now or datetime.now(UTC)
    rows = [
        r
        for r in session.scalars(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.entitlement == settings.revenuecat_entitlement,
            )
        )
        if r.store == PROMOTIONAL or settings.counts(r.environment, user_id)
    ]
    if not rows:
        return None

    def ends(sub: Subscription) -> datetime:
        return max(
            (t for t in (sub.expires_at, sub.grace_period_expires_at) if t is not None),
            default=datetime.max.replace(tzinfo=UTC),
        )

    active = [r for r in rows if gives_access(r, now)]
    if active:
        return SubscriptionState(row=max(active, key=ends), active=True)
    return SubscriptionState(row=max(rows, key=ends), active=False)


def plan_of(session: Session, user_id: str, settings: ApiSettings) -> UserPlan:
    """The user's plan and its limits; free for anyone without a row yet."""
    row = session.execute(select(User.plan, User.plan_changed_by).where(User.id == user_id)).first()
    plan = row.plan if row is not None else Plan.FREE
    changed = row is not None and row.plan_changed_by is not None
    source = PlanSource.ADMIN if changed else PlanSource.DEFAULT
    subscription = subscription_of(session, user_id, settings)
    # A subscription wins a tie with an admin grant of Pro: it's what the user pays for.
    if subscription is not None and subscription.active and _RANK[Plan.PRO] >= _RANK[plan]:
        plan, source = Plan.PRO, PlanSource.STORE
    return UserPlan(
        plan=plan,
        source=source,
        limits=limits_for(plan, settings),
        subscription=subscription,
    )
