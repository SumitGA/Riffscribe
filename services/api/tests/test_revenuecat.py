"""Reading RevenueCat's customer response (`GET /v1/subscribers/{id}`)."""

from datetime import UTC, datetime

from api.revenuecat import parse_subscriber
from tabscribe_platform.db import BillingEnvironment

# Shaped like RevenueCat's documented response, trimmed.
SUBSCRIBER = {
    "request_date": "2026-11-07T10:00:00Z",
    "subscriber": {
        "original_app_user_id": "user_abc",
        "entitlements": {
            "pro": {
                "expires_date": "2026-12-07T10:00:00Z",
                "grace_period_expires_date": None,
                "product_identifier": "pro:monthly",
                "purchase_date": "2026-11-07T10:00:00Z",
            }
        },
        "subscriptions": {
            "pro:monthly": {
                "billing_issues_detected_at": None,
                "expires_date": "2026-12-07T10:00:00Z",
                "grace_period_expires_date": None,
                "is_sandbox": True,
                "original_purchase_date": "2026-11-07T10:00:00Z",
                "period_type": "trial",
                "purchase_date": "2026-11-07T10:00:00Z",
                "refunded_at": None,
                "store": "play_store",
                "store_transaction_id": "GPA.1234-5678",
                "unsubscribe_detected_at": "2026-11-08T09:00:00Z",
            },
            "old_product": {
                "expires_date": "2025-01-01T00:00:00Z",
                "is_sandbox": False,
                "store": "app_store",
            },
        },
    },
}


def test_reads_each_product_and_its_entitlement() -> None:
    play, old = parse_subscriber(SUBSCRIBER)
    assert play.environment is BillingEnvironment.SANDBOX
    assert (play.store, play.product_id, play.entitlement) == ("play_store", "pro:monthly", "pro")
    assert play.period_type == "trial"
    assert play.expires_at == datetime(2026, 12, 7, 10, tzinfo=UTC)
    assert play.unsubscribed_at == datetime(2026, 11, 8, 9, tzinfo=UTC)
    assert play.store_transaction_id == "GPA.1234-5678"
    assert play.billing_issue_at is None and play.refunded_at is None

    assert old.environment is BillingEnvironment.PRODUCTION
    assert old.entitlement is None and old.period_type == "normal"


def test_an_empty_customer_has_nothing() -> None:
    assert parse_subscriber({"subscriber": {"entitlements": {}, "subscriptions": {}}}) == []
    assert parse_subscriber({}) == []
