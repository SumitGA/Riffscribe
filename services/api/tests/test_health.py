import pytest
from fastapi.testclient import TestClient

from api.main import app

pytestmark = pytest.mark.unit


def test_healthz() -> None:
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
