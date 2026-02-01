"""add_is_onboarded_to_users

Revision ID: b2c3d4e5f6g7
Revises: ecd445ee1dac
Create Date: 2026-01-21 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'ecd445ee1dac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_onboarded column to users table with backfill and index."""
    inspector = sa.inspect(op.get_bind())
    user_columns = [col["name"] for col in inspector.get_columns("users")]

    if "is_onboarded" not in user_columns:
        print("  → Adding 'is_onboarded' column to users table...")
        op.add_column(
            "users",
            sa.Column(
                "is_onboarded",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

        # Backfill: Mark users as onboarded if they own a workspace with GitHub integration
        print("  → Backfilling is_onboarded for existing users with GitHub integrations...")
        op.execute(text("""
            UPDATE users
            SET is_onboarded = true
            WHERE id IN (
                SELECT DISTINCT m.user_id
                FROM memberships m
                JOIN github_integrations gi ON m.workspace_id = gi.workspace_id
                WHERE m.role = 'owner'
            )
        """))

        # Add index for faster queries on is_onboarded
        print("  → Creating index on users.is_onboarded...")
        op.create_index('idx_users_is_onboarded', 'users', ['is_onboarded'])
    else:
        print("  ⊘ Column 'is_onboarded' already exists in 'users' table, skipping...")


def downgrade() -> None:
    """Remove is_onboarded column and index from users table."""
    inspector = sa.inspect(op.get_bind())
    user_columns = [col["name"] for col in inspector.get_columns("users")]

    if "is_onboarded" in user_columns:
        # Drop index first
        existing_indexes = {i["name"] for i in inspector.get_indexes("users")}
        if "idx_users_is_onboarded" in existing_indexes:
            print("  → Dropping index 'idx_users_is_onboarded'...")
            op.drop_index('idx_users_is_onboarded', table_name='users')

        print("  → Dropping 'is_onboarded' column from users table...")
        op.drop_column("users", "is_onboarded")
    else:
        print("  ⊘ Column 'is_onboarded' does not exist in 'users' table, skipping...")
