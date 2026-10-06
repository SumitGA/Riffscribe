"""The mobile app's API types are generated from a committed copy of the OpenAPI schema; this
keeps that copy in step with the API."""

from pathlib import Path

import pytest

from api.main import app
from api.openapi import schema_json

pytestmark = pytest.mark.unit

COMMITTED = Path(__file__).resolve().parents[3] / "apps/mobile/src/api/openapi.json"


def test_the_mobile_apps_schema_copy_is_current() -> None:
    assert COMMITTED.read_text() == schema_json(app.openapi()), (
        "the API changed: run `make api-types` and commit the result"
    )
