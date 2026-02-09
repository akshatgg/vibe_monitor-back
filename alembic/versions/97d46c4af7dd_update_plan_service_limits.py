"""update_plan_service_limits

Update service limits for billing plans:
- Free plan: 5 -> 2 services
- Pro plan: 5 -> 3 base services (+ $5/each additional)
- Recalculate billable_service_count for Pro subscriptions

Revision ID: 97d46c4af7dd
Revises: d8f3a2b5c1e9
Create Date: 2026-02-09 10:03:18.830816

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '97d46c4af7dd'
down_revision: Union[str, Sequence[str], None] = 'd8f3a2b5c1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Update plan service limits and recalculate billable services."""
    conn = op.get_bind()

    print("=" * 70)
    print("🔄 Updating billing plan limits...")
    print("=" * 70)

    # Step 1: Delete excess services for FREE plan users (keep oldest 2 per workspace)
    print("\n🗑️  Checking for excess services in FREE plan workspaces...")

    # Count excess services
    result = conn.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT s.id
            FROM services s
            INNER JOIN subscriptions sub ON s.workspace_id = sub.workspace_id
            INNER JOIN plans p ON sub.plan_id = p.id
            WHERE p.plan_type = 'FREE'
            AND (
                SELECT COUNT(*)
                FROM services s2
                WHERE s2.workspace_id = s.workspace_id
                AND s2.created_at <= s.created_at
            ) > 2
        ) excess
    """))
    excess_count = result.scalar() or 0

    if excess_count > 0:
        # Delete services beyond 2nd oldest per workspace
        conn.execute(text("""
            DELETE FROM services
            WHERE id IN (
                SELECT s.id
                FROM services s
                INNER JOIN subscriptions sub ON s.workspace_id = sub.workspace_id
                INNER JOIN plans p ON sub.plan_id = p.id
                WHERE p.plan_type = 'FREE'
                AND (
                    SELECT COUNT(*)
                    FROM services s2
                    WHERE s2.workspace_id = s.workspace_id
                    AND s2.created_at <= s.created_at
                ) > 2
            )
        """))
        print(f"✅ Deleted {excess_count} excess service(s) - kept 2 oldest per workspace")
    else:
        print("✅ No excess services found (all FREE workspaces have ≤2 services)")

    # Step 2: Update FREE plan: 5 -> 2 services
    print("\n📝 Updating plan limits...")
    conn.execute(text("""
        UPDATE plans
        SET base_service_count = 2,
            updated_at = NOW()
        WHERE plan_type = 'FREE'
    """))
    print("✅ FREE plan: Updated to 2 services")

    # Step 3: Update PRO plan: 5 -> 3 base services
    conn.execute(text("""
        UPDATE plans
        SET base_service_count = 3,
            updated_at = NOW()
        WHERE plan_type = 'PRO'
    """))
    print("✅ PRO plan: Updated to 3 base services")

    # Step 4: Recalculate billable_service_count for PRO subscriptions
    print("\n🔢 Recalculating PRO billing...")
    conn.execute(text("""
        UPDATE subscriptions s
        SET billable_service_count = GREATEST(
            0,
            (
                SELECT COUNT(*)
                FROM services srv
                WHERE srv.workspace_id = s.workspace_id
            ) - 3
        ),
        updated_at = NOW()
        FROM plans p
        WHERE s.plan_id = p.id
        AND p.plan_type = 'PRO'
    """))
    print("✅ PRO subscriptions: Recalculated billable service counts")

    print("=" * 70)
    print("✨ Migration completed!")
    print("=" * 70)


def downgrade() -> None:
    """Revert plan service limits to previous values."""
    conn = op.get_bind()

    print("=" * 70)
    print("⏪ Reverting billing plan limits...")
    print("=" * 70)

    # Revert FREE plan: 2 -> 5 services
    conn.execute(text("""
        UPDATE plans
        SET base_service_count = 5,
            updated_at = NOW()
        WHERE plan_type = 'FREE'
    """))
    print("✅ FREE plan: Reverted to 5 services")

    # Revert PRO plan: 3 -> 5 base services
    conn.execute(text("""
        UPDATE plans
        SET base_service_count = 5,
            updated_at = NOW()
        WHERE plan_type = 'PRO'
    """))
    print("✅ PRO plan: Reverted to 5 base services")

    # Recalculate billable_service_count with old base (5)
    conn.execute(text("""
        UPDATE subscriptions s
        SET billable_service_count = GREATEST(
            0,
            (
                SELECT COUNT(*)
                FROM services srv
                WHERE srv.workspace_id = s.workspace_id
            ) - 5
        ),
        updated_at = NOW()
        FROM plans p
        WHERE s.plan_id = p.id
        AND p.plan_type = 'PRO'
    """))
    print("✅ PRO subscriptions: Recalculated billable service counts (base=5)")

    print("=" * 70)
    print("✨ Downgrade completed!")
    print("=" * 70)
