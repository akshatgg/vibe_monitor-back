"""add_integrations_control_plane

Revision ID: a1b2c3d4e5f6
Revises: 80ff9d48ddc5
Create Date: 2025-12-17 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '80ff9d48ddc5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # ==========================================================================
    # STEP 1: Create integrations control plane table
    # ==========================================================================
    op.create_table(
        'integrations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('health_status', sa.String(), nullable=True),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.CheckConstraint("status IN ('active', 'disabled', 'error')", name='check_integration_status'),
        sa.CheckConstraint("health_status IS NULL OR health_status IN ('healthy', 'degraded', 'failed', 'unknown')", name='check_integration_health_status'),
        sa.UniqueConstraint('workspace_id', 'provider', name='unique_provider_per_workspace')
    )

    op.create_index('idx_integrations_workspace', 'integrations', ['workspace_id'])
    op.create_index('idx_integrations_provider', 'integrations', ['provider'])
    op.create_index('idx_integrations_workspace_provider', 'integrations', ['workspace_id', 'provider'])
    op.create_index('idx_integrations_status', 'integrations', ['status'], postgresql_where=sa.text("status = 'active'"))
    op.create_index('idx_integrations_health', 'integrations', ['health_status'], postgresql_where=sa.text("health_status != 'healthy'"))

    # ==========================================================================
    # STEP 2: Add integration_id FK column to all provider tables (nullable)
    # ==========================================================================
    provider_tables = [
        ('github_integrations', 'fk_github_integrations_integration_id'),
        ('aws_integrations', 'fk_aws_integrations_integration_id'),
        ('grafana_integrations', 'fk_grafana_integrations_integration_id'),
        ('datadog_integrations', 'fk_datadog_integrations_integration_id'),
        ('newrelic_integrations', 'fk_newrelic_integrations_integration_id'),
        ('slack_installations', 'fk_slack_installations_integration_id'),
    ]

    for table, fk_name in provider_tables:
        op.add_column(table, sa.Column('integration_id', sa.String(), nullable=True))
        op.create_foreign_key(fk_name, table, 'integrations', ['integration_id'], ['id'], ondelete='CASCADE')

    # ==========================================================================
    # STEP 3: Backfill integrations from existing provider tables
    # ==========================================================================

    # GitHub
    conn.execute(text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at, last_verified_at)
        SELECT gen_random_uuid(), workspace_id, 'github',
            CASE WHEN is_active THEN 'active' ELSE 'disabled' END,
            CASE WHEN is_active THEN 'unknown' ELSE 'failed' END,
            created_at, COALESCE(updated_at, created_at), last_synced_at
        FROM github_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """))
    conn.execute(text("""
        UPDATE github_integrations gi SET integration_id = i.id
        FROM integrations i WHERE gi.workspace_id = i.workspace_id AND i.provider = 'github' AND gi.integration_id IS NULL;
    """))

    # AWS
    conn.execute(text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at, last_verified_at)
        SELECT gen_random_uuid(), workspace_id, 'aws',
            CASE WHEN is_active THEN 'active' ELSE 'disabled' END,
            CASE WHEN is_active THEN 'unknown' ELSE 'failed' END,
            created_at, COALESCE(updated_at, created_at), last_verified_at
        FROM aws_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """))
    conn.execute(text("""
        UPDATE aws_integrations ai SET integration_id = i.id
        FROM integrations i WHERE ai.workspace_id = i.workspace_id AND i.provider = 'aws' AND ai.integration_id IS NULL;
    """))

    # Grafana
    conn.execute(text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at)
        SELECT gen_random_uuid(), vm_workspace_id, 'grafana', 'active', 'unknown',
            created_at, COALESCE(updated_at, created_at)
        FROM grafana_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """))
    conn.execute(text("""
        UPDATE grafana_integrations gi SET integration_id = i.id
        FROM integrations i WHERE gi.vm_workspace_id = i.workspace_id AND i.provider = 'grafana' AND gi.integration_id IS NULL;
    """))

    # Datadog
    conn.execute(text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at, last_verified_at)
        SELECT gen_random_uuid(), workspace_id, 'datadog', 'active', 'unknown',
            created_at, COALESCE(updated_at, created_at), last_verified_at
        FROM datadog_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """))
    conn.execute(text("""
        UPDATE datadog_integrations di SET integration_id = i.id
        FROM integrations i WHERE di.workspace_id = i.workspace_id AND i.provider = 'datadog' AND di.integration_id IS NULL;
    """))

    # NewRelic
    conn.execute(text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at, last_verified_at)
        SELECT gen_random_uuid(), workspace_id, 'newrelic', 'active', 'unknown',
            created_at, COALESCE(updated_at, created_at), last_verified_at
        FROM newrelic_integrations WHERE integration_id IS NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """))
    conn.execute(text("""
        UPDATE newrelic_integrations ni SET integration_id = i.id
        FROM integrations i WHERE ni.workspace_id = i.workspace_id AND i.provider = 'newrelic' AND ni.integration_id IS NULL;
    """))

    # Slack
    conn.execute(text("""
        INSERT INTO integrations (id, workspace_id, provider, status, health_status, created_at, updated_at)
        SELECT gen_random_uuid(), workspace_id, 'slack', 'active', 'unknown',
            installed_at, COALESCE(updated_at, installed_at)
        FROM slack_installations WHERE integration_id IS NULL AND workspace_id IS NOT NULL
        ON CONFLICT (workspace_id, provider) DO NOTHING;
    """))
    conn.execute(text("""
        UPDATE slack_installations si SET integration_id = i.id
        FROM integrations i WHERE si.workspace_id = i.workspace_id AND i.provider = 'slack' AND si.integration_id IS NULL;
    """))

    # ==========================================================================
    # STEP 4: Add NOT NULL constraints and indexes to integration_id columns
    # ==========================================================================
    for table in ['github_integrations', 'aws_integrations', 'grafana_integrations',
                  'datadog_integrations', 'newrelic_integrations']:
        op.alter_column(table, 'integration_id', nullable=False)
        op.create_unique_constraint(f'uq_{table}_integration_id', table, ['integration_id'])
        op.create_index(f'idx_{table}_integration_id', table, ['integration_id'])

    # Slack - keep nullable (some installations may not have workspace_id)
    op.create_unique_constraint('uq_slack_installations_integration_id', 'slack_installations', ['integration_id'])
    op.create_index('idx_slack_installations_integration_id', 'slack_installations', ['integration_id'])


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    # Drop indexes and constraints from provider tables
    for table in ['slack_installations', 'newrelic_integrations', 'datadog_integrations',
                  'grafana_integrations', 'aws_integrations', 'github_integrations']:
        op.drop_index(f'idx_{table}_integration_id', table_name=table)
        op.drop_constraint(f'uq_{table}_integration_id', table, type_='unique')
        if table != 'slack_installations':
            op.alter_column(table, 'integration_id', nullable=True)

    # Clear integration_id values
    conn.execute(text("UPDATE github_integrations SET integration_id = NULL"))
    conn.execute(text("UPDATE aws_integrations SET integration_id = NULL"))
    conn.execute(text("UPDATE grafana_integrations SET integration_id = NULL"))
    conn.execute(text("UPDATE datadog_integrations SET integration_id = NULL"))
    conn.execute(text("UPDATE newrelic_integrations SET integration_id = NULL"))
    conn.execute(text("UPDATE slack_installations SET integration_id = NULL"))

    # Delete all integrations
    conn.execute(text("DELETE FROM integrations"))

    # Drop FK constraints and columns
    for table, fk_name in [
        ('slack_installations', 'fk_slack_installations_integration_id'),
        ('newrelic_integrations', 'fk_newrelic_integrations_integration_id'),
        ('datadog_integrations', 'fk_datadog_integrations_integration_id'),
        ('grafana_integrations', 'fk_grafana_integrations_integration_id'),
        ('aws_integrations', 'fk_aws_integrations_integration_id'),
        ('github_integrations', 'fk_github_integrations_integration_id'),
    ]:
        op.drop_constraint(fk_name, table, type_='foreignkey')
        op.drop_column(table, 'integration_id')

    # Drop integrations table indexes
    op.drop_index('idx_integrations_health', table_name='integrations')
    op.drop_index('idx_integrations_status', table_name='integrations')
    op.drop_index('idx_integrations_workspace_provider', table_name='integrations')
    op.drop_index('idx_integrations_provider', table_name='integrations')
    op.drop_index('idx_integrations_workspace', table_name='integrations')

    # Drop integrations table
    op.drop_table('integrations')
