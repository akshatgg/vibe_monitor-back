"""Add services table

Revision ID: s3rv1c3s
Revises: s1a2c3k4
Create Date: 2025-12-28

Adds the services table for tracking billable services within workspaces.
Services are the billing unit for the platform:
- Free tier: 5 services
- Paid tier: $30/month for 5 services + $5/month per additional service
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "s3rv1c3s"
down_revision: Union[str, Sequence[str], None] = "s1a2c3k4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    """Create services table."""
    if not table_exists("services"):
        op.create_table(
            "services",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("repository_id", sa.String(), nullable=True),
            sa.Column("repository_name", sa.String(255), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["workspace_id"],
                ["workspaces.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["repository_id"],
                ["github_integrations.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create indexes
        op.create_index(
            "uq_workspace_service_name",
            "services",
            ["workspace_id", "name"],
            unique=True,
        )
        op.create_index(
            "idx_services_workspace",
            "services",
            ["workspace_id"],
        )
        op.create_index(
            "idx_services_repository",
            "services",
            ["repository_id"],
        )
        op.create_index(
            "idx_services_enabled",
            "services",
            ["enabled"],
        )


def downgrade() -> None:
    """Drop services table."""
    if table_exists("services"):
        op.drop_index("idx_services_enabled", table_name="services")
        op.drop_index("idx_services_repository", table_name="services")
        op.drop_index("idx_services_workspace", table_name="services")
        op.drop_index("uq_workspace_service_name", table_name="services")
        op.drop_table("services")
