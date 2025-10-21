"""Add is_active column to github_integrations table

Revision ID: 12e4bbd5974b
Revises: b0f53cfcf12a
Create Date: 2025-10-17 15:03:14.106108

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "12e4bbd5974b"
down_revision: Union[str, Sequence[str], None] = "b0f53cfcf12a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_active column to track GitHub integration suspension status."""
    # Add is_active column with server_default=True for existing rows
    op.add_column(
        "github_integrations",
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )


def downgrade() -> None:
    """Remove is_active column from github_integrations table."""
    op.drop_column("github_integrations", "is_active")
