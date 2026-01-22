"""Add index on github_integrations.installation_id

Revision ID: 716ab90ef94b
Revises: 12e4bbd5974b
Create Date: 2025-10-17 15:34:13.029525

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "716ab90ef94b"
down_revision: Union[str, Sequence[str], None] = "12e4bbd5974b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add index on installation_id for faster webhook lookups."""
    bind = op.get_bind()
    inspector = inspect(bind)

    # Check if index exists
    indexes = [idx["name"] for idx in inspector.get_indexes("github_integrations")]
    if "idx_github_integration_installation" not in indexes:
        op.create_index(
            "idx_github_integration_installation",
            "github_integrations",
            ["installation_id"],
            unique=False,
        )
    else:
        print("  ⊘ Index 'idx_github_integration_installation' already exists, skipping...")


def downgrade() -> None:
    """Remove index on installation_id."""
    op.drop_index(
        "idx_github_integration_installation", table_name="github_integrations"
    )
