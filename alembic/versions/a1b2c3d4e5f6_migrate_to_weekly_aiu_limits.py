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
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '97d46c4af7dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Migrate to weekly AIU limits."""
    conn = op.get_bind()

    # Step 1: Add new columns
    op.add_column(
        'plans',
        sa.Column('aiu_limit_weekly_base', sa.Integer(), nullable=True)
    )
    op.add_column(
        'plans',
        sa.Column('aiu_limit_weekly_per_service', sa.Integer(), nullable=True)
    )

    # Step 2: Populate new columns based on plan_type

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
    print(f"  Updated {free_count} FREE plans to weekly AIU limits")

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
    print(f"  Updated {pro_count} PRO plans to weekly AIU limits")

    # Step 3: Make new columns non-nullable now that they have values
    op.alter_column('plans', 'aiu_limit_weekly_base', nullable=False)
    op.alter_column('plans', 'aiu_limit_weekly_per_service', nullable=False)

    # Step 4: Clean up old rca_request tracking data
    result = conn.execute(text("""
        DELETE FROM rate_limit_tracking
        WHERE resource_type = 'rca_request'
        RETURNING id
    """))
    deleted_count = len(result.fetchall())
    print(f"  Deleted {deleted_count} old rca_request tracking records")

    # Step 5: Drop old daily limit column
    op.drop_column('plans', 'rca_session_limit_daily')

def downgrade() -> None:
    """Rollback to daily RCA limits.

    WARNING: This will restore schema but CANNOT restore deleted rca_request data.
    The old tracking data was cleaned up during upgrade and cannot be recovered.
    """
    conn = op.get_bind()

    # Step 1: Recreate old column
    op.add_column(
        'plans',
        sa.Column('rca_session_limit_daily', sa.Integer(), nullable=True)
    )

    # Step 2: Restore old values based on plan_type

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
    print(f"  Reverted {free_count} FREE plans to daily limits")

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
    print(f"  Reverted {pro_count} PRO plans to daily limits")

    # Step 3: Make column non-nullable
    op.alter_column('plans', 'rca_session_limit_daily', nullable=False)

    # Step 4: Drop new AIU columns
    op.drop_column('plans', 'aiu_limit_weekly_per_service')
    op.drop_column('plans', 'aiu_limit_weekly_base')

