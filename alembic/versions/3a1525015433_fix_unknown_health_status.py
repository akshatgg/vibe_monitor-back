"""fix_unknown_health_status

Revision ID: 3a1525015433
Revises: a1b2c3d4e5f6
Create Date: 2025-12-18 14:17:09.470947

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = '3a1525015433'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Fix health_status for existing integrations.

    The previous migration set health_status='unknown' for backfilled integrations,
    but the worker and capability resolver only accept 'healthy' or NULL.

    Setting to NULL means "not yet verified" - health checks will run on first use.
    """
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE integrations
        SET health_status = NULL, updated_at = NOW()
        WHERE health_status = 'unknown'
    """))


def downgrade() -> None:
    """Revert health_status back to 'unknown' for integrations that were NULL."""
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE integrations
        SET health_status = 'unknown', updated_at = NOW()
        WHERE health_status IS NULL
    """))
