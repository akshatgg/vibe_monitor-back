"""seed_plans_if_empty

Revision ID: b612ffbe12b8
Revises: a5b6c7d8e9f0
Create Date: 2026-01-30 06:45:40.117044

This migration ensures:
1. Plans table has FREE and PRO plans seeded
2. All existing workspaces have subscriptions (defaults to FREE)
3. Billing structure supports easy plan upgrades and service additions

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b612ffbe12b8'
down_revision: Union[str, Sequence[str], None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed plans table if empty (idempotent)."""

    # Insert Free plan (only if doesn't exist)
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

    # Insert Pro plan (only if doesn't exist)
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

    # Create subscriptions for any workspaces that don't have one (assign FREE plan)
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


def downgrade() -> None:
    """Downgrade schema (no-op since this is data seeding)."""
    # We don't delete plans or subscriptions on downgrade
    # as that could break existing data
    pass