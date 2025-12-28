"""merge_services_migration

Revision ID: ae0a9fdcccf0
Revises: i1n2v3t4, s3rv1c3s
Create Date: 2025-12-28 12:33:34.272721

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "ae0a9fdcccf0"
down_revision: Union[str, Sequence[str], None] = ("i1n2v3t4", "s3rv1c3s")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
