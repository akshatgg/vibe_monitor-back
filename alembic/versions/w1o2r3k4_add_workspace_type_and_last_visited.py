"""Add workspace type enum and last_visited_workspace_id

Revision ID: w1o2r3k4
Revises: s1a2c3k4
Create Date: 2025-12-28

Adds:
- WorkspaceType enum (personal, team) to workspaces table
- last_visited_workspace_id column to users table
- Data migration to classify existing workspaces as personal or team
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "w1o2r3k4"
down_revision: Union[str, Sequence[str], None] = "s1a2c3k4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add workspace type and last_visited_workspace_id."""
    # Create the workspacetype enum
    workspacetype_enum = sa.Enum("personal", "team", name="workspacetype")
    workspacetype_enum.create(op.get_bind(), checkfirst=True)

    # Add type column to workspaces with default 'team'
    inspect = sa.inspect(op.get_bind())
    columns = [col["name"] for col in inspect.get_columns("workspaces")]

    if "type" not in columns:
        op.add_column(
            "workspaces",
            sa.Column(
                "type",
                sa.Enum("personal", "team", name="workspacetype", create_type=False),
                nullable=False,
                server_default="team",
            ),
        )
    else:
        print("Column 'type' already exists in 'workspaces' table. Skipping addition.")

    # Add last_visited_workspace_id to users

    if "last_visited_workspace_id" not in [
        col["name"] for col in inspect.get_columns("users")
    ]:
        op.add_column(
            "users",
            sa.Column("last_visited_workspace_id", sa.String(), nullable=True),
        )
    else:
        print(
            "Column 'last_visited_workspace_id' already exists in 'users' table. Skipping addition."
        )

    # Add foreign key constraint for last_visited_workspace_id
    op.create_foreign_key(
        "fk_users_last_visited_workspace",
        "users",
        "workspaces",
        ["last_visited_workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Data migration: Classify existing personal workspaces
    # Personal workspaces are identified by:
    # - visible_to_org = False
    # - Has exactly one member who is the owner
    # Note: At this point in the migration chain, the Role enum has uppercase values (OWNER, MEMBER)
    op.execute(
        text(
            """
            UPDATE workspaces w
            SET type = 'personal'
            WHERE w.visible_to_org = FALSE
              AND (
                SELECT COUNT(*) FROM memberships m WHERE m.workspace_id = w.id
              ) = 1
              AND EXISTS (
                SELECT 1 FROM memberships m
                WHERE m.workspace_id = w.id AND m.role = 'OWNER'
              )
            """
        )
    )


def downgrade() -> None:
    """Remove workspace type and last_visited_workspace_id."""
    # Drop foreign key constraint
    op.drop_constraint("fk_users_last_visited_workspace", "users", type_="foreignkey")

    # Drop last_visited_workspace_id column
    op.drop_column("users", "last_visited_workspace_id")

    # Drop type column from workspaces
    op.drop_column("workspaces", "type")

    # Drop the workspacetype enum
    op.execute(text("DROP TYPE IF EXISTS workspacetype"))
