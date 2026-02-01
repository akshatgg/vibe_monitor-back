"""Add Datadog integrations table

Revision ID: f1a2b3c4d5e6
Revises: e8f9a2b3c4d5
Create Date: 2025-11-29 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e8f9a2b3c4d5"
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


def upgrade() -> None:
    """Create Datadog integrations table."""
    if not table_exists("datadog_integrations"):
        op.create_table(
            "datadog_integrations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("api_key", sa.String(), nullable=False),
            sa.Column("app_key", sa.String(), nullable=False),
            sa.Column("region", sa.String(), nullable=False),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not index_exists("idx_datadog_integration_workspace", "datadog_integrations"):
        op.create_index(
            "idx_datadog_integration_workspace",
            "datadog_integrations",
            ["workspace_id"],
        )


def downgrade() -> None:
    """Drop Datadog integrations table."""
    op.drop_index(
        "idx_datadog_integration_workspace", table_name="datadog_integrations"
    )
    op.drop_table("datadog_integrations")
