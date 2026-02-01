"""Baseline schema snapshot - Fresh start point for all migrations.

Revision ID: z000_baseline_snapshot
Revises: None (This is the new root)
Create Date: 2026-02-02

This migration captures the complete database schema as of PR #213.
It serves as a clean starting point, replacing all 49 historical migrations.

IMPORTANT:
- For FRESH databases: This runs and creates everything.
- For EXISTING databases (prod): Run `alembic stamp z000_baseline_snapshot`
  to mark the DB as already at this version WITHOUT running the migration.

After this baseline:
- All enum values are UPPERCASE
- All tables, indexes, and constraints match the current app/models.py
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "z000_baseline_snapshot"
down_revision = None  # This is the new root migration
branch_labels = None
depends_on = None


def upgrade():
    """Create complete schema from scratch."""

    # =========================================================================
    # ENUM TYPES (all UPPERCASE values)
    # =========================================================================

    role_enum = postgresql.ENUM('OWNER', 'USER', name='role', create_type=False)
    jobstatus_enum = postgresql.ENUM('QUEUED', 'RUNNING', 'WAITING_INPUT', 'COMPLETED', 'FAILED', name='jobstatus', create_type=False)
    jobsource_enum = postgresql.ENUM('SLACK', 'WEB', 'MSTEAMS', name='jobsource', create_type=False)
    feedbacksource_enum = postgresql.ENUM('WEB', 'SLACK', name='feedbacksource', create_type=False)
    turnstatus_enum = postgresql.ENUM('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', name='turnstatus', create_type=False)
    steptype_enum = postgresql.ENUM('TOOL_CALL', 'THINKING', 'STATUS', name='steptype', create_type=False)
    stepstatus_enum = postgresql.ENUM('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', name='stepstatus', create_type=False)
    invitationstatus_enum = postgresql.ENUM('PENDING', 'ACCEPTED', 'DECLINED', 'EXPIRED', name='invitationstatus', create_type=False)
    deploymentstatus_enum = postgresql.ENUM('PENDING', 'IN_PROGRESS', 'SUCCESS', 'FAILED', 'CANCELLED', name='deploymentstatus', create_type=False)
    deploymentsource_enum = postgresql.ENUM('MANUAL', 'WEBHOOK', 'GITHUB_ACTIONS', 'GITHUB_DEPLOYMENTS', 'ARGOCD', 'JENKINS', name='deploymentsource', create_type=False)
    llmprovider_enum = postgresql.ENUM('VIBEMONITOR', 'OPENAI', 'AZURE_OPENAI', 'GEMINI', name='llmprovider', create_type=False)
    llmconfigstatus_enum = postgresql.ENUM('ACTIVE', 'ERROR', 'UNCONFIGURED', name='llmconfigstatus', create_type=False)
    plantype_enum = postgresql.ENUM('FREE', 'PRO', name='plantype', create_type=False)
    subscriptionstatus_enum = postgresql.ENUM('ACTIVE', 'PAST_DUE', 'CANCELED', 'INCOMPLETE', 'TRIALING', name='subscriptionstatus', create_type=False)
    securityeventtype_enum = postgresql.ENUM('PROMPT_INJECTION', 'GUARD_DEGRADED', name='securityeventtype', create_type=False)

    # Create all enum types
    role_enum.create(op.get_bind(), checkfirst=True)
    jobstatus_enum.create(op.get_bind(), checkfirst=True)
    jobsource_enum.create(op.get_bind(), checkfirst=True)
    feedbacksource_enum.create(op.get_bind(), checkfirst=True)
    turnstatus_enum.create(op.get_bind(), checkfirst=True)
    steptype_enum.create(op.get_bind(), checkfirst=True)
    stepstatus_enum.create(op.get_bind(), checkfirst=True)
    invitationstatus_enum.create(op.get_bind(), checkfirst=True)
    deploymentstatus_enum.create(op.get_bind(), checkfirst=True)
    deploymentsource_enum.create(op.get_bind(), checkfirst=True)
    llmprovider_enum.create(op.get_bind(), checkfirst=True)
    llmconfigstatus_enum.create(op.get_bind(), checkfirst=True)
    plantype_enum.create(op.get_bind(), checkfirst=True)
    subscriptionstatus_enum.create(op.get_bind(), checkfirst=True)
    securityeventtype_enum.create(op.get_bind(), checkfirst=True)

    # =========================================================================
    # CORE TABLES (in dependency order)
    # =========================================================================

    # --- workspaces (no FK dependencies) ---
    op.create_table('workspaces',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('domain', sa.String(), nullable=True),
        sa.Column('visible_to_org', sa.Boolean(), nullable=True, default=False),
        sa.Column('is_paid', sa.Boolean(), nullable=True, default=False),
        sa.Column('daily_request_limit', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # --- users (depends on workspaces for last_visited_workspace_id) ---
    op.create_table('users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False, default=False),
        sa.Column('newsletter_subscribed', sa.Boolean(), nullable=False, default=True),
        sa.Column('is_onboarded', sa.Boolean(), nullable=False, default=False),
        sa.Column('last_visited_workspace_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.ForeignKeyConstraint(['last_visited_workspace_id'], ['workspaces.id'], ondelete='SET NULL')
    )

    # --- integrations (central control plane) ---
    op.create_table('integrations',
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
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE')
    )
    op.create_index('ix_integrations_workspace_id', 'integrations', ['workspace_id'])
    op.create_index('ix_integrations_workspace_provider', 'integrations', ['workspace_id', 'provider'])

    # --- memberships ---
    op.create_table('memberships',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('role', role_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.UniqueConstraint('user_id', 'workspace_id', name='uq_membership_user_workspace')
    )

    # --- teams ---
    op.create_table('teams',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('geography', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE')
    )
    op.create_index('uq_team_workspace_name', 'teams', ['workspace_id', 'name'], unique=True)
    op.create_index('idx_teams_workspace', 'teams', ['workspace_id'])
    op.create_index('idx_teams_name', 'teams', ['name'])

    # --- team_membership ---
    op.create_table('team_membership',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE')
    )
    op.create_index('uq_team_membership', 'team_membership', ['team_id', 'user_id'], unique=True)
    op.create_index('idx_team_membership_team', 'team_membership', ['team_id'])
    op.create_index('idx_team_membership_user', 'team_membership', ['user_id'])

    # --- workspace_invitations ---
    op.create_table('workspace_invitations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('inviter_id', sa.String(), nullable=False),
        sa.Column('invitee_email', sa.String(), nullable=False),
        sa.Column('invitee_id', sa.String(), nullable=True),
        sa.Column('role', role_enum, nullable=False),
        sa.Column('status', invitationstatus_enum, nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['inviter_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invitee_id'], ['users.id'], ondelete='CASCADE')
    )
    op.create_index('idx_invitation_workspace', 'workspace_invitations', ['workspace_id'])
    op.create_index('idx_invitation_invitee_email', 'workspace_invitations', ['invitee_email'])
    op.create_index('idx_invitation_token', 'workspace_invitations', ['token'])
    op.create_index('idx_invitation_status', 'workspace_invitations', ['status'])
    op.create_index('idx_invitation_expires_at', 'workspace_invitations', ['expires_at'])

    # --- refresh_tokens ---
    op.create_table('refresh_tokens',
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('token')
    )

    # --- email_verifications ---
    op.create_table('email_verifications',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=True),
        sa.Column('token_type', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'])
    )
    op.create_index('idx_email_verification_token', 'email_verifications', ['token'])
    op.create_index('idx_email_verification_user', 'email_verifications', ['user_id'])
    op.create_index('idx_email_verification_expires', 'email_verifications', ['expires_at'])
    op.create_index('ix_email_verifications_token_hash', 'email_verifications', ['token_hash'])

    # --- emails ---
    op.create_table('emails',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('message_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'])
    )
    op.create_index('idx_emails_user', 'emails', ['user_id'])
    op.create_index('idx_emails_sent_at', 'emails', ['sent_at'])
    op.create_index('idx_emails_status', 'emails', ['status'])

    # =========================================================================
    # INTEGRATION TABLES
    # =========================================================================

    # --- grafana_integrations ---
    op.create_table('grafana_integrations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('vm_workspace_id', sa.String(), nullable=False),
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('grafana_url', sa.String(500), nullable=False),
        sa.Column('api_token', sa.String(500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['vm_workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ondelete='CASCADE')
    )

    # --- slack_installations ---
    op.create_table('slack_installations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('team_id', sa.String(), nullable=False),
        sa.Column('team_name', sa.String(), nullable=False),
        sa.Column('access_token', sa.String(), nullable=False),
        sa.Column('bot_user_id', sa.String(), nullable=True),
        sa.Column('scope', sa.String(), nullable=True),
        sa.Column('workspace_id', sa.String(), nullable=True),
        sa.Column('integration_id', sa.String(), nullable=True),
        sa.Column('installed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ondelete='CASCADE')
    )

    # --- github_integrations ---
    op.create_table('github_integrations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('github_user_id', sa.String(), nullable=False),
        sa.Column('github_username', sa.String(), nullable=False),
        sa.Column('installation_id', sa.String(), nullable=False),
        sa.Column('scopes', sa.String(), nullable=True),
        sa.Column('access_token', sa.String(), nullable=True),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('installation_id', name='uq_github_integrations_installation_id')
    )
    op.create_index('idx_github_integration_installation', 'github_integrations', ['installation_id'])

    # --- aws_integrations ---
    op.create_table('aws_integrations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('role_arn', sa.String(), nullable=False),
        sa.Column('external_id', sa.String(), nullable=True),
        sa.Column('access_key_id', sa.String(), nullable=False),
        sa.Column('secret_access_key', sa.String(), nullable=False),
        sa.Column('session_token', sa.String(), nullable=False),
        sa.Column('credentials_expiration', sa.DateTime(timezone=True), nullable=False),
        sa.Column('aws_region', sa.String(), nullable=True, server_default='us-west-1'),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ondelete='CASCADE')
    )
    op.create_index('idx_aws_integration_workspace', 'aws_integrations', ['workspace_id'])
    op.create_index('idx_aws_integration_active', 'aws_integrations', ['is_active'])

    # --- newrelic_integrations ---
    op.create_table('newrelic_integrations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('account_id', sa.String(), nullable=False),
        sa.Column('api_key', sa.String(), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ondelete='CASCADE')
    )

    # --- datadog_integrations ---
    op.create_table('datadog_integrations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('integration_id', sa.String(), nullable=False),
        sa.Column('api_key', sa.String(), nullable=False),
        sa.Column('app_key', sa.String(), nullable=False),
        sa.Column('region', sa.String(), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['integration_id'], ['integrations.id'], ondelete='CASCADE')
    )
    op.create_index('idx_datadog_integration_workspace', 'datadog_integrations', ['workspace_id'])

    # =========================================================================
    # JOB & SECURITY TABLES
    # =========================================================================

    # --- jobs ---
    op.create_table('jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('vm_workspace_id', sa.String(), nullable=False),
        sa.Column('source', jobsource_enum, nullable=False),
        sa.Column('slack_integration_id', sa.String(), nullable=True),
        sa.Column('trigger_channel_id', sa.String(), nullable=True),
        sa.Column('trigger_thread_ts', sa.String(), nullable=True),
        sa.Column('trigger_message_ts', sa.String(), nullable=True),
        sa.Column('status', jobstatus_enum, nullable=False),
        sa.Column('priority', sa.Integer(), nullable=True, default=0),
        sa.Column('retries', sa.Integer(), nullable=True, default=0),
        sa.Column('max_retries', sa.Integer(), nullable=True, default=3),
        sa.Column('backoff_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('requested_context', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['vm_workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['slack_integration_id'], ['slack_installations.id'], ondelete='CASCADE')
    )
    op.create_index('idx_jobs_workspace_status', 'jobs', ['vm_workspace_id', 'status'])
    op.create_index('idx_jobs_slack_integration', 'jobs', ['slack_integration_id'])
    op.create_index('idx_jobs_created_at', 'jobs', ['created_at'])

    # --- security_events ---
    op.create_table('security_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('event_type', securityeventtype_enum, nullable=False),
        sa.Column('severity', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=True),
        sa.Column('slack_integration_id', sa.String(), nullable=True),
        sa.Column('slack_user_id', sa.String(), nullable=True),
        sa.Column('message_preview', sa.Text(), nullable=True),
        sa.Column('guard_response', sa.String(), nullable=True),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('event_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['slack_integration_id'], ['slack_installations.id'], ondelete='CASCADE')
    )
    op.create_index('idx_security_events_type', 'security_events', ['event_type'])
    op.create_index('idx_security_events_workspace', 'security_events', ['workspace_id'])
    op.create_index('idx_security_events_detected_at', 'security_events', ['detected_at'])
    op.create_index('idx_security_events_slack_user', 'security_events', ['slack_user_id'])
    op.create_index('idx_security_events_slack_integration', 'security_events', ['slack_integration_id'])

    # --- rate_limit_tracking ---
    op.create_table('rate_limit_tracking',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('resource_type', sa.String(), nullable=False),
        sa.Column('window_key', sa.String(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'])
    )
    op.create_index('idx_rate_limit_unique', 'rate_limit_tracking', ['workspace_id', 'resource_type', 'window_key'], unique=True)
    op.create_index('idx_rate_limit_workspace', 'rate_limit_tracking', ['workspace_id'])
    op.create_index('idx_rate_limit_resource', 'rate_limit_tracking', ['resource_type'])

    # =========================================================================
    # CHAT TABLES
    # =========================================================================

    # --- chat_sessions ---
    op.create_table('chat_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('source', jobsource_enum, nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('slack_team_id', sa.String(), nullable=True),
        sa.Column('slack_channel_id', sa.String(), nullable=True),
        sa.Column('slack_thread_ts', sa.String(), nullable=True),
        sa.Column('slack_user_id', sa.String(), nullable=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'])
    )
    op.create_index('idx_chat_sessions_workspace', 'chat_sessions', ['workspace_id'])
    op.create_index('idx_chat_sessions_user', 'chat_sessions', ['user_id'])
    op.create_index('idx_chat_sessions_workspace_user', 'chat_sessions', ['workspace_id', 'user_id'])
    op.create_index('idx_chat_sessions_created_at', 'chat_sessions', ['created_at'])
    op.create_index('idx_chat_sessions_source', 'chat_sessions', ['source'])

    # --- chat_turns ---
    op.create_table('chat_turns',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('user_message', sa.Text(), nullable=False),
        sa.Column('final_response', sa.Text(), nullable=True),
        sa.Column('status', turnstatus_enum, nullable=False),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'])
    )
    op.create_index('idx_chat_turns_session', 'chat_turns', ['session_id'])
    op.create_index('idx_chat_turns_job', 'chat_turns', ['job_id'])
    op.create_index('idx_chat_turns_status', 'chat_turns', ['status'])
    op.create_index('idx_chat_turns_created_at', 'chat_turns', ['created_at'])

    # --- chat_files ---
    op.create_table('chat_files',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('turn_id', sa.String(), nullable=False),
        sa.Column('s3_bucket', sa.String(), nullable=False),
        sa.Column('s3_key', sa.String(), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('relative_path', sa.String(500), nullable=True),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('uploaded_by', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['turn_id'], ['chat_turns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='CASCADE')
    )
    op.create_index('idx_chat_files_turn_id', 'chat_files', ['turn_id'])
    op.create_index('idx_chat_files_uploaded_by', 'chat_files', ['uploaded_by'])
    op.create_index('idx_chat_files_created_at', 'chat_files', ['created_at'])

    # --- turn_feedbacks ---
    op.create_table('turn_feedbacks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('turn_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('slack_user_id', sa.String(255), nullable=True),
        sa.Column('is_positive', sa.Boolean(), nullable=False),
        sa.Column('source', feedbacksource_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['turn_id'], ['chat_turns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('turn_id', 'user_id', name='uq_turn_feedback_user'),
        sa.UniqueConstraint('turn_id', 'slack_user_id', name='uq_turn_feedback_slack_user')
    )
    op.create_index('idx_turn_feedbacks_turn_id', 'turn_feedbacks', ['turn_id'])
    op.create_index('idx_turn_feedbacks_user_id', 'turn_feedbacks', ['user_id'])
    op.create_index('idx_turn_feedbacks_slack_user_id', 'turn_feedbacks', ['slack_user_id'])

    # --- turn_comments ---
    op.create_table('turn_comments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('turn_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('slack_user_id', sa.String(255), nullable=True),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('source', feedbacksource_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['turn_id'], ['chat_turns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL')
    )
    op.create_index('idx_turn_comments_turn_id', 'turn_comments', ['turn_id'])
    op.create_index('idx_turn_comments_user_id', 'turn_comments', ['user_id'])
    op.create_index('idx_turn_comments_slack_user_id', 'turn_comments', ['slack_user_id'])
    op.create_index('idx_turn_comments_created_at', 'turn_comments', ['created_at'])

    # --- turn_steps ---
    op.create_table('turn_steps',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('turn_id', sa.String(), nullable=False),
        sa.Column('step_type', steptype_enum, nullable=False),
        sa.Column('tool_name', sa.String(100), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('status', stepstatus_enum, nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['turn_id'], ['chat_turns.id'], ondelete='CASCADE')
    )
    op.create_index('idx_turn_steps_turn', 'turn_steps', ['turn_id'])
    op.create_index('idx_turn_steps_turn_sequence', 'turn_steps', ['turn_id', 'sequence'])

    # =========================================================================
    # BILLING TABLES
    # =========================================================================

    # --- plans ---
    op.create_table('plans',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('plan_type', plantype_enum, nullable=False),
        sa.Column('stripe_price_id', sa.String(255), nullable=True),
        sa.Column('base_service_count', sa.Integer(), nullable=False, default=5),
        sa.Column('base_price_cents', sa.Integer(), nullable=False, default=0),
        sa.Column('additional_service_price_cents', sa.Integer(), nullable=False, default=500),
        sa.Column('rca_session_limit_daily', sa.Integer(), nullable=False, default=10),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # --- subscriptions ---
    op.create_table('subscriptions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('plan_id', sa.String(), nullable=False),
        sa.Column('stripe_customer_id', sa.String(255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
        sa.Column('status', subscriptionstatus_enum, nullable=False),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('billable_service_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id']),
        sa.UniqueConstraint('workspace_id')
    )
    op.create_index('idx_subscriptions_workspace', 'subscriptions', ['workspace_id'])
    op.create_index('idx_subscriptions_stripe_customer', 'subscriptions', ['stripe_customer_id'])
    op.create_index('idx_subscriptions_stripe_subscription', 'subscriptions', ['stripe_subscription_id'])
    op.create_index('idx_subscriptions_status', 'subscriptions', ['status'])

    # --- services ---
    op.create_table('services',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('team_id', sa.String(), nullable=True),
        sa.Column('repository_id', sa.String(), nullable=True),
        sa.Column('repository_name', sa.String(255), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['repository_id'], ['github_integrations.id'], ondelete='SET NULL')
    )
    op.create_index('uq_workspace_service_name', 'services', ['workspace_id', 'name'], unique=True)
    op.create_index('idx_services_workspace', 'services', ['workspace_id'])
    op.create_index('idx_services_team', 'services', ['team_id'])
    op.create_index('idx_services_repository', 'services', ['repository_id'])
    op.create_index('idx_services_enabled', 'services', ['enabled'])

    # --- llm_provider_configs ---
    op.create_table('llm_provider_configs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('provider', llmprovider_enum, nullable=False),
        sa.Column('model_name', sa.String(100), nullable=True),
        sa.Column('config_encrypted', sa.Text(), nullable=True),
        sa.Column('status', llmconfigstatus_enum, nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('workspace_id')
    )
    op.create_index('idx_llm_provider_config_workspace', 'llm_provider_configs', ['workspace_id'])
    op.create_index('idx_llm_provider_config_provider', 'llm_provider_configs', ['provider'])

    # =========================================================================
    # ENVIRONMENT & DEPLOYMENT TABLES
    # =========================================================================

    # --- environments ---
    op.create_table('environments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('workspace_id', 'name', name='uq_environment_workspace_name')
    )
    op.create_index('ix_environments_workspace_id', 'environments', ['workspace_id'])

    # --- environment_repositories ---
    op.create_table('environment_repositories',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('environment_id', sa.String(), nullable=False),
        sa.Column('repo_full_name', sa.String(255), nullable=False),
        sa.Column('branch_name', sa.String(255), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['environment_id'], ['environments.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('environment_id', 'repo_full_name', name='uq_env_repo')
    )
    op.create_index('ix_environment_repositories_environment_id', 'environment_repositories', ['environment_id'])

    # --- deployments ---
    op.create_table('deployments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('environment_id', sa.String(), nullable=False),
        sa.Column('repo_full_name', sa.String(255), nullable=False),
        sa.Column('branch', sa.String(255), nullable=True),
        sa.Column('commit_sha', sa.String(40), nullable=True),
        sa.Column('status', deploymentstatus_enum, nullable=False),
        sa.Column('source', deploymentsource_enum, nullable=False),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('extra_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['environment_id'], ['environments.id'], ondelete='CASCADE')
    )
    op.create_index('ix_deployments_env_repo_deployed', 'deployments', ['environment_id', 'repo_full_name', 'deployed_at'])
    op.create_index('ix_deployments_environment_id', 'deployments', ['environment_id'])

    # --- workspace_api_keys ---
    op.create_table('workspace_api_keys',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workspace_id', sa.String(), nullable=False),
        sa.Column('key_hash', sa.String(64), nullable=False),
        sa.Column('key_prefix', sa.String(8), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE')
    )
    op.create_index('ix_workspace_api_keys_workspace_id', 'workspace_api_keys', ['workspace_id'])
    op.create_index('ix_workspace_api_keys_key_hash', 'workspace_api_keys', ['key_hash'])

    # =========================================================================
    # SEED DATA: Plans
    # =========================================================================
    op.execute("""
        INSERT INTO plans (id, name, plan_type, stripe_price_id, base_service_count, base_price_cents, additional_service_price_cents, rca_session_limit_daily, is_active, created_at)
        SELECT 'plan_free', 'Free', 'FREE', NULL, 5, 0, 500, 10, true, now()
        WHERE NOT EXISTS (SELECT 1 FROM plans WHERE plan_type = 'FREE');
    """)
    op.execute("""
        INSERT INTO plans (id, name, plan_type, stripe_price_id, base_service_count, base_price_cents, additional_service_price_cents, rca_session_limit_daily, is_active, created_at)
        SELECT 'plan_pro', 'Pro', 'PRO', NULL, 5, 3000, 500, 100, true, now()
        WHERE NOT EXISTS (SELECT 1 FROM plans WHERE plan_type = 'PRO');
    """)


def downgrade():
    """Drop all tables in reverse dependency order."""

    # Drop tables in reverse order
    op.drop_table('workspace_api_keys')
    op.drop_table('deployments')
    op.drop_table('environment_repositories')
    op.drop_table('environments')
    op.drop_table('llm_provider_configs')
    op.drop_table('services')
    op.drop_table('subscriptions')
    op.drop_table('plans')
    op.drop_table('turn_steps')
    op.drop_table('turn_comments')
    op.drop_table('turn_feedbacks')
    op.drop_table('chat_files')
    op.drop_table('chat_turns')
    op.drop_table('chat_sessions')
    op.drop_table('rate_limit_tracking')
    op.drop_table('security_events')
    op.drop_table('jobs')
    op.drop_table('datadog_integrations')
    op.drop_table('newrelic_integrations')
    op.drop_table('aws_integrations')
    op.drop_table('github_integrations')
    op.drop_table('slack_installations')
    op.drop_table('grafana_integrations')
    op.drop_table('emails')
    op.drop_table('email_verifications')
    op.drop_table('refresh_tokens')
    op.drop_table('workspace_invitations')
    op.drop_table('team_membership')
    op.drop_table('teams')
    op.drop_table('memberships')
    op.drop_table('integrations')
    op.drop_table('users')
    op.drop_table('workspaces')

    # Drop enum types
    op.execute('DROP TYPE IF EXISTS securityeventtype')
    op.execute('DROP TYPE IF EXISTS subscriptionstatus')
    op.execute('DROP TYPE IF EXISTS plantype')
    op.execute('DROP TYPE IF EXISTS llmconfigstatus')
    op.execute('DROP TYPE IF EXISTS llmprovider')
    op.execute('DROP TYPE IF EXISTS deploymentsource')
    op.execute('DROP TYPE IF EXISTS deploymentstatus')
    op.execute('DROP TYPE IF EXISTS invitationstatus')
    op.execute('DROP TYPE IF EXISTS stepstatus')
    op.execute('DROP TYPE IF EXISTS steptype')
    op.execute('DROP TYPE IF EXISTS turnstatus')
    op.execute('DROP TYPE IF EXISTS feedbacksource')
    op.execute('DROP TYPE IF EXISTS jobsource')
    op.execute('DROP TYPE IF EXISTS jobstatus')
    op.execute('DROP TYPE IF EXISTS role')
