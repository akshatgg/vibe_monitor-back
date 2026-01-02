"""Add deployment tracking and workspace API keys

Revision ID: f8f458133678
Revises: be37ea21eb73
Create Date: 2026-01-02 13:30:51.475179

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8f458133678"
down_revision: Union[str, Sequence[str], None] = "be37ea21eb73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create deployment_status enum
    deployment_status = sa.Enum(
        "pending",
        "in_progress",
        "success",
        "failed",
        "cancelled",
        name="deploymentstatus",
    )
    deployment_status.create(op.get_bind(), checkfirst=True)

    # Create deployment_source enum
    deployment_source = sa.Enum(
        "manual",
        "webhook",
        "github_actions",
        "github_deployments",
        "argocd",
        "jenkins",
        name="deploymentsource",
    )
    deployment_source.create(op.get_bind(), checkfirst=True)

    # Create deployments table
    op.create_table(
        "deployments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("environment_id", sa.String(), nullable=False),
        sa.Column("repo_full_name", sa.String(255), nullable=False),
        sa.Column("branch", sa.String(255), nullable=True),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column(
            "status", deployment_status, nullable=False, server_default="success"
        ),
        sa.Column("source", deployment_source, nullable=False, server_default="manual"),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"], ["environments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_deployments_env_repo_deployed",
        "deployments",
        ["environment_id", "repo_full_name", "deployed_at"],
    )
    op.create_index("ix_deployments_environment_id", "deployments", ["environment_id"])

    # Create workspace_api_keys table
    op.create_table(
        "workspace_api_keys",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workspace_api_keys_workspace_id", "workspace_api_keys", ["workspace_id"]
    )
    op.create_index(
        "ix_workspace_api_keys_key_hash", "workspace_api_keys", ["key_hash"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop workspace_api_keys table
    op.drop_index("ix_workspace_api_keys_key_hash", table_name="workspace_api_keys")
    op.drop_index("ix_workspace_api_keys_workspace_id", table_name="workspace_api_keys")
    op.drop_table("workspace_api_keys")

    # Drop deployments table
    op.drop_index("ix_deployments_environment_id", table_name="deployments")
    op.drop_index("ix_deployments_env_repo_deployed", table_name="deployments")
    op.drop_table("deployments")

    # Drop enums
    sa.Enum(name="deploymentsource").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="deploymentstatus").drop(op.get_bind(), checkfirst=True)
