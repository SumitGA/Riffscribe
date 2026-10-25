"""plans and admin actions: a user's plan (free or unlimited) and an audit log of admin changes

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-25 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("plan", sa.String(length=32), nullable=False, server_default="free"),
    )
    op.create_check_constraint(op.f("ck_users_plan"), "users", "plan IN ('free', 'unlimited')")
    op.add_column("users", sa.Column("plan_changed_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("plan_changed_by", sa.String(length=128)))
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("admin_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target_user_id", sa.String(length=128), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_actions")),
    )
    op.create_index(op.f("ix_admin_actions_created_at"), "admin_actions", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_actions_created_at"), table_name="admin_actions")
    op.drop_table("admin_actions")
    op.drop_column("users", "plan_changed_by")
    op.drop_column("users", "plan_changed_at")
    op.drop_constraint(op.f("ck_users_plan"), "users", type_="check")
    op.drop_column("users", "plan")
