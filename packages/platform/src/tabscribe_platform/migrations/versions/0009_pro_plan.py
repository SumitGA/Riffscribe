"""pro plan: the paid plan, and each job's clip-length limit from its plan

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-07 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_users_plan"), "users", type_="check")
    op.create_check_constraint(
        op.f("ck_users_plan"), "users", "plan IN ('free', 'pro', 'unlimited')"
    )
    op.add_column("jobs", sa.Column("max_duration_s", sa.Integer()))


def downgrade() -> None:
    op.drop_column("jobs", "max_duration_s")
    op.execute("UPDATE users SET plan = 'free' WHERE plan = 'pro'")
    op.drop_constraint(op.f("ck_users_plan"), "users", type_="check")
    op.create_check_constraint(op.f("ck_users_plan"), "users", "plan IN ('free', 'unlimited')")
