"""Store subscriptions through RevenueCat (ADR-0016): the webhook, syncing, and the plan they give.

RevenueCat itself is a fake: `customers` holds what it would report for each user.
"""

import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from api.billing import get_customers
from api.main import app
from api.revenuecat import RevenueCatError, StoreSubscription
from tabscribe_platform.db import BillingEnvironment, BillingEvent, Plan, Subscription, User
from tabscribe_platform.jobqueue import JobQueue, Priority, QueueName
from testsupport.api import LIMITS, NEW_JOB, WEBHOOK_SECRET, auth

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)


@dataclass
class FakeCustomers:
    owned: dict[str, list[StoreSubscription]] = field(default_factory=dict)
    down: bool = False
    reads: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def subscriptions(self, app_user_id: str) -> list[StoreSubscription]:
        if self.down:
            raise RevenueCatError("RevenueCat answered 500")
        self.reads.append(app_user_id)
        return self.owned.get(app_user_id, [])

    def delete(self, app_user_id: str) -> None:
        self.deleted.append(app_user_id)


@pytest.fixture
def customers(api: TestClient) -> Iterator[FakeCustomers]:
    fake = FakeCustomers()
    app.dependency_overrides[get_customers] = lambda: fake
    yield fake


PRO_MONTHLY = StoreSubscription(
    environment=BillingEnvironment.SANDBOX,
    store="app_store",
    product_id="pro_monthly",
    entitlement="pro",
    period_type="normal",
    purchased_at=NOW - timedelta(days=1),
    original_purchased_at=NOW - timedelta(days=1),
    expires_at=NOW + timedelta(days=29),
    billing_issue_at=None,
    grace_period_expires_at=None,
    unsubscribed_at=None,
    refunded_at=None,
    store_transaction_id="2000000123",
)


def known_user(db: Engine, user_id: str, plan: Plan = Plan.FREE) -> None:
    with Session(db) as session:
        changed_by = "admin_1" if plan is not Plan.FREE else None
        session.add(User(id=user_id, plan=plan, plan_changed_by=changed_by))
        session.commit()


def send(
    api: TestClient,
    user_id: str | None,
    *,
    type: str = "INITIAL_PURCHASE",
    environment: str = "SANDBOX",
    event_id: str | None = None,
    secret: str = WEBHOOK_SECRET,
    **extra: Any,
) -> Any:
    event = {
        "id": event_id or str(uuid.uuid4()),
        "type": type,
        "environment": environment,
        "app_user_id": user_id,
        "original_app_user_id": user_id,
        "store": "APP_STORE",
        "product_id": "pro_monthly",
        "entitlement_ids": ["pro"],
        "event_timestamp_ms": int(NOW.timestamp() * 1000),
        "price": 4.99,
        "currency": "AUD",
        **extra,
    }
    body = {"api_version": "1.0", "event": event}
    return api.post("/billing/revenuecat", json=body, headers={"Authorization": f"Bearer {secret}"})


def me(api: TestClient, user_id: str) -> dict[str, Any]:
    result: dict[str, Any] = api.get("/me", headers=auth(user_id)).json()
    return result


def events(db: Engine) -> list[BillingEvent]:
    with Session(db) as session:
        return list(session.scalars(select(BillingEvent)))


def test_the_webhook_needs_the_secret(api: TestClient, customers: FakeCustomers) -> None:
    assert send(api, "user_x", secret="wrong").status_code == 401
    response = api.post("/billing/revenuecat", json={"event": {"id": "e", "type": "TEST"}})
    assert response.status_code == 401
    assert customers.reads == []


def test_a_purchase_gives_pro_from_the_store(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers, job_queue: JobQueue
) -> None:
    known_user(db, alice)
    customers.owned[alice] = [PRO_MONTHLY]
    response = send(api, alice)
    assert (response.status_code, response.json()) == (200, {"outcome": "synced"})

    body = me(api, alice)
    assert (body["plan"], body["plan_source"]) == ("pro", "store")
    assert body["limits"]["jobs_per_month"] == LIMITS.pro_jobs_per_month
    sub = body["subscription"]
    assert sub["store"] == "app_store" and sub["product_id"] == "pro_monthly"
    assert sub["active"] and sub["will_renew"] and not sub["billing_issue"]
    assert datetime.fromisoformat(sub["expires_at"]) == PRO_MONTHLY.expires_at

    # The subscription's limits apply to jobs.
    created = api.post("/jobs", json=NEW_JOB, headers=auth(alice)).json()
    assert created["job"]["id"]
    [stored] = events(db)
    assert stored.outcome == "synced" and stored.processed_at is not None
    assert stored.user_ids == [alice] and stored.payload["event"]["price"] == 4.99


def test_a_repeated_event_is_handled_once(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers
) -> None:
    known_user(db, alice)
    customers.owned[alice] = [PRO_MONTHLY]
    assert send(api, alice, event_id="evt_1").json() == {"outcome": "synced"}
    assert send(api, alice, event_id="evt_1").json() == {"outcome": "duplicate"}
    assert customers.reads == [alice]
    assert len(events(db)) == 1


def test_purchases_from_the_other_environment_dont_count(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers
) -> None:
    known_user(db, alice)
    # A real purchase reaching staging (sandbox) is recorded and ignored.
    assert send(api, alice, environment="PRODUCTION").json() == {"outcome": "other_environment"}
    assert customers.reads == []
    # So is a production subscription RevenueCat reports for the user.
    customers.owned[alice] = [replace(PRO_MONTHLY, environment=BillingEnvironment.PRODUCTION)]
    assert send(api, alice).json() == {"outcome": "synced"}
    body = me(api, alice)
    assert body["plan"] == "free" and body["subscription"] is None


def test_rest_api_test_event_and_unknown_users(
    api: TestClient, db: Engine, customers: FakeCustomers
) -> None:
    assert send(api, "anyone", type="TEST").json() == {"outcome": "test"}
    # Someone without a row here (never used the app, or deleted their account): no row made.
    assert send(api, "user_gone").json() == {"outcome": "unknown_user"}
    assert send(api, "$RCAnonymousID:abc").json() == {"outcome": "unknown_user"}
    with Session(db) as session:
        assert session.get(User, "user_gone") is None
    assert customers.reads == []


def test_revenuecat_down_is_retried(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers
) -> None:
    known_user(db, alice)
    customers.owned[alice] = [PRO_MONTHLY]
    customers.down = True
    assert send(api, alice, event_id="evt_2").status_code == 503
    [stored] = events(db)
    assert stored.outcome == "failed" and stored.processed_at is None
    assert me(api, alice)["plan"] == "free"

    customers.down = False  # RevenueCat delivers the event again
    assert send(api, alice, event_id="evt_2").json() == {"outcome": "synced"}
    assert me(api, alice)["plan"] == "pro"


@pytest.mark.parametrize(
    ("change", "plan", "flags"),
    [
        # Cancelled: Pro until the end of the paid period, then it doesn't renew.
        ({"unsubscribed_at": NOW}, "pro", {"active": True, "will_renew": False}),
        # Ended.
        (
            {"expires_at": NOW - timedelta(hours=1)},
            "free",
            {"active": False, "will_renew": False},
        ),
        # A failed renewal in the store's grace period: still Pro, with a warning.
        (
            {
                "expires_at": NOW - timedelta(hours=1),
                "billing_issue_at": NOW - timedelta(hours=1),
                "grace_period_expires_at": NOW + timedelta(days=6),
            },
            "pro",
            {"active": True, "billing_issue": True},
        ),
        # Refunded.
        ({"refunded_at": NOW}, "free", {"active": False, "refunded": True}),
        # A free trial.
        ({"period_type": "trial"}, "pro", {"active": True, "in_trial": True}),
    ],
)
def test_the_subscription_state_sets_the_plan(
    api: TestClient,
    db: Engine,
    alice: str,
    customers: FakeCustomers,
    change: dict[str, Any],
    plan: str,
    flags: dict[str, bool],
) -> None:
    known_user(db, alice)
    customers.owned[alice] = [replace(PRO_MONTHLY, **change)]
    send(api, alice, type="RENEWAL")
    body = me(api, alice)
    assert body["plan"] == plan
    assert body["plan_source"] == ("store" if plan == "pro" else "default")
    assert {k: body["subscription"][k] for k in flags} == flags


def test_an_ended_subscription_brings_back_the_free_limits(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers, job_queue: JobQueue
) -> None:
    known_user(db, alice)
    customers.owned[alice] = [PRO_MONTHLY]
    send(api, alice)
    customers.owned[alice] = [replace(PRO_MONTHLY, expires_at=NOW - timedelta(minutes=1))]
    send(api, alice, type="EXPIRATION")

    created = api.post("/jobs", json=NEW_JOB, headers=auth(alice)).json()
    up = created["upload"]
    urllib.request.urlopen(
        urllib.request.Request(up["url"], data=b"audio", headers=up["headers"], method="PUT"),
        timeout=10,
    ).close()
    assert api.post(f"/jobs/{created['job']['id']}/submit", headers=auth(alice)).status_code == 200
    delivery = job_queue.receive(QueueName.CPU, "test", wait_s=0.1)
    assert delivery is not None and delivery.priority is Priority.NORMAL
    job_queue.ack(delivery)


def test_an_admin_grant_and_a_subscription_give_the_bigger_plan(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers
) -> None:
    known_user(db, alice, Plan.UNLIMITED)
    customers.owned[alice] = [PRO_MONTHLY]
    send(api, alice)
    body = me(api, alice)
    assert (body["plan"], body["plan_source"]) == ("unlimited", "admin")
    assert body["subscription"]["active"]  # shown, so the user can manage it


def test_a_promotional_grant_counts(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers
) -> None:
    known_user(db, alice)
    customers.owned[alice] = [
        replace(
            PRO_MONTHLY,
            environment=BillingEnvironment.PRODUCTION,  # RevenueCat reports grants as production
            store="promotional",
            product_id="rc_promo_pro_monthly",
        )
    ]
    send(api, alice)
    body = me(api, alice)
    assert (body["plan"], body["plan_source"]) == ("pro", "store")
    assert not body["subscription"]["will_renew"]


def test_a_transfer_moves_the_subscription(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers
) -> None:
    bob = f"{alice}-bob"
    known_user(db, alice)
    known_user(db, bob)
    customers.owned[alice] = [PRO_MONTHLY]
    send(api, alice)
    # Bob restores Alice's App Store purchase on his phone; RevenueCat moves it to him.
    customers.owned = {alice: [], bob: [PRO_MONTHLY]}
    response = send(api, None, type="TRANSFER", transferred_from=[alice], transferred_to=[bob])
    assert response.json() == {"outcome": "synced"}
    assert me(api, alice)["plan"] == "free"
    assert me(api, bob)["plan"] == "pro"


def test_the_app_syncs_after_a_purchase(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers
) -> None:
    customers.owned[alice] = [PRO_MONTHLY]
    # Works before the user has a row here, unlike the webhook.
    assert api.post("/me/billing/sync", headers=auth(alice)).status_code == 204
    assert me(api, alice)["plan"] == "pro"
    customers.down = True
    assert api.post("/me/billing/sync", headers=auth(alice)).status_code == 502
    assert me(api, alice)["plan"] == "pro"  # a failed sync changes nothing


def test_without_revenuecat_billing_is_off(api: TestClient, alice: str) -> None:
    # The test settings have no RevenueCat API key.
    assert api.post("/me/billing/sync", headers=auth(alice)).status_code == 404
    assert me(api, alice)["subscription"] is None


def test_deleting_the_account_removes_the_billing_records(
    api: TestClient, db: Engine, alice: str, customers: FakeCustomers
) -> None:
    known_user(db, alice)
    customers.owned[alice] = [PRO_MONTHLY]
    send(api, alice)
    send(api, "someone-else")
    assert api.delete("/me", headers=auth(alice)).status_code == 204
    with Session(db) as session:
        assert session.scalars(select(Subscription)).all() == []
        assert [e.user_ids for e in session.scalars(select(BillingEvent))] == [["someone-else"]]
    assert customers.deleted == [alice]
