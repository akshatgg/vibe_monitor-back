"""merge_billing_migrations

Revision ID: 8494f35f5b00
Revises: ae0a9fdcccf0, b1l2l3i4n5g6
Create Date: 2025-12-28 12:45:32.095301

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "8494f35f5b00"
down_revision: Union[str, Sequence[str], None] = ("ae0a9fdcccf0", "b1l2l3i4n5g6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
