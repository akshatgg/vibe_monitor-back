"""Rename Role.MEMBER to Role.USER

Revision ID: r1o2l3e4
Revises: w1o2r3k4
Create Date: 2025-12-28

Renames the Role enum value from MEMBER to USER to better reflect
that members of team workspaces are users with different permission levels.
"""

from typing import Sequence, Union

from alembic import op  # noqa: F401 - required for Alembic


# revision identifiers, used by Alembic.
revision: str = "r1o2l3e4"
down_revision: Union[str, Sequence[str], None] = "w1o2r3k4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: This migration is superseded by f1x3num5_fix_enum_case_mismatch.py

    Originally tried to ADD VALUE 'USER' + UPDATE, but this fails in PostgreSQL
    because new enum values can't be used in the same transaction.

    The f1x3num5 migration properly handles this using RENAME VALUE 'MEMBER' TO 'user',
    which works in a single transaction and also converts to lowercase.
    """
    pass


def downgrade() -> None:
    """No-op: See upgrade() for explanation."""
    pass
