import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from tabscribe_platform.db import PushToken
from testsupport.api import auth

pytestmark = pytest.mark.integration

TOKEN = "ExponentPushToken[abc123_XYZ-9]"


def tokens(db: Engine) -> list[tuple[str, str, str]]:
    with Session(db) as session:
        rows = session.execute(select(PushToken.token, PushToken.user_id, PushToken.platform))
        return [tuple(row) for row in rows]  # type: ignore[misc]


def test_register_and_remove_a_device(api: TestClient, alice: str, db: Engine) -> None:
    body = {"token": TOKEN, "platform": "android"}
    assert api.put("/me/push-tokens", json=body, headers=auth(alice)).status_code == 204
    assert api.put("/me/push-tokens", json=body, headers=auth(alice)).status_code == 204  # again
    assert (TOKEN, alice, "android") in tokens(db)

    # Only the owner can remove it; anyone else is ignored without saying so.
    assert api.delete(f"/me/push-tokens/{TOKEN}", headers=auth("mallory")).status_code == 204
    assert (TOKEN, alice, "android") in tokens(db)
    assert api.delete(f"/me/push-tokens/{TOKEN}", headers=auth(alice)).status_code == 204
    assert all(token != TOKEN for token, _, _ in tokens(db))


def test_a_device_follows_whoever_signs_in(api: TestClient, alice: str, db: Engine) -> None:
    body = {"token": TOKEN, "platform": "ios"}
    api.put("/me/push-tokens", json=body, headers=auth(alice))
    api.put("/me/push-tokens", json=body, headers=auth(f"{alice}-other"))
    assert [(t, u) for t, u, _ in tokens(db) if t == TOKEN] == [(TOKEN, f"{alice}-other")]
    api.delete(f"/me/push-tokens/{TOKEN}", headers=auth(f"{alice}-other"))


@pytest.mark.parametrize(
    "body",
    [
        {"token": "not-an-expo-token", "platform": "android"},
        {"token": TOKEN, "platform": "windows"},
        {"token": "ExponentPushToken[" + "a" * 300 + "]", "platform": "ios"},
    ],
)
def test_rejects_bad_tokens(api: TestClient, alice: str, body: dict[str, str]) -> None:
    assert api.put("/me/push-tokens", json=body, headers=auth(alice)).status_code == 422


def test_needs_a_signed_in_user(api: TestClient) -> None:
    body = {"token": TOKEN, "platform": "ios"}
    assert api.put("/me/push-tokens", json=body).status_code == 401
