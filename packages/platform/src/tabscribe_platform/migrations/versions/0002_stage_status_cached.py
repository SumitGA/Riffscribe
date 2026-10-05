"""stage status `cached` (dedup cache)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-05 17:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Statuses are VARCHAR + CHECK (models._enum), so a new value means swapping the constraint.
CONSTRAINT = "ck_stage_runs_stagestatus"
OLD = "('queued', 'running', 'succeeded', 'skipped', 'failed')"
NEW = "('queued', 'running', 'succeeded', 'skipped', 'failed', 'cached')"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "stage_runs", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "stage_runs", f"status IN {NEW}")


def downgrade() -> None:
    op.execute("UPDATE stage_runs SET status = 'succeeded' WHERE status = 'cached'")
    op.drop_constraint(op.f(CONSTRAINT), "stage_runs", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "stage_runs", f"status IN {OLD}")
