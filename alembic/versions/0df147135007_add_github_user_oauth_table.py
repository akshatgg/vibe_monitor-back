"""Add github_user_oauth table

Revision ID: 0df147135007
Revises: b413091d1260
Create Date: 2026-01-04 17:56:22.783887

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0df147135007"
down_revision: Union[str, Sequence[str], None] = "b413091d1260"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create github_user_oauth table for per-user OAuth tokens."""
    op.create_table(
        "github_user_oauth",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("github_user_id", sa.String(), nullable=False),
        sa.Column("github_username", sa.String(), nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("scopes", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_github_user_oauth_user", "github_user_oauth", ["user_id"], unique=True
    )


def downgrade() -> None:
    """Drop github_user_oauth table."""
    op.drop_index("idx_github_user_oauth_user", table_name="github_user_oauth")
    op.drop_table("github_user_oauth")
