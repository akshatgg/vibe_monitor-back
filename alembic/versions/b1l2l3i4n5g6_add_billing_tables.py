"""Add billing tables (plans and subscriptions)

Revision ID: b1l2l3i4n5g6
Revises: s1a2c3k4
Create Date: 2025-12-28
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM


revision: str = "b1l2l3i4n5g6"
down_revision: Union[str, Sequence[str], None] = "s1a2c3k4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------- Upgrade ----------

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())

    # ----- Enums (idempotent) -----
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE plantype AS ENUM ('free', 'pro');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE subscriptionstatus AS ENUM (
                'active', 'past_due', 'canceled', 'incomplete', 'trialing'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # ----- Plans table -----
    if "plans" not in existing_tables:
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
    else:
        print("  ⊘ Table 'plans' already exists, skipping...")

    # ----- Subscriptions table -----
    if "subscriptions" not in existing_tables:
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
    else:
        print("  ⊘ Table 'subscriptions' already exists, skipping...")

    # ----- Indexes -----
    existing_indexes = set()
    if "subscriptions" in existing_tables:
        existing_indexes = {i["name"] for i in inspector.get_indexes("subscriptions")}

    index_defs = [
        ("idx_subscriptions_workspace", ["workspace_id"]),
        ("idx_subscriptions_stripe_customer", ["stripe_customer_id"]),
        ("idx_subscriptions_stripe_subscription", ["stripe_subscription_id"]),
        ("idx_subscriptions_status", ["status"]),
    ]

    for idx_name, cols in index_defs:
        if idx_name not in existing_indexes:
            op.create_index(idx_name, "subscriptions", cols)
            existing_indexes.add(idx_name)
        else:
            print(f"  ⊘ Index '{idx_name}' already exists, skipping...")

    # ----- Seed plans (idempotent) -----
    # Insert Free plan
    op.execute(sa.text("""
        INSERT INTO plans (
            id, name, plan_type, stripe_price_id,
            base_service_count, base_price_cents,
            additional_service_price_cents, rca_session_limit_daily,
            is_active, created_at
        )
        SELECT
            gen_random_uuid()::text, 'Free', 'free', NULL,
            5, 0, 0, 10,
            true, NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM plans WHERE plan_type = 'free'
        )
    """))

    # Insert Pro plan
    op.execute(sa.text("""
        INSERT INTO plans (
            id, name, plan_type, stripe_price_id,
            base_service_count, base_price_cents,
            additional_service_price_cents, rca_session_limit_daily,
            is_active, created_at
        )
        SELECT
            gen_random_uuid()::text, 'Pro', 'pro', NULL,
            5, 3000, 500, 100,
            true, NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM plans WHERE plan_type = 'pro'
        )
    """))

    # ----- Create subscriptions for existing workspaces (only missing ones) -----
    op.execute(sa.text("""
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
        JOIN plans p ON p.plan_type = 'free'
        WHERE NOT EXISTS (
            SELECT 1 FROM subscriptions s WHERE s.workspace_id = w.id
        )
    """))


# ---------- Downgrade ----------

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())

    # ----- Drop subscriptions safely -----
    if "subscriptions" in existing_tables:
        existing_indexes = {i["name"] for i in inspector.get_indexes("subscriptions")}

        for idx in [
            "idx_subscriptions_status",
            "idx_subscriptions_stripe_subscription",
            "idx_subscriptions_stripe_customer",
            "idx_subscriptions_workspace",
        ]:
            if idx in existing_indexes:
                op.drop_index(idx, table_name="subscriptions")

        op.drop_table("subscriptions")
    else:
        print("  ⊘ Table 'subscriptions' does not exist, skipping...")

    # ----- Drop plans -----
    if "plans" in existing_tables:
        op.drop_table("plans")
    else:
        print("  ⊘ Table 'plans' does not exist, skipping...")

    # ----- Drop enums -----
    op.execute(sa.text("DROP TYPE IF EXISTS subscriptionstatus"))
    op.execute(sa.text("DROP TYPE IF EXISTS plantype"))
