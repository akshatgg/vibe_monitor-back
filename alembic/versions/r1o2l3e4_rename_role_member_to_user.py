"""Rename Role.MEMBER to Role.USER

Revision ID: r1o2l3e4
Revises: w1o2r3k4
Create Date: 2025-12-28

Renames the Role enum value from MEMBER to USER to better reflect
that members of team workspaces are users with different permission levels.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "r1o2l3e4"
down_revision: Union[str, Sequence[str], None] = "w1o2r3k4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename MEMBER to USER in the role enum."""
    # PostgreSQL allows renaming enum values with ALTER TYPE
    # First, add the new value
    op.execute(text("ALTER TYPE role ADD VALUE IF NOT EXISTS 'USER'"))

    # Update all existing MEMBER values to USER
    op.execute(text("UPDATE memberships SET role = 'USER' WHERE role = 'MEMBER'"))

    # Note: PostgreSQL doesn't allow removing enum values directly
    # The old 'MEMBER' value will remain in the enum but won't be used
    # This is a safe approach that maintains backward compatibility


def downgrade() -> None:
    """Rename USER back to MEMBER in the role enum."""
    # Update all USER values back to MEMBER
    op.execute(text("UPDATE memberships SET role = 'MEMBER' WHERE role = 'USER'"))

    # Note: We can't remove the 'USER' value from the enum in PostgreSQL
    # but we've updated all data back to use 'MEMBER'
