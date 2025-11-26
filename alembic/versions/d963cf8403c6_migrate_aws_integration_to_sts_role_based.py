"""Migrate AWS integration to STS role-based authentication

Revision ID: d963cf8403c6
Revises: iqx5rixmd6xw
Create Date: 2025-10-30 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d963cf8403c6"
down_revision: Union[str, Sequence[str], None] = "iqx5rixmd6xw"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to use STS role-based authentication."""
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if table exists
    if "aws_integrations" not in inspector.get_table_names():
        # Table doesn't exist, skip migration
        return

    columns = {col["name"] for col in inspector.get_columns("aws_integrations")}

    # Add new columns for role-based authentication (only if they don't exist)
    if "role_arn" not in columns:
        op.add_column(
            "aws_integrations", sa.Column("role_arn", sa.String(), nullable=True)
        )
    if "external_id" not in columns:
        op.add_column(
            "aws_integrations", sa.Column("external_id", sa.String(), nullable=True)
        )
    if "session_token" not in columns:
        op.add_column(
            "aws_integrations", sa.Column("session_token", sa.String(), nullable=True)
        )
    if "credentials_expiration" not in columns:
        op.add_column(
            "aws_integrations",
            sa.Column(
                "credentials_expiration", sa.DateTime(timezone=True), nullable=True
            ),
        )

    # Rename old access key columns to new names (only if old names exist)
    if "aws_access_key_id" in columns and "access_key_id" not in columns:
        op.alter_column(
            "aws_integrations", "aws_access_key_id", new_column_name="access_key_id"
        )
    if "aws_secret_access_key" in columns and "secret_access_key" not in columns:
        op.alter_column(
            "aws_integrations",
            "aws_secret_access_key",
            new_column_name="secret_access_key",
        )

    # Mark existing integrations as inactive (they need to be reconfigured with role ARNs)
    op.execute("UPDATE aws_integrations SET is_active = false WHERE role_arn IS NULL")


def downgrade() -> None:
    """Downgrade schema back to access key-based authentication."""
    # Remove new columns
    op.drop_column("aws_integrations", "credentials_expiration")
    op.drop_column("aws_integrations", "session_token")
    op.drop_column("aws_integrations", "external_id")
    op.drop_column("aws_integrations", "role_arn")

    # Rename columns back to original names
    op.alter_column(
        "aws_integrations", "access_key_id", new_column_name="aws_access_key_id"
    )
    op.alter_column(
        "aws_integrations", "secret_access_key", new_column_name="aws_secret_access_key"
    )
