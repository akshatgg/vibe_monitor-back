"""Add LLM provider configs table for BYOLLM

Revision ID: g1h2i3j4k5l6
Revises: d3e4f5a6b7c8
Create Date: 2025-12-28 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "g1h2i3j4k5l6"
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


def upgrade() -> None:
    """Create LLM provider configs table for BYOLLM (Bring Your Own LLM)."""
    # Create table if it doesn't exist
    if not table_exists("llm_provider_configs"):
        op.create_table(
            "llm_provider_configs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            # Provider: 'vibemonitor' | 'openai' | 'azure_openai' | 'gemini'
            sa.Column(
                "provider", sa.String(50), nullable=False, server_default="vibemonitor"
            ),
            # Model name (e.g., "gpt-4-turbo", "gemini-1.5-pro")
            sa.Column("model_name", sa.String(100), nullable=True),
            # Encrypted JSON config blob for API keys and provider-specific settings
            sa.Column("config_encrypted", sa.Text(), nullable=True),
            # Status: 'active' | 'error' | 'unconfigured'
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            # Verification tracking
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            # Timestamps
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            # Foreign key with cascade delete
            sa.ForeignKeyConstraint(
                ["workspace_id"],
                ["workspaces.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            # Unique constraint: one config per workspace
            sa.UniqueConstraint(
                "workspace_id", name="uq_llm_provider_config_workspace"
            ),
        )

    # Create indexes if they don't exist
    if table_exists("llm_provider_configs"):
        if not index_exists(
            "idx_llm_provider_config_workspace", "llm_provider_configs"
        ):
            op.create_index(
                "idx_llm_provider_config_workspace",
                "llm_provider_configs",
                ["workspace_id"],
            )

        if not index_exists("idx_llm_provider_config_provider", "llm_provider_configs"):
            op.create_index(
                "idx_llm_provider_config_provider",
                "llm_provider_configs",
                ["provider"],
            )


def downgrade() -> None:
    """Drop LLM provider configs table."""
    if table_exists("llm_provider_configs"):
        # Drop indexes first
        if index_exists("idx_llm_provider_config_provider", "llm_provider_configs"):
            op.drop_index(
                "idx_llm_provider_config_provider", table_name="llm_provider_configs"
            )
        if index_exists("idx_llm_provider_config_workspace", "llm_provider_configs"):
            op.drop_index(
                "idx_llm_provider_config_workspace", table_name="llm_provider_configs"
            )
        # Drop table
        op.drop_table("llm_provider_configs")
