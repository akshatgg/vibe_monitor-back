"""Add environments tables

Revision ID: e1n2v3s4
Revises: s1a2c3k4
Create Date: 2025-12-28

Creates the environments and environment_repositories tables for managing
deployment environment configurations within workspaces.
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1n2v3s4"
down_revision: Union[str, Sequence[str], None] = "s1a2c3k4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def index_exists(index_name: str, table_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def constraint_exists(constraint_name: str, table_name: str) -> bool:
    """Check if a unique constraint exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    constraints = inspector.get_unique_constraints(table_name)
    return any(c["name"] == constraint_name for c in constraints)


def upgrade() -> None:
    """Create environments and environment_repositories tables."""

    # Create environments table if it doesn't exist
    if not table_exists("environments"):
        op.create_table(
            "environments",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column(
                "is_default", sa.Boolean(), nullable=False, server_default="false"
            ),
            sa.Column(
                "auto_discovery_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id"],
                ["workspaces.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "workspace_id", "name", name="uq_environment_workspace_name"
            ),
        )

        # Create index on workspace_id
        op.create_index(
            "ix_environments_workspace_id",
            "environments",
            ["workspace_id"],
            unique=False,
        )

    # Create environment_repositories table if it doesn't exist
    if not table_exists("environment_repositories"):
        op.create_table(
            "environment_repositories",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("environment_id", sa.String(), nullable=False),
            sa.Column("repo_full_name", sa.String(255), nullable=False),
            sa.Column("branch_name", sa.String(255), nullable=True),
            sa.Column(
                "is_enabled", sa.Boolean(), nullable=False, server_default="false"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(
                ["environment_id"],
                ["environments.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("environment_id", "repo_full_name", name="uq_env_repo"),
        )

        # Create index on environment_id
        op.create_index(
            "ix_environment_repositories_environment_id",
            "environment_repositories",
            ["environment_id"],
            unique=False,
        )


def downgrade() -> None:
    """Drop environments and environment_repositories tables."""
    # Drop environment_repositories first (child table)
    if table_exists("environment_repositories"):
        op.drop_index(
            "ix_environment_repositories_environment_id",
            table_name="environment_repositories",
        )
        op.drop_table("environment_repositories")

    # Drop environments table
    if table_exists("environments"):
        op.drop_index("ix_environments_workspace_id", table_name="environments")
        op.drop_table("environments")
