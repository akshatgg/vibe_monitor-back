"""Add workspace_invitations table

Revision ID: i1n2v3t4
Revises: r1o2l3e4
Create Date: 2025-12-28

Creates the workspace_invitations table to support inviting users
to team workspaces. Includes InvitationStatus enum and proper indexes.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ENUM


# revision identifiers, used by Alembic.
revision: str = "i1n2v3t4"
down_revision: Union[str, Sequence[str], None] = "r1o2l3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create workspace_invitations table."""
    inspector = sa.inspect(op.get_bind())
    table_name = "workspace_invitations"

    # Fetch existing schema once
    existing_tables = set(inspector.get_table_names())
    existing_indexes = {i["name"] for i in inspector.get_indexes(table_name)} if table_name in existing_tables else set()

    # Create the invitationstatus enum (idempotent)
    op.execute(
        text(
            """
            DO $$ BEGIN
                CREATE TYPE invitationstatus AS ENUM ('pending', 'accepted', 'declined', 'expired');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
            """
        )
    )

    # Create workspace_invitations table if it doesn't exist
    if table_name not in existing_tables:
        op.create_table(
            table_name,
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("inviter_id", sa.String(), nullable=False),
            sa.Column("invitee_email", sa.String(), nullable=False),
            sa.Column("invitee_id", sa.String(), nullable=True),
            sa.Column(
                "role",
                ENUM("OWNER", "MEMBER", name="role", create_type=False),
                nullable=False,
                server_default="MEMBER",
            ),
            sa.Column(
                "status",
                ENUM(
                    "pending",
                    "accepted",
                    "declined",
                    "expired",
                    name="invitationstatus",
                    create_type=False,
                ),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["workspace_id"],
                ["workspaces.id"],
                name="fk_invitation_workspace",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["inviter_id"],
                ["users.id"],
                name="fk_invitation_inviter",
            ),
            sa.ForeignKeyConstraint(
                ["invitee_id"],
                ["users.id"],
                name="fk_invitation_invitee",
            ),
            sa.UniqueConstraint("token", name="uq_invitation_token"),
        )
        # Refresh indexes after table creation
        existing_indexes = set()
    else:
        print(f"  ⊘ Table '{table_name}' already exists, skipping...")

    # Create indexes if they don't exist
    indexes_to_create = [
        ("idx_invitation_workspace", ["workspace_id"]),
        ("idx_invitation_invitee_email", ["invitee_email"]),
        ("idx_invitation_token", ["token"]),
        ("idx_invitation_status", ["status"]),
        ("idx_invitation_expires_at", ["expires_at"]),
    ]

    for idx_name, columns in indexes_to_create:
        if idx_name not in existing_indexes:
            op.create_index(idx_name, table_name, columns)
            existing_indexes.add(idx_name)
        else:
            print(f"  ⊘ Index '{idx_name}' already exists, skipping...")


def downgrade() -> None:
    """Drop workspace_invitations table."""
    inspector = sa.inspect(op.get_bind())
    table_name = "workspace_invitations"

    existing_tables = set(inspector.get_table_names())
    existing_indexes = {i["name"] for i in inspector.get_indexes(table_name)} if table_name in existing_tables else set()

    # Drop indexes if they exist
    indexes_to_drop = [
        "idx_invitation_expires_at",
        "idx_invitation_status",
        "idx_invitation_token",
        "idx_invitation_invitee_email",
        "idx_invitation_workspace",
    ]

    for idx_name in indexes_to_drop:
        if idx_name in existing_indexes:
            op.drop_index(idx_name, table_name=table_name)

    # Drop table if it exists
    if table_name in existing_tables:
        op.drop_table(table_name)
    else:
        print(f"  ⊘ Table '{table_name}' does not exist, skipping...")

    # Drop enum (using IF EXISTS for safety)
    op.execute(text("DROP TYPE IF EXISTS invitationstatus"))
