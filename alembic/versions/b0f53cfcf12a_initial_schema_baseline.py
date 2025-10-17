"""Initial schema baseline

Revision ID: b0f53cfcf12a
Revises:
Create Date: 2025-10-17 15:01:57.512019

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "b0f53cfcf12a"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
