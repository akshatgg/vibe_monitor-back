"""Add deployment tracking and workspace API keys

Revision ID: f8f458133678
Revises: be37ea21eb73
Create Date: 2026-01-02 13:30:51.475179

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ENUM


# revision identifiers, used by Alembic.
revision: str = "f8f458133678"
down_revision: Union[str, Sequence[str], None] = "be37ea21eb73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    # Create deployment_status enum (idempotent)
    op.execute(
        text("""
            DO $$ BEGIN
                CREATE TYPE deploymentstatus AS ENUM (
                    'pending', 'in_progress', 'success', 'failed', 'cancelled'
                );
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
        """)
    )

    # Create deployment_source enum (idempotent)
    op.execute(
        text("""
            DO $$ BEGIN
                CREATE TYPE deploymentsource AS ENUM (
                    'manual', 'webhook', 'github_actions', 'github_deployments', 'argocd', 'jenkins'
                );
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
        """)
    )

    # ----- deployments table -----
    if "deployments" not in existing_tables:
        op.create_table(
            "deployments",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("environment_id", sa.String(), nullable=False),
            sa.Column("repo_full_name", sa.String(255), nullable=False),
            sa.Column("branch", sa.String(255), nullable=True),
            sa.Column("commit_sha", sa.String(40), nullable=True),
            sa.Column(
                "status",
                ENUM(
                    "pending",
                    "in_progress",
                    "success",
                    "failed",
                    "cancelled",
                    name="deploymentstatus",
                    create_type=False,
                ),
                nullable=False,
                server_default="success",
            ),
            sa.Column(
                "source",
                ENUM(
                    "manual",
                    "webhook",
                    "github_actions",
                    "github_deployments",
                    "argocd",
                    "jenkins",
                    name="deploymentsource",
                    create_type=False,
                ),
                nullable=False,
                server_default="manual",
            ),
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
        existing_tables.add("deployments")
    else:
        print("  ⊘ Table 'deployments' already exists, skipping...")

    # Create indexes for deployments
    existing_deployments_indexes = {i["name"] for i in inspector.get_indexes("deployments")} if "deployments" in existing_tables else set()

    deployments_indexes = [
        ("ix_deployments_env_repo_deployed", ["environment_id", "repo_full_name", "deployed_at"]),
        ("ix_deployments_environment_id", ["environment_id"]),
    ]

    for idx_name, columns in deployments_indexes:
        if idx_name not in existing_deployments_indexes:
            op.create_index(idx_name, "deployments", columns)
            existing_deployments_indexes.add(idx_name)
        else:
            print(f"  ⊘ Index '{idx_name}' already exists, skipping...")

    # ----- workspace_api_keys table -----
    if "workspace_api_keys" not in existing_tables:
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
        existing_tables.add("workspace_api_keys")
    else:
        print("  ⊘ Table 'workspace_api_keys' already exists, skipping...")

    # Create indexes for workspace_api_keys
    existing_apikeys_indexes = {i["name"] for i in inspector.get_indexes("workspace_api_keys")} if "workspace_api_keys" in existing_tables else set()

    apikeys_indexes = [
        ("ix_workspace_api_keys_workspace_id", ["workspace_id"]),
        ("ix_workspace_api_keys_key_hash", ["key_hash"]),
    ]

    for idx_name, columns in apikeys_indexes:
        if idx_name not in existing_apikeys_indexes:
            op.create_index(idx_name, "workspace_api_keys", columns)
            existing_apikeys_indexes.add(idx_name)
        else:
            print(f"  ⊘ Index '{idx_name}' already exists, skipping...")


def downgrade() -> None:
    """Downgrade schema."""
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    # ----- Drop workspace_api_keys table -----
    if "workspace_api_keys" in existing_tables:
        existing_apikeys_indexes = {i["name"] for i in inspector.get_indexes("workspace_api_keys")}

        for idx_name in [
            "ix_workspace_api_keys_key_hash",
            "ix_workspace_api_keys_workspace_id",
        ]:
            if idx_name in existing_apikeys_indexes:
                op.drop_index(idx_name, table_name="workspace_api_keys")

        op.drop_table("workspace_api_keys")
    else:
        print("  ⊘ Table 'workspace_api_keys' does not exist, skipping...")

    # ----- Drop deployments table -----
    if "deployments" in existing_tables:
        existing_deployments_indexes = {i["name"] for i in inspector.get_indexes("deployments")}

        for idx_name in [
            "ix_deployments_environment_id",
            "ix_deployments_env_repo_deployed",
        ]:
            if idx_name in existing_deployments_indexes:
                op.drop_index(idx_name, table_name="deployments")

        op.drop_table("deployments")
    else:
        print("  ⊘ Table 'deployments' does not exist, skipping...")

    # Drop enums
    op.execute(text("DROP TYPE IF EXISTS deploymentsource"))
    op.execute(text("DROP TYPE IF EXISTS deploymentstatus"))
