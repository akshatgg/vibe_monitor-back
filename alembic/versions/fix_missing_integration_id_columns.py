"""fix_missing_integration_id_columns

Revision ID: fix_integration_id
Revises: 3a1525015433
Create Date: 2025-12-18 18:10:00.000000

This migration fixes a state mismatch where the a1b2c3d4e5f6 migration
was marked as complete but the integration_id columns were not actually added.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = "fix_integration_id"
down_revision: Union[str, Sequence[str], None] = "3a1525015433"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(conn, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    # nosec B608 - table_name and column_name are hardcoded constants, not user input
    result = conn.execute(
        text(f"""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = '{table_name}' AND column_name = '{column_name}'
        )
    """)  # nosec B608
    )
    return result.scalar()


def upgrade() -> None:
    """Add missing integration_id columns if they don't exist."""
    conn = op.get_bind()

    # Tables that need integration_id column
    provider_tables = [
        ("github_integrations", "fk_github_integrations_integration_id", False),
        ("aws_integrations", "fk_aws_integrations_integration_id", False),
        ("grafana_integrations", "fk_grafana_integrations_integration_id", False),
        ("datadog_integrations", "fk_datadog_integrations_integration_id", False),
        ("newrelic_integrations", "fk_newrelic_integrations_integration_id", False),
        (
            "slack_installations",
            "fk_slack_installations_integration_id",
            True,
        ),  # nullable for slack
    ]

    # Check if integrations table exists, create if not
    integrations_exists = conn.execute(
        text("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'integrations'
        )
    """)
    ).scalar()

    if not integrations_exists:
        print("Creating integrations table...")
        op.create_table(
            "integrations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("workspace_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("health_status", sa.String(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint(
                "workspace_id", "provider", name="unique_provider_per_workspace"
            ),
        )
        op.create_index("idx_integrations_workspace", "integrations", ["workspace_id"])
        op.create_index("idx_integrations_provider", "integrations", ["provider"])
    else:
        # Check if unique constraint exists, create if missing
        constraint_exists = conn.execute(
            text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_name = 'integrations'
                AND constraint_name = 'unique_provider_per_workspace'
            )
        """)
        ).scalar()

        if not constraint_exists:
            print("Adding unique constraint to integrations table...")
            # First delete any duplicates
            conn.execute(
                text("""
                DELETE FROM integrations a USING integrations b
                WHERE a.id < b.id
                AND a.workspace_id = b.workspace_id
                AND a.provider = b.provider;
            """)
            )
            op.create_unique_constraint(
                "unique_provider_per_workspace",
                "integrations",
                ["workspace_id", "provider"],
            )

    # Add integration_id columns where missing
    for table, fk_name, nullable in provider_tables:
        if not column_exists(conn, table, "integration_id"):
            print(f"Adding integration_id column to {table}...")
            op.add_column(
                table, sa.Column("integration_id", sa.String(), nullable=True)
            )

            # Try to create FK, ignore if exists
            try:
                op.create_foreign_key(
                    fk_name,
                    table,
                    "integrations",
                    ["integration_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
            except Exception as e:
                print(f"FK {fk_name} may already exist: {e}")
        else:
            print(f"Column integration_id already exists in {table}, skipping...")

    # Backfill integrations data if needed
    print("Backfilling integrations data...")

    # GitHub
    conn.execute(
        text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at, last_verified_at)
        SELECT gen_random_uuid()::text, workspace_id, 'github',
            CASE WHEN is_active THEN 'active' ELSE 'disabled' END,
            NULL,
            created_at, COALESCE(updated_at, created_at), last_synced_at
        FROM github_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """)
    )
    conn.execute(
        text("""
        UPDATE github_integrations gi SET integration_id = i.id
        FROM integrations i WHERE gi.workspace_id = i.workspace_id AND i.provider = 'github' AND gi.integration_id IS NULL;
    """)
    )

    # AWS
    conn.execute(
        text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at, last_verified_at)
        SELECT gen_random_uuid()::text, workspace_id, 'aws',
            CASE WHEN is_active THEN 'active' ELSE 'disabled' END,
            NULL,
            created_at, COALESCE(updated_at, created_at), last_verified_at
        FROM aws_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """)
    )
    conn.execute(
        text("""
        UPDATE aws_integrations ai SET integration_id = i.id
        FROM integrations i WHERE ai.workspace_id = i.workspace_id AND i.provider = 'aws' AND ai.integration_id IS NULL;
    """)
    )

    # Grafana
    conn.execute(
        text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at)
        SELECT gen_random_uuid()::text, vm_workspace_id, 'grafana', 'active', NULL,
            created_at, COALESCE(updated_at, created_at)
        FROM grafana_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """)
    )
    conn.execute(
        text("""
        UPDATE grafana_integrations gi SET integration_id = i.id
        FROM integrations i WHERE gi.vm_workspace_id = i.workspace_id AND i.provider = 'grafana' AND gi.integration_id IS NULL;
    """)
    )

    # Datadog
    conn.execute(
        text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at, last_verified_at)
        SELECT gen_random_uuid()::text, workspace_id, 'datadog', 'active', NULL,
            created_at, COALESCE(updated_at, created_at), last_verified_at
        FROM datadog_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """)
    )
    conn.execute(
        text("""
        UPDATE datadog_integrations di SET integration_id = i.id
        FROM integrations i WHERE di.workspace_id = i.workspace_id AND i.provider = 'datadog' AND di.integration_id IS NULL;
    """)
    )

    # NewRelic
    conn.execute(
        text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at, last_verified_at)
        SELECT gen_random_uuid()::text, workspace_id, 'newrelic', 'active', NULL,
            created_at, COALESCE(updated_at, created_at), last_verified_at
        FROM newrelic_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """)
    )
    conn.execute(
        text("""
        UPDATE newrelic_integrations ni SET integration_id = i.id
        FROM integrations i WHERE ni.workspace_id = i.workspace_id AND i.provider = 'newrelic' AND ni.integration_id IS NULL;
    """)
    )

    # Slack
    conn.execute(
        text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at)
        SELECT gen_random_uuid()::text, workspace_id, 'slack', 'active', NULL,
            installed_at, COALESCE(updated_at, installed_at)
        FROM slack_installations WHERE integration_id IS NULL AND workspace_id IS NOT NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """)
    )
    conn.execute(
        text("""
        UPDATE slack_installations si SET integration_id = i.id
        FROM integrations i WHERE si.workspace_id = i.workspace_id AND i.provider = 'slack' AND si.integration_id IS NULL;
    """)
    )

    print("Backfill complete.")


def downgrade() -> None:
    """This migration is a fix, downgrade not supported."""
    pass
