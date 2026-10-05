"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-05 15:17:24.352748
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_key", sa.String(length=512), nullable=False),
        sa.Column("source_content_type", sa.String(length=128), nullable=False),
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("audio_sha256", sa.String(length=64), nullable=True),
        sa.Column("pipeline_version", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending_upload', 'queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_jobs_jobstatus"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_jobs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(
        op.f("ix_jobs_user_id_created_at"), "jobs", ["user_id", "created_at"], unique=False
    )
    op.create_table(
        "result_cache",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_result_cache_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_result_cache")),
    )
    op.create_table(
        "score_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("musicxml_key", sa.String(length=512), nullable=False),
        sa.Column("tab_musicxml_key", sa.String(length=512), nullable=True),
        sa.Column("midi_key", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_score_versions_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_score_versions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_score_versions")),
        sa.UniqueConstraint("job_id", "version", name=op.f("uq_score_versions_job_id_version")),
    )
    op.create_index(op.f("ix_score_versions_user_id"), "score_versions", ["user_id"], unique=False)
    op.create_table(
        "stage_runs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_s", sa.Double(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'skipped', 'failed')",
            name=op.f("ck_stage_runs_stagestatus"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_stage_runs_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id", "stage", name=op.f("pk_stage_runs")),
    )


def downgrade() -> None:
    op.drop_table("stage_runs")
    op.drop_index(op.f("ix_score_versions_user_id"), table_name="score_versions")
    op.drop_table("score_versions")
    op.drop_table("result_cache")
    op.drop_index(op.f("ix_jobs_user_id_created_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("users")
