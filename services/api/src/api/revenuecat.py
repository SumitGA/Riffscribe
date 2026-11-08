"""RevenueCat's REST API (v1), the API's only view of the stores (ADR-0016).

The webhook says *that* something changed for a customer; what they own now is always read back
from here, so a webhook that arrives late, twice or out of order can't leave a wrong state. The
app user ID is the Clerk user ID (the app logs in to RevenueCat with it).
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from tabscribe_platform.db import BillingEnvironment

API = "https://api.revenuecat.com/v1"
USER_AGENT = "riffscribe-api/1.0"
PROMOTIONAL = "promotional"  # Pro granted in RevenueCat, not bought in a store


class RevenueCatError(Exception):
    """RevenueCat couldn't be reached or refused the request; worth retrying later."""


@dataclass(frozen=True)
class StoreSubscription:
    """One product a customer bought (the `subscriptions` table's columns)."""

    environment: BillingEnvironment
    store: str
    product_id: str
    entitlement: str | None
    period_type: str
    purchased_at: datetime | None
    original_purchased_at: datetime | None
    expires_at: datetime | None
    billing_issue_at: datetime | None
    grace_period_expires_at: datetime | None
    unsubscribed_at: datetime | None
    refunded_at: datetime | None
    store_transaction_id: str | None


class Customers(Protocol):
    """What the API needs from RevenueCat; tests use a fake."""

    def subscriptions(self, app_user_id: str) -> list[StoreSubscription]: ...

    def delete(self, app_user_id: str) -> None: ...


class RevenueCat:
    def __init__(self, secret_api_key: str, *, timeout_s: float = 10) -> None:
        self._key = secret_api_key
        self._timeout_s = timeout_s

    def _request(self, method: str, app_user_id: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{API}/subscribers/{urllib.parse.quote(app_user_id, safe='')}",
            method=method,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                body: dict[str, Any] = json.loads(response.read() or b"{}")
                return body
        except urllib.error.HTTPError as error:
            if method == "DELETE" and error.code == 404:  # already gone
                return {}
            raise RevenueCatError(f"RevenueCat answered {error.code}") from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise RevenueCatError(f"RevenueCat unreachable: {error}") from error

    def subscriptions(self, app_user_id: str) -> list[StoreSubscription]:
        # GET creates an empty customer if there is none, which is harmless.
        return parse_subscriber(self._request("GET", app_user_id))

    def delete(self, app_user_id: str) -> None:
        """Delete the customer and their purchase history (account deletion). The stores keep
        billing; an active subscription has to be cancelled in the store."""
        self._request("DELETE", app_user_id)


def _time(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


def _same_product(a: str, b: str) -> bool:
    # Google Play products can appear as "pro" or "pro:monthly" (subscription:base plan).
    return a == b or a.split(":")[0] == b.split(":")[0]


def parse_subscriber(body: dict[str, Any]) -> list[StoreSubscription]:
    """The products in a `GET /subscribers/{id}` response, each with the entitlement it unlocks."""
    subscriber = body.get("subscriber") or {}
    entitlements: dict[str, Any] = subscriber.get("entitlements") or {}
    result = []
    for product_id, sub in (subscriber.get("subscriptions") or {}).items():
        entitlement = next(
            (
                name
                for name, e in entitlements.items()
                if isinstance(e.get("product_identifier"), str)
                and _same_product(e["product_identifier"], product_id)
            ),
            None,
        )
        result.append(
            StoreSubscription(
                environment=(
                    BillingEnvironment.SANDBOX
                    if sub.get("is_sandbox")
                    else BillingEnvironment.PRODUCTION
                ),
                store=str(sub.get("store") or "unknown")[:32],
                product_id=product_id[:128],
                entitlement=entitlement,
                period_type=str(sub.get("period_type") or "normal")[:16],
                purchased_at=_time(sub.get("purchase_date")),
                original_purchased_at=_time(sub.get("original_purchase_date")),
                expires_at=_time(sub.get("expires_date")),
                billing_issue_at=_time(sub.get("billing_issues_detected_at")),
                grace_period_expires_at=_time(sub.get("grace_period_expires_date")),
                unsubscribed_at=_time(sub.get("unsubscribe_detected_at")),
                refunded_at=_time(sub.get("refunded_at")),
                store_transaction_id=(
                    str(sub["store_transaction_id"])[:128]
                    if sub.get("store_transaction_id")
                    else None
                ),
            )
        )
    return result
