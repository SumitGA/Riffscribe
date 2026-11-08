"""subscriptions: store subscriptions as RevenueCat reports them, and every webhook it sent

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-07 18:00:00
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _at(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True))


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("store", sa.String(length=32), nullable=False),
        sa.Column("product_id", sa.String(length=128), nullable=False),
        sa.Column("entitlement", sa.String(length=64)),
        sa.Column("period_type", sa.String(length=16), nullable=False),
        _at("purchased_at"),
        _at("original_purchased_at"),
        _at("expires_at"),
        _at("billing_issue_at"),
        _at("grace_period_expires_at"),
        _at("unsubscribed_at"),
        _at("refunded_at"),
        sa.Column("store_transaction_id", sa.String(length=128)),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        # The model's enum check (named after BillingEnvironment).
        sa.CheckConstraint(
            "environment IN ('sandbox', 'production')",
            name=op.f("ck_subscriptions_billingenvironment"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "environment",
            "store",
            "product_id",
            name=op.f("uq_subscriptions_user_id_environment_store_product_id"),
        ),
    )
    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("store", sa.String(length=32)),
        sa.Column("product_id", sa.String(length=128)),
        _at("event_at"),
        sa.Column("user_ids", postgresql.ARRAY(sa.String(length=128)), nullable=False),
        _at("processed_at"),
        sa.Column("outcome", sa.String(length=32)),
        sa.Column("error", sa.Text()),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_events")),
    )
    op.create_index(op.f("ix_billing_events_received_at"), "billing_events", ["received_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_billing_events_received_at"), table_name="billing_events")
    op.drop_table("billing_events")
    op.drop_table("subscriptions")
