"""Postgres fixtures shared by the platform, API and worker tests. They need `make up` running."""

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

# The docker-compose Postgres. CI sets TEST_DATABASE_URL to its service container.
DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://tabscribe:tabscribe@localhost:5433/tabscribe"
ALEMBIC_INI = Path(__file__).parent.parent / "packages/platform/alembic.ini"

type Migrate = Callable[..., None]


def _migrate(engine: Engine, revision: str = "head", *, down: bool = False) -> None:
    cfg = Config(str(ALEMBIC_INI))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        (command.downgrade if down else command.upgrade)(cfg, revision)


@pytest.fixture(scope="session")
def migrate() -> Migrate:
    """`migrate(engine, revision="head", down=False)`: run Alembic on a test database."""
    return _migrate


def _admin_engine() -> Engine:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        engine.connect().close()
    except OperationalError as exc:
        pytest.fail(f"cannot reach Postgres at {make_url(url)!r}; run `make up` first ({exc})")
    return engine


@pytest.fixture(scope="session")
def fresh_database() -> Iterator[Engine]:
    """An empty database that is dropped afterwards. Tests may migrate it however they like."""
    admin = _admin_engine()
    name = f"tabscribe_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(admin.url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def db_engine(fresh_database: Engine) -> Engine:
    """A database migrated to the latest schema, shared by the whole test session."""
    _migrate(fresh_database)
    return fresh_database


@pytest.fixture
def db(db_engine: Engine) -> Iterator[Engine]:
    """The migrated database, emptied after each test."""
    yield db_engine
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE users, jobs, stage_runs, score_versions, result_cache CASCADE"))
