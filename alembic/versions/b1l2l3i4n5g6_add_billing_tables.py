"""Add billing tables (plans and subscriptions)

Revision ID: b1l2l3i4n5g6
Revises: s1a2c3k4
Create Date: 2025-12-28

Adds Plan and Subscription tables for Stripe billing integration.
Seeds default Free and Pro plans, and creates subscriptions for all existing workspaces.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM


# revision identifiers, used by Alembic.
revision: str = "b1l2l3i4n5g6"
down_revision: Union[str, Sequence[str], None] = "s1a2c3k4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create billing tables and seed default plans."""
    # Create plantype enum (if not exists to handle partial migrations)
    op.execute(
        sa.text(
            "DO $$ BEGIN CREATE TYPE plantype AS ENUM ('free', 'pro'); EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
    )

    # Create subscriptionstatus enum (if not exists to handle partial migrations)
    op.execute(
        sa.text(
            "DO $$ BEGIN CREATE TYPE subscriptionstatus AS ENUM ('active', 'past_due', 'canceled', 'incomplete', 'trialing'); EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
    )

    # Create plans table
    op.create_table(
        "plans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column(
            "plan_type",
            ENUM("free", "pro", name="plantype", create_type=False),
            nullable=False,
        ),
        sa.Column("stripe_price_id", sa.String(255), nullable=True),
        sa.Column("base_service_count", sa.Integer(), nullable=False, default=5),
        sa.Column("base_price_cents", sa.Integer(), nullable=False, default=0),
        sa.Column(
            "additional_service_price_cents", sa.Integer(), nullable=False, default=500
        ),
        sa.Column("rca_session_limit_daily", sa.Integer(), nullable=False, default=10),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Create subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column(
            "status",
            ENUM(
                "active",
                "past_due",
                "canceled",
                "incomplete",
                "trialing",
                name="subscriptionstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("billable_service_count", sa.Integer(), nullable=False, default=0),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.UniqueConstraint("workspace_id"),
    )

    # Create indexes for subscriptions
    op.create_index("idx_subscriptions_workspace", "subscriptions", ["workspace_id"])
    op.create_index(
        "idx_subscriptions_stripe_customer", "subscriptions", ["stripe_customer_id"]
    )
    op.create_index(
        "idx_subscriptions_stripe_subscription",
        "subscriptions",
        ["stripe_subscription_id"],
    )
    op.create_index("idx_subscriptions_status", "subscriptions", ["status"])

    # Seed default plans
    # Free plan: 5 services, 10 RCA sessions/day, $0
    # Pro plan: 5 base services, 100 RCA sessions/day, $30/month, $5/additional service
    op.execute(
        sa.text(
            """
            INSERT INTO plans (
                id, name, plan_type, stripe_price_id,
                base_service_count, base_price_cents,
                additional_service_price_cents, rca_session_limit_daily,
                is_active, created_at
            )
            VALUES
                (
                    gen_random_uuid()::text, 'Free', 'free', NULL,
                    5, 0, 0, 10,
                    true, NOW()
                ),
                (
                    gen_random_uuid()::text, 'Pro', 'pro', NULL,
                    5, 3000, 500, 100,
                    true, NOW()
                )
            """
        )
    )

    # Create subscription for all existing workspaces (Free plan)
    op.execute(
        sa.text(
            """
            INSERT INTO subscriptions (
                id, workspace_id, plan_id, status,
                billable_service_count, created_at
            )
            SELECT
                gen_random_uuid()::text,
                w.id,
                p.id,
                'active',
                0,
                NOW()
            FROM workspaces w
            CROSS JOIN plans p
            WHERE p.plan_type = 'free'
            """
        )
    )


def downgrade() -> None:
    """Remove billing tables."""
    # Drop subscriptions table first (has foreign key to plans)
    op.drop_index("idx_subscriptions_status", table_name="subscriptions")
    op.drop_index("idx_subscriptions_stripe_subscription", table_name="subscriptions")
    op.drop_index("idx_subscriptions_stripe_customer", table_name="subscriptions")
    op.drop_index("idx_subscriptions_workspace", table_name="subscriptions")
    op.drop_table("subscriptions")

    # Drop plans table
    op.drop_table("plans")

    # Drop enums
    op.execute(sa.text("DROP TYPE IF EXISTS subscriptionstatus"))
    op.execute(sa.text("DROP TYPE IF EXISTS plantype"))
