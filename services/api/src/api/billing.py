"""Store subscriptions through RevenueCat (ADR-0016).

`POST /billing/revenuecat` is RevenueCat's webhook. It checks the shared secret, keeps the event
as received (`billing_events`; a repeated delivery is a no-op) and then re-reads each affected
customer from RevenueCat into `subscriptions`. The event itself only says *who* to re-read, so
late, repeated or out-of-order events can't leave a wrong state.

`POST /me/billing/sync` does the same re-read for the caller. The app calls it right after a
purchase or a restore, so Pro doesn't wait for the webhook.

Only purchases from this server's environment count (`BILLING_ENVIRONMENT`): staging takes the
stores' test purchases, production only real ones.
"""

import hmac
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.auth import CurrentUserDep
from api.deps import ApiSettingsDep, LimiterDep, SessionDep
from api.revenuecat import Customers, RevenueCat, RevenueCatError
from api.settings import ApiSettings
from tabscribe_platform.db import BillingEvent, Subscription, User

router = APIRouter(tags=["billing"])
logger = logging.getLogger(__name__)

BILLING_OFF = "billing is not set up"
SYNCS_PER_MINUTE = 6
# RevenueCat's ID for a customer the app hasn't logged in yet; never one of our users.
ANONYMOUS_PREFIX = "$RCAnonymousID:"


def get_customers(settings: ApiSettingsDep) -> Customers | None:
    key = settings.revenuecat_secret_api_key
    return RevenueCat(key.get_secret_value()) if key is not None else None


CustomersDep = Annotated[Customers | None, Depends(get_customers)]


class WebhookEvent(BaseModel):
    """The fields used here; everything else is kept in the stored payload."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=128)
    type: str = Field(max_length=64)
    environment: str = Field(default="PRODUCTION", max_length=16)
    app_user_id: str | None = None
    original_app_user_id: str | None = None
    transferred_from: list[str] = Field(default_factory=list)  # TRANSFER events
    transferred_to: list[str] = Field(default_factory=list)
    store: str | None = None
    product_id: str | None = None
    event_timestamp_ms: int | None = None


class WebhookBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    event: WebhookEvent


def _user_ids(event: WebhookEvent) -> list[str]:
    ids = [event.app_user_id, event.original_app_user_id, *event.transferred_from]
    ids += event.transferred_to
    seen: dict[str, None] = {}
    for i in ids:
        if i and not i.startswith(ANONYMOUS_PREFIX) and len(i) <= 128:
            seen[i] = None
    return list(seen)


def sync_user(session: Session, user_id: str, customers: Customers) -> int:
    """Replace the user's subscriptions with what RevenueCat has now (not committed). Rows for
    products that moved to another account (a TRANSFER) disappear with the replace."""
    # One sync per user at a time (the webhook and the app's sync can race).
    session.execute(select(User.id).where(User.id == user_id).with_for_update())
    subscriptions = customers.subscriptions(user_id)
    session.execute(delete(Subscription).where(Subscription.user_id == user_id))
    now = datetime.now(UTC)
    for sub in subscriptions:
        session.add(Subscription(user_id=user_id, synced_at=now, **asdict(sub)))
    return len(subscriptions)


def _handle(
    session: Session, event: WebhookEvent, settings: ApiSettings, customers: Customers | None
) -> str:
    """Act on one event (inside the caller's transaction) and say what was done."""
    if event.type == "TEST":  # RevenueCat's "send test event" button
        return "test"
    if event.environment.lower() != settings.billing_environment.value:
        return "other_environment"
    ids = _user_ids(event)
    known = list(session.scalars(select(User.id).where(User.id.in_(ids)))) if ids else []
    if not known:
        # Nobody here yet (they haven't used the app since signing in) or the account was
        # deleted. A user who appears later is synced by the app (POST /me/billing/sync).
        return "unknown_user"
    if customers is None:
        raise RevenueCatError("REVENUECAT_SECRET_API_KEY is not set")
    for user_id in known:
        sync_user(session, user_id, customers)
    return "synced"


@router.post("/billing/revenuecat", include_in_schema=False)
def revenuecat_webhook(
    body: WebhookBody,
    session: SessionDep,
    settings: ApiSettingsDep,
    customers: CustomersDep,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    secret = settings.revenuecat_webhook_secret
    if secret is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BILLING_OFF)
    expected = f"Bearer {secret.get_secret_value()}"
    if not hmac.compare_digest((authorization or "").encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong webhook secret")

    event = body.event
    payload: dict[str, Any] = body.model_dump(mode="json")
    event_at = (
        datetime.fromtimestamp(event.event_timestamp_ms / 1000, UTC)
        if event.event_timestamp_ms is not None
        else None
    )
    session.execute(
        insert(BillingEvent)
        .values(
            id=event.id,
            type=event.type,
            environment=event.environment,
            store=event.store[:32] if event.store else None,
            product_id=event.product_id[:128] if event.product_id else None,
            event_at=event_at,
            user_ids=_user_ids(event),
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=[BillingEvent.id])
    )
    session.commit()

    # The row lock makes a second delivery of the same event wait, then see it handled.
    stored = session.get(BillingEvent, event.id, with_for_update=True)
    assert stored is not None
    log = {"event_id": event.id, "event_type": event.type}
    if stored.processed_at is not None:
        session.rollback()
        logger.info("billing event repeated", extra=log)
        return JSONResponse({"outcome": "duplicate"})
    try:
        outcome = _handle(session, event, settings, customers)
    except RevenueCatError as error:
        session.rollback()
        session.execute(
            update(BillingEvent)
            .where(BillingEvent.id == event.id)
            .values(outcome="failed", error=str(error)[:1000])
        )
        session.commit()
        logger.warning("billing event not handled; RevenueCat retries", extra=log)
        # Not 2xx: RevenueCat delivers it again later, and the retry is handled then.
        return JSONResponse({"outcome": "failed"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    stored.processed_at = datetime.now(UTC)
    stored.outcome = outcome
    stored.error = None
    session.commit()
    logger.info("billing event handled", extra={**log, "outcome": outcome})
    return JSONResponse({"outcome": outcome})


@router.post("/me/billing/sync", status_code=status.HTTP_204_NO_CONTENT, tags=["me"])
def sync_my_subscription(
    user: CurrentUserDep, session: SessionDep, limiter: LimiterDep, customers: CustomersDep
) -> None:
    """Re-read the caller's subscriptions from RevenueCat, after a purchase or a restore in the
    app. `GET /me` then shows the plan."""
    if customers is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, BILLING_OFF)
    if not limiter.hit(user.id, "billing_sync", SYNCS_PER_MINUTE, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "try again in a minute")
    session.execute(insert(User).values(id=user.id).on_conflict_do_nothing())
    try:
        count = sync_user(session, user.id, customers)
    except RevenueCatError as error:
        session.rollback()
        logger.warning("subscription sync failed", extra={"error": str(error)})
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "couldn't check your purchases; try again"
        ) from error
    session.commit()
    logger.info("subscriptions synced", extra={"subscriptions": count})
