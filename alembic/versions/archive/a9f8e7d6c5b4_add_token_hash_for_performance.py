"""Add token_hash column for O(1) token verification performance

Revision ID: a9f8e7d6c5b4
Revises: 2b46743bd682
Create Date: 2025-12-19 14:00:00.000000

This migration adds a token_hash column to email_verifications table
to optimize token lookup from O(n) to O(1), preventing DOS attacks.
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a9f8e7d6c5b4"
down_revision: Union[str, Sequence[str], None] = "2b46743bd682"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add token_hash column and index for fast token lookups."""
    from sqlalchemy import inspect
    from alembic import context

    conn = context.get_bind()
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("email_verifications")]

    # Add token_hash column if it doesn't exist
    if "token_hash" not in columns:
        op.add_column(
            "email_verifications",
            sa.Column("token_hash", sa.String(length=64), nullable=True),
        )

        # Create index on token_hash for O(1) lookups
        op.create_index(
            "idx_email_verification_token_hash",
            "email_verifications",
            ["token_hash"],
            unique=False,
        )

        print("✓ Added token_hash column with index for performance optimization")


def downgrade() -> None:
    """Remove token_hash column and index."""
    # Drop index
    op.drop_index("idx_email_verification_token_hash", table_name="email_verifications")

    # Drop column
    op.drop_column("email_verifications", "token_hash")
