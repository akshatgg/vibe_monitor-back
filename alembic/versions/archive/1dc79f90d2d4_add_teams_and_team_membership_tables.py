"""add teams and team_membership tables

Revision ID: 1dc79f90d2d4
Revises: b2c3d4e5f6g7
Create Date: 2026-01-27 06:14:07.354695

Creates the teams and team_membership tables for organizing users
within workspaces into teams. Also adds team_id column to services table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '1dc79f90d2d4'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6g7'
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
    if not table_exists(table_name):
        return False
    indexes = inspector.get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if not table_exists(table_name):
        return False
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def constraint_exists(constraint_name: str, table_name: str) -> bool:
    """Check if a constraint exists on a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if not table_exists(table_name):
        return False
    # Check foreign key constraints
    foreign_keys = inspector.get_foreign_keys(table_name)
    return any(fk["name"] == constraint_name for fk in foreign_keys)


def upgrade() -> None:
    """Create teams and team_membership tables."""

    # Create teams table if it doesn't exist
    if not table_exists("teams"):
        op.create_table(
            "teams",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("geography", sa.String(255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["workspace_id"],
                ["workspaces.id"],
                name="fk_teams_workspace",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        print("  ✓ Created table 'teams'")
    else:
        print("  ⊘ Table 'teams' already exists, skipping...")

    # Create indexes for teams table
    if not index_exists("uq_team_workspace_name", "teams"):
        op.create_index(
            "uq_team_workspace_name",
            "teams",
            ["workspace_id", "name"],
            unique=True,
        )
        print("  ✓ Created unique index 'uq_team_workspace_name'")
    else:
        print("  ⊘ Index 'uq_team_workspace_name' already exists, skipping...")

    if not index_exists("idx_teams_workspace", "teams"):
        op.create_index(
            "idx_teams_workspace",
            "teams",
            ["workspace_id"],
        )
        print("  ✓ Created index 'idx_teams_workspace'")
    else:
        print("  ⊘ Index 'idx_teams_workspace' already exists, skipping...")

    if not index_exists("idx_teams_name", "teams"):
        op.create_index(
            "idx_teams_name",
            "teams",
            ["name"],
        )
        print("  ✓ Created index 'idx_teams_name'")
    else:
        print("  ⊘ Index 'idx_teams_name' already exists, skipping...")

    # Create team_membership table if it doesn't exist
    if not table_exists("team_membership"):
        op.create_table(
            "team_membership",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("team_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["team_id"],
                ["teams.id"],
                name="fk_team_membership_team",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_team_membership_user",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        print("  ✓ Created table 'team_membership'")
    else:
        print("  ⊘ Table 'team_membership' already exists, skipping...")

    # Create indexes for team_membership table
    if not index_exists("uq_team_membership", "team_membership"):
        op.create_index(
            "uq_team_membership",
            "team_membership",
            ["team_id", "user_id"],
            unique=True,
        )
        print("  ✓ Created unique index 'uq_team_membership'")
    else:
        print("  ⊘ Index 'uq_team_membership' already exists, skipping...")

    if not index_exists("idx_team_membership_team", "team_membership"):
        op.create_index(
            "idx_team_membership_team",
            "team_membership",
            ["team_id"],
        )
        print("  ✓ Created index 'idx_team_membership_team'")
    else:
        print("  ⊘ Index 'idx_team_membership_team' already exists, skipping...")

    if not index_exists("idx_team_membership_user", "team_membership"):
        op.create_index(
            "idx_team_membership_user",
            "team_membership",
            ["user_id"],
        )
        print("  ✓ Created index 'idx_team_membership_user'")
    else:
        print("  ⊘ Index 'idx_team_membership_user' already exists, skipping...")

    # Add team_id column to services table
    if table_exists("services"):
        if not column_exists("services", "team_id"):
            op.add_column(
                "services",
                sa.Column("team_id", sa.String(), nullable=True),
            )
            print("  ✓ Added column 'team_id' to services table")

            # Add foreign key constraint
            op.create_foreign_key(
                "fk_services_team",
                "services",
                "teams",
                ["team_id"],
                ["id"],
                ondelete="SET NULL",
            )
            print("  ✓ Created foreign key 'fk_services_team'")
        else:
            print("  ⊘ Column 'team_id' already exists in services table, skipping...")

        # Create index on team_id
        if not index_exists("idx_services_team", "services"):
            op.create_index(
                "idx_services_team",
                "services",
                ["team_id"],
            )
            print("  ✓ Created index 'idx_services_team'")
        else:
            print("  ⊘ Index 'idx_services_team' already exists, skipping...")
    else:
        print("  ⊘ Table 'services' does not exist, skipping team_id addition...")


def downgrade() -> None:
    """Drop teams and team_membership tables and remove team_id from services."""

    # Remove team_id from services table first (before dropping teams table)
    if table_exists("services") and column_exists("services", "team_id"):
        # Drop index first
        if index_exists("idx_services_team", "services"):
            op.drop_index("idx_services_team", table_name="services")
            print("  ✓ Dropped index 'idx_services_team'")
        else:
            print("  ⊘ Index 'idx_services_team' does not exist, skipping...")

        # Drop foreign key constraint
        if constraint_exists("fk_services_team", "services"):
            op.drop_constraint("fk_services_team", "services", type_="foreignkey")
            print("  ✓ Dropped foreign key 'fk_services_team'")
        else:
            print("  ⊘ Foreign key 'fk_services_team' does not exist, skipping...")

        # Drop column
        op.drop_column("services", "team_id")
        print("  ✓ Dropped column 'team_id' from services table")
    else:
        print("  ⊘ Column 'team_id' does not exist in services table, skipping...")

    # Drop team_membership table (child table)
    if table_exists("team_membership"):
        if index_exists("idx_team_membership_user", "team_membership"):
            op.drop_index("idx_team_membership_user", table_name="team_membership")
        if index_exists("idx_team_membership_team", "team_membership"):
            op.drop_index("idx_team_membership_team", table_name="team_membership")
        if index_exists("uq_team_membership", "team_membership"):
            op.drop_index("uq_team_membership", table_name="team_membership")
        op.drop_table("team_membership")
        print("  ✓ Dropped table 'team_membership'")
    else:
        print("  ⊘ Table 'team_membership' does not exist, skipping...")

    # Drop teams table
    if table_exists("teams"):
        if index_exists("idx_teams_name", "teams"):
            op.drop_index("idx_teams_name", table_name="teams")
        if index_exists("idx_teams_workspace", "teams"):
            op.drop_index("idx_teams_workspace", table_name="teams")
        if index_exists("uq_team_workspace_name", "teams"):
            op.drop_index("uq_team_workspace_name", table_name="teams")
        op.drop_table("teams")
        print("  ✓ Dropped table 'teams'")
    else:
        print("  ⊘ Table 'teams' does not exist, skipping...")
