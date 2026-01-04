"""drop_auto_discovery_enabled_column

Revision ID: b413091d1260
Revises: f8f458133678
Create Date: 2026-01-04 11:33:11.171425

Removes the auto_discovery_enabled column from environments table.
This feature was never implemented and is being removed to simplify the schema.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b413091d1260"
down_revision: Union[str, Sequence[str], None] = "f8f458133678"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop auto_discovery_enabled column from environments table."""
    op.drop_column("environments", "auto_discovery_enabled")


def downgrade() -> None:
    """Re-add auto_discovery_enabled column to environments table."""
    op.add_column(
        "environments",
        sa.Column(
            "auto_discovery_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
