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
    inspector = sa.inspect(op.get_bind())
    table_name = "github_user_oauth"

    existing_tables = set(inspector.get_table_names())
    existing_indexes = {i["name"] for i in inspector.get_indexes(table_name)} if table_name in existing_tables else set()

    # Create table if it doesn't exist
    if table_name not in existing_tables:
        op.create_table(
            table_name,
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
        existing_indexes = set()
    else:
        print(f"  ⊘ Table '{table_name}' already exists, skipping...")

    # Create index if it doesn't exist
    idx_name = "idx_github_user_oauth_user"
    if idx_name not in existing_indexes:
        op.create_index(idx_name, table_name, ["user_id"], unique=True)
    else:
        print(f"  ⊘ Index '{idx_name}' already exists, skipping...")


def downgrade() -> None:
    """Drop github_user_oauth table."""
    inspector = sa.inspect(op.get_bind())
    table_name = "github_user_oauth"

    existing_tables = set(inspector.get_table_names())

    # Drop index if it exists
    if table_name in existing_tables:
        existing_indexes = {i["name"] for i in inspector.get_indexes(table_name)}
        idx_name = "idx_github_user_oauth_user"
        if idx_name in existing_indexes:
            op.drop_index(idx_name, table_name=table_name)

    # Drop table if it exists
    if table_name in existing_tables:
        op.drop_table(table_name)
    else:
        print(f"  ⊘ Table '{table_name}' does not exist, skipping...")
