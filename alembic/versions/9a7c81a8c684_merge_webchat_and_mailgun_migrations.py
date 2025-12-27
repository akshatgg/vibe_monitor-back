"""Merge webchat and mailgun migrations

Revision ID: 9a7c81a8c684
Revises: c1h2a3t4, d3e4f5a6b7c8
Create Date: 2025-12-27 16:05:01.888637

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "9a7c81a8c684"
down_revision: Union[str, Sequence[str], None] = ("c1h2a3t4", "d3e4f5a6b7c8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
