"""score edits: version status, base version, edit operations and the editable document

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "score_versions",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
    )
    op.create_check_constraint(
        op.f("ck_score_versions_versionstatus"),
        "score_versions",
        "status IN ('pending', 'ready', 'failed')",
    )
    op.add_column("score_versions", sa.Column("error_message", sa.String(length=500)))
    op.add_column("score_versions", sa.Column("base_version", sa.Integer()))
    op.add_column("score_versions", sa.Column("edits", postgresql.JSONB()))
    op.add_column("score_versions", sa.Column("document_key", sa.String(length=512)))
    op.alter_column("score_versions", "musicxml_key", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM score_versions WHERE musicxml_key IS NULL")
    op.alter_column("score_versions", "musicxml_key", nullable=False)
    op.drop_column("score_versions", "document_key")
    op.drop_column("score_versions", "edits")
    op.drop_column("score_versions", "base_version")
    op.drop_column("score_versions", "error_message")
    op.drop_constraint(op.f("ck_score_versions_versionstatus"), "score_versions")
    op.drop_column("score_versions", "status")
