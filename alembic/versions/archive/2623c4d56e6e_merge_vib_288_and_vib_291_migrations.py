"""merge VIB-288 and VIB-291 migrations

Revision ID: 2623c4d56e6e
Revises: 25c346804ff3, 8494f35f5b00
Create Date: 2025-12-28 13:23:50.038664

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "2623c4d56e6e"
down_revision: Union[str, Sequence[str], None] = ("25c346804ff3", "8494f35f5b00")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
