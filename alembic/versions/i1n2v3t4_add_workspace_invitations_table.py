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


# revision identifiers, used by Alembic.
revision: str = "i1n2v3t4"
down_revision: Union[str, Sequence[str], None] = "r1o2l3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create workspace_invitations table."""
    # Create the invitationstatus enum
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

    # Create workspace_invitations table
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("inviter_id", sa.String(), nullable=False),
        sa.Column("invitee_email", sa.String(), nullable=False),
        sa.Column("invitee_id", sa.String(), nullable=True),
        sa.Column(
            "role",
            sa.Enum("OWNER", "MEMBER", name="role", create_type=False),
            nullable=False,
            server_default="MEMBER",
        ),
        sa.Column(
            "status",
            sa.Enum(
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

    # Create indexes for query performance
    op.create_index(
        "idx_invitation_workspace",
        "workspace_invitations",
        ["workspace_id"],
    )
    op.create_index(
        "idx_invitation_invitee_email",
        "workspace_invitations",
        ["invitee_email"],
    )
    op.create_index(
        "idx_invitation_token",
        "workspace_invitations",
        ["token"],
    )
    op.create_index(
        "idx_invitation_status",
        "workspace_invitations",
        ["status"],
    )
    op.create_index(
        "idx_invitation_expires_at",
        "workspace_invitations",
        ["expires_at"],
    )


def downgrade() -> None:
    """Drop workspace_invitations table."""
    # Drop indexes
    op.drop_index("idx_invitation_expires_at", table_name="workspace_invitations")
    op.drop_index("idx_invitation_status", table_name="workspace_invitations")
    op.drop_index("idx_invitation_token", table_name="workspace_invitations")
    op.drop_index("idx_invitation_invitee_email", table_name="workspace_invitations")
    op.drop_index("idx_invitation_workspace", table_name="workspace_invitations")

    # Drop table
    op.drop_table("workspace_invitations")

    # Drop enum
    op.execute(text("DROP TYPE IF EXISTS invitationstatus"))
