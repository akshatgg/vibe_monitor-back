"""merge credential auth and integration fix branches

Revision ID: 2b46743bd682
Revises: eb279001df3c, fix_integration_id
Create Date: 2025-12-19 12:32:21.330236

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "2b46743bd682"
down_revision: Union[str, Sequence[str], None] = ("eb279001df3c", "fix_integration_id")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
