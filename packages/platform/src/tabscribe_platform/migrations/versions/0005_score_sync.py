"""score sync: when each bar starts in the uploaded audio, for synced playback

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-09 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("score_versions", sa.Column("sync_key", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("score_versions", "sync_key")
