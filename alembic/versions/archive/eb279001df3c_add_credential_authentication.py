"""Add credential authentication support

Revision ID: eb279001df3c
Revises: f1a2b3c4d5e6
Create Date: 2025-12-09 22:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "eb279001df3c"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add credential authentication fields and email verification table."""
    # Add new columns to users table (if they don't exist)
    from sqlalchemy import inspect
    from alembic import context

    conn = context.get_bind()
    inspector = inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("users")]

    if "password_hash" not in columns:
        op.add_column("users", sa.Column("password_hash", sa.String(), nullable=True))

    if "is_verified" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "is_verified", sa.Boolean(), nullable=False, server_default="false"
            ),
        )
        # Update all existing users to be verified
        # All current users signed up via Google OAuth, so they should be auto-verified
        op.execute("UPDATE users SET is_verified = true")

    # Create email_verifications table (if it doesn't exist)
    tables = inspector.get_table_names()

    if "email_verifications" not in tables:
        op.create_table(
            "email_verifications",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("token", sa.String(), nullable=False),
            sa.Column("token_type", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes
        op.create_index(
            "idx_email_verification_token",
            "email_verifications",
            ["token"],
            unique=True,
        )
        op.create_index(
            "idx_email_verification_user",
            "email_verifications",
            ["user_id"],
            unique=False,
        )
        op.create_index(
            "idx_email_verification_expires",
            "email_verifications",
            ["expires_at"],
            unique=False,
        )


def downgrade() -> None:
    """Remove credential authentication fields and email verification table."""
    # Drop indexes
    op.drop_index("idx_email_verification_expires", table_name="email_verifications")
    op.drop_index("idx_email_verification_user", table_name="email_verifications")
    op.drop_index("idx_email_verification_token", table_name="email_verifications")

    # Drop table
    op.drop_table("email_verifications")

    # Drop columns from users
    op.drop_column("users", "is_verified")
    op.drop_column("users", "password_hash")
