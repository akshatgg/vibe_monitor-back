"""migrate_to_weekly_aiu_limits

Migrate from daily RCA request limits to weekly AIU (AI Unit) limits:
- Add aiu_limit_weekly_base column (100K for FREE, 3M for PRO)
- Add aiu_limit_weekly_per_service column (0 for FREE, 500K for PRO)
- Remove rca_session_limit_daily column (old daily limit)
- Clean up old rca_request tracking data (deprecated, replaced by aiu_usage)

New limit structure:
- FREE: 100K AIU/week (fixed, no additional service scaling)
- PRO: 3M AIU base + 500K per extra service (scalable)
- To get more AIU with extra services, users must upgrade to PRO

Tracking system:
- OLD: rca_request (daily message counts) - REMOVED
- NEW: aiu_usage (weekly token counts) - Active

Revision ID: a1b2c3d4e5f6
Revises: 97d46c4af7dd
Create Date: 2026-02-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '97d46c4af7dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    """Migrate to weekly AIU limits."""
    conn = op.get_bind()

    print("=" * 80)
    print("🔄 Migrating to Weekly AIU Limits...")
    print("=" * 80)

    # Step 1: Add new columns with validation
    print("\n📝 Checking and adding new AIU limit columns...")

    if not column_exists('plans', 'aiu_limit_weekly_base'):
        op.add_column(
            'plans',
            sa.Column('aiu_limit_weekly_base', sa.Integer(), nullable=True)
        )
        print("✅ Added column: aiu_limit_weekly_base")
    else:
        print("⚠️  Column already exists: aiu_limit_weekly_base (skipping)")

    if not column_exists('plans', 'aiu_limit_weekly_per_service'):
        op.add_column(
            'plans',
            sa.Column('aiu_limit_weekly_per_service', sa.Integer(), nullable=True)
        )
        print("✅ Added column: aiu_limit_weekly_per_service")
    else:
        print("⚠️  Column already exists: aiu_limit_weekly_per_service (skipping)")

    # Step 2: Populate new columns based on plan_type
    print("\n📊 Setting AIU limits for each plan...")

    # FREE plan: 100K AIU/week (no additional service scaling - must upgrade to PRO)
    # Also fix: additional_service_price_cents should be 0 (cannot add services on FREE)
    result = conn.execute(text("""
        UPDATE plans
        SET aiu_limit_weekly_base = 100000,
            aiu_limit_weekly_per_service = 0,
            additional_service_price_cents = 0,
            updated_at = NOW()
        WHERE plan_type = 'FREE'
        RETURNING id
    """))
    free_count = len(result.fetchall())
    print(f"✅ FREE plan: 100K AIU/week (fixed limit, $0 per extra service) - Updated {free_count} plan(s)")

    # PRO plan: 3M AIU base + 500K per extra service
    # Ensure: additional_service_price_cents is 500 ($5 per service)
    result = conn.execute(text("""
        UPDATE plans
        SET aiu_limit_weekly_base = 3000000,
            aiu_limit_weekly_per_service = 500000,
            additional_service_price_cents = 500,
            updated_at = NOW()
        WHERE plan_type = 'PRO'
        RETURNING id
    """))
    pro_count = len(result.fetchall())
    print(f"✅ PRO plan: 3M AIU base + 500K per service ($5 each) - Updated {pro_count} plan(s)")

    # Step 3: Make new columns non-nullable now that they have values
    print("\n🔒 Setting NOT NULL constraints...")
    if column_exists('plans', 'aiu_limit_weekly_base'):
        op.alter_column('plans', 'aiu_limit_weekly_base', nullable=False)
        print("✅ Constraint applied: aiu_limit_weekly_base NOT NULL")

    if column_exists('plans', 'aiu_limit_weekly_per_service'):
        op.alter_column('plans', 'aiu_limit_weekly_per_service', nullable=False)
        print("✅ Constraint applied: aiu_limit_weekly_per_service NOT NULL")

    # Step 4: Clean up old rca_request tracking data
    print("\n🗑️  Cleaning up deprecated rca_request tracking data...")
    result = conn.execute(text("""
        DELETE FROM rate_limit_tracking
        WHERE resource_type = 'rca_request'
        RETURNING id
    """))
    deleted_count = len(result.fetchall())
    print(f"✅ Deleted {deleted_count} old rca_request record(s)")
    print("   (Deprecated daily message tracking replaced by weekly token tracking)")

    # Step 5: Drop old daily limit column with validation
    print("\n🗑️  Removing old daily RCA limit column...")
    if column_exists('plans', 'rca_session_limit_daily'):
        op.drop_column('plans', 'rca_session_limit_daily')
        print("✅ Old column removed: rca_session_limit_daily")
    else:
        print("⚠️  Column does not exist: rca_session_limit_daily (already removed)")

    print("\n" + "=" * 80)
    print("✨ Migration to Weekly AIU Limits completed!")
    print("=" * 80)
    print("\n📋 Summary:")
    print("   • FREE: 100K AIU/week (fixed, no scaling)")
    print("   • PRO:  3M AIU base + 500K per extra service (scalable)")
    print("   • Want more AIU? Upgrade to PRO!")
    print("   • Old rca_request data cleaned up (now using aiu_usage)")
    print("=" * 80)


def downgrade() -> None:
    """Rollback to daily RCA limits.

    WARNING: This will restore schema but CANNOT restore deleted rca_request data.
    The old tracking data was cleaned up during upgrade and cannot be recovered.
    """
    conn = op.get_bind()

    print("=" * 80)
    print("⏪ Rolling back to Daily RCA Limits...")
    print("=" * 80)
    print("\n⚠️  WARNING: Old rca_request tracking data cannot be restored!")
    print("   (Data was deleted during upgrade - schema will be restored only)\n")

    # Step 1: Recreate old column with validation
    print("\n📝 Checking and recreating daily RCA limit column...")
    if not column_exists('plans', 'rca_session_limit_daily'):
        op.add_column(
            'plans',
            sa.Column('rca_session_limit_daily', sa.Integer(), nullable=True)
        )
        print("✅ Added column: rca_session_limit_daily")
    else:
        print("⚠️  Column already exists: rca_session_limit_daily (skipping)")

    # Step 2: Restore old values based on plan_type
    print("\n📊 Restoring old daily limits...")

    # FREE plan: 10 requests/day
    # Note: Restoring old (incorrect) additional_service_price_cents = 500
    result = conn.execute(text("""
        UPDATE plans
        SET rca_session_limit_daily = 10,
            additional_service_price_cents = 500,
            updated_at = NOW()
        WHERE plan_type = 'FREE'
        RETURNING id
    """))
    free_count = len(result.fetchall())
    print(f"✅ FREE plan: 10 requests/day (restored old state) - Updated {free_count} plan(s)")

    # PRO plan: 100 requests/day
    result = conn.execute(text("""
        UPDATE plans
        SET rca_session_limit_daily = 100,
            additional_service_price_cents = 500,
            updated_at = NOW()
        WHERE plan_type = 'PRO'
        RETURNING id
    """))
    pro_count = len(result.fetchall())
    print(f"✅ PRO plan: 100 requests/day (restored old state) - Updated {pro_count} plan(s)")

    # Step 3: Make column non-nullable
    print("\n🔒 Setting NOT NULL constraint...")
    if column_exists('plans', 'rca_session_limit_daily'):
        op.alter_column('plans', 'rca_session_limit_daily', nullable=False)
        print("✅ Constraint applied: rca_session_limit_daily NOT NULL")

    # Step 4: Drop new AIU columns with validation
    print("\n🗑️  Removing AIU limit columns...")
    if column_exists('plans', 'aiu_limit_weekly_per_service'):
        op.drop_column('plans', 'aiu_limit_weekly_per_service')
        print("✅ Removed column: aiu_limit_weekly_per_service")
    else:
        print("⚠️  Column does not exist: aiu_limit_weekly_per_service (already removed)")

    if column_exists('plans', 'aiu_limit_weekly_base'):
        op.drop_column('plans', 'aiu_limit_weekly_base')
        print("✅ Removed column: aiu_limit_weekly_base")
    else:
        print("⚠️  Column does not exist: aiu_limit_weekly_base (already removed)")

    print("\n" + "=" * 80)
    print("✨ Rollback to Daily RCA Limits completed!")
    print("=" * 80)
