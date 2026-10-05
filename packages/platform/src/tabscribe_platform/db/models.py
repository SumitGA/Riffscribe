"""Database tables. Postgres holds metadata only; audio and scores live in object storage.

Every query on user data must filter by `user_id` (tenant isolation, CLAUDE.md).
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint names, so Alembic migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


def _enum[E: StrEnum](cls: type[E]) -> Enum:
    # VARCHAR + CHECK rather than a native Postgres enum: adding a value is then a plain migration.
    return Enum(
        cls,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


class JobStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StageStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    FAILED = "failed"


class User(Base):
    """A user known to the auth provider. `id` is the JWT `sub`; no passwords are stored here."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(None, "user_id", "created_at"),
        Index(None, "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.PENDING_UPLOAD)
    # The pipeline settings (instrument, tuning, capo, ...) as `PipelineConfig` JSON.
    config: Mapped[dict[str, Any]]

    # The upload, as declared by the client and checked on submit.
    source_key: Mapped[str] = mapped_column(String(512))
    source_content_type: Mapped[str] = mapped_column(String(128))
    source_size_bytes: Mapped[int] = mapped_column(BigInteger)

    # Set by the worker: sha256 of the normalized audio, and the pipeline that produced the
    # result (CLAUDE.md: results always record their pipeline version).
    audio_sha256: Mapped[str | None] = mapped_column(String(64))
    pipeline_version: Mapped[str | None] = mapped_column(String(64))

    # Machine-readable reason (e.g. `invalid_input`, `stage_failed`) plus a message safe to show.
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=utcnow)
    submitted_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class StageRun(Base):
    """One row per (job, stage): the stage's latest status and how many attempts it has used."""

    __tablename__ = "stage_runs"

    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    stage: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[StageStatus] = mapped_column(_enum(StageStatus), default=StageStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    duration_s: Mapped[float | None]
    last_error: Mapped[str | None] = mapped_column(Text)


class ScoreVersion(Base):
    """A score for a job. Version 0 is the pipeline's output; editor saves (Phase 4) add 1, 2, ...

    Versions are never overwritten.
    """

    __tablename__ = "score_versions"
    __table_args__ = (UniqueConstraint("job_id", "version"), Index(None, "user_id"))

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    musicxml_key: Mapped[str] = mapped_column(String(512))
    tab_musicxml_key: Mapped[str | None] = mapped_column(String(512))
    midi_key: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ResultCache(Base):
    """Dedup cache: a finished job whose results can be copied instead of recomputed.

    `key` = sha256 of (normalized audio sha256, pipeline version, pipeline config).
    """

    __tablename__ = "result_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
