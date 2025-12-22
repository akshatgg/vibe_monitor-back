"""Add New Relic integrations table

Revision ID: e8f9a2b3c4d5
Revises: d963cf8403c6
Create Date: 2025-11-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e8f9a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "d963cf8403c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create New Relic integrations table."""
    op.create_table(
        "newrelic_integrations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("api_key", sa.String(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
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
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes
    op.create_index(
        "idx_newrelic_integration_workspace",
        "newrelic_integrations",
        ["workspace_id"],
    )


def downgrade() -> None:
    """Drop New Relic integrations table."""
    op.drop_index(
        "idx_newrelic_integration_workspace", table_name="newrelic_integrations"
    )
    op.drop_table("newrelic_integrations")
