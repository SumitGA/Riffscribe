from collections.abc import Callable

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tabscribe_platform.db import Base, Job, JobStatus, ScoreVersion, User

pytestmark = pytest.mark.integration


def _job(user_id: str) -> Job:
    return Job(
        user_id=user_id,
        config={"instrument": "guitar"},
        source_key=f"users/{user_id}/jobs/x/source/upload.m4a",
        source_content_type="audio/mp4",
        source_size_bytes=1234,
    )


def test_migrations_match_models(db: Engine) -> None:
    with db.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_server_default": True})
        assert compare_metadata(context, Base.metadata) == []


def test_migrations_downgrade_and_upgrade(
    fresh_database: Engine, db: Engine, migrate: Callable[..., None]
) -> None:
    migrate(fresh_database, "base", down=True)
    assert inspect(fresh_database).get_table_names() == ["alembic_version"]
    migrate(fresh_database)
    assert "jobs" in inspect(fresh_database).get_table_names()


def test_required_indexes_exist(db: Engine) -> None:
    indexes = {tuple(ix["column_names"]) for ix in inspect(db).get_indexes("jobs")}
    assert ("user_id", "created_at") in indexes
    assert ("status",) in indexes


def test_job_defaults(db: Engine) -> None:
    with Session(db) as session:
        session.add(User(id="alice"))
        session.flush()
        job = _job("alice")
        session.add(job)
        session.commit()
        job_id = job.id

    with Session(db) as session:
        loaded = session.scalars(select(Job).where(Job.user_id == "alice")).one()
        assert loaded.id == job_id
        assert loaded.status is JobStatus.PENDING_UPLOAD
        assert loaded.created_at.tzinfo is not None
        assert loaded.config == {"instrument": "guitar"}


def test_status_is_checked_by_the_database(db: Engine) -> None:
    with Session(db) as session:
        session.add(User(id="alice"))
        session.flush()
        session.add(_job("alice"))
        session.commit()
    with db.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(text("UPDATE jobs SET status = 'exploded'"))


def test_score_versions_are_unique_per_job(db: Engine) -> None:
    with Session(db) as session:
        session.add(User(id="alice"))
        session.flush()
        job = _job("alice")
        session.add(job)
        session.flush()
        for _ in range(2):
            session.add(ScoreVersion(job_id=job.id, user_id="alice", version=0, musicxml_key="k"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_deleting_a_user_deletes_their_jobs(db: Engine) -> None:
    with Session(db) as session:
        session.add(User(id="alice"))
        session.flush()
        session.add(_job("alice"))
        session.commit()
        session.delete(session.get_one(User, "alice"))
        session.commit()
        assert session.scalars(select(Job)).all() == []
