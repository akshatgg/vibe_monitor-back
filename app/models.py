"""
Unified database models for the application.
All SQLAlchemy models are defined here.
"""

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Enum,
    Integer,
    Text,
    Index,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.core.config import settings

Base = declarative_base()


# Enums
class Role(enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class JobStatus(enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"


# User and Workspace Models
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)

    # Authentication fields
    
    password_hash = Column(String, nullable=True)  # Null for Google OAuth users
    is_verified = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    memberships = relationship("Membership", back_populates="user")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    domain = Column(String, nullable=True)  # For company workspaces
    visible_to_org = Column(
        Boolean, default=False
    )  # If domain users can see this workspace
    is_paid = Column(Boolean, default=False)  # For future payment features
    daily_request_limit = Column(
        Integer, default=settings.DEFAULT_DAILY_REQUEST_LIMIT, nullable=False
    )  # Daily RCA request limit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    memberships = relationship("Membership", back_populates="workspace")
    grafana_integration = relationship(
        "GrafanaIntegration", back_populates="workspace", uselist=False
    )


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.MEMBER)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="memberships")
    workspace = relationship("Workspace", back_populates="memberships")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    token = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Integration(Base):
    """
    Unified integration control plane table.
    Tracks all integrations (GitHub, Grafana, AWS, etc.) for a workspace
    with their status and health information.

    The 'provider' column serves as both the provider name and type identifier
    (e.g., 'github', 'grafana', 'aws', 'datadog', 'newrelic', 'slack').
    """

    __tablename__ = "integrations"

    id = Column(String, primary_key=True)
    workspace_id = Column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )

    # Provider serves as both provider name and type
    provider = Column(
        String, nullable=False
    )  # 'github', 'grafana', 'aws', 'datadog', 'newrelic', 'slack'

    # Lifecycle
    status = Column(
        String, nullable=False, default="active"
    )  # 'active', 'disabled', 'error'
    health_status = Column(
        String, nullable=True
    )  # 'healthy' or 'failed', NULL means not yet checked

    # Verification
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Indexes defined in migration file


class EmailVerification(Base):
    """
    Stores email verification and password reset tokens.
    Supports both verification links and password reset flows.
    """

    __tablename__ = "email_verifications"

    id = Column(String, primary_key=True)  # UUID
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, nullable=False)  # Encrypted token for security
    token_hash = Column(
        String(64), nullable=True, index=True
    )  # SHA-256 hash for O(1) lookup
    token_type = Column(
        String, nullable=False
    )  # 'email_verification' or 'password_reset'
    expires_at = Column(DateTime(timezone=True), nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)  # NULL if not used yet
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", backref="email_verifications")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_email_verification_token", "token"),
        Index("idx_email_verification_user", "user_id"),
        Index("idx_email_verification_expires", "expires_at"),
    )


class GrafanaIntegration(Base):
    __tablename__ = "grafana_integrations"

    id = Column(String, primary_key=True)
    vm_workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    integration_id = Column(
        String, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    grafana_url = Column(String(500), nullable=False)
    api_token = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="grafana_integration")


# Slack Models
class SlackInstallation(Base):
    """
    Stores Slack bot OAuth installation data for multi-workspace support

    Each installation represents a bot installed in a Slack workspace.
    The access_token is used to send messages and interact with that workspace.
    """

    __tablename__ = "slack_installations"

    id = Column(String, primary_key=True)  # UUID
    team_id = Column(
        String, unique=True, nullable=False
    )  # Slack workspace ID (e.g., T123456)
    team_name = Column(String, nullable=False)  # Slack workspace name
    access_token = Column(
        String, nullable=False
    )  # Bot OAuth token (xoxb-...) - TODO: Encrypt in production
    bot_user_id = Column(String, nullable=True)  # Slack bot user ID (e.g., U987654)
    scope = Column(
        String, nullable=True
    )  # OAuth scopes granted (e.g., "app_mentions:read,chat:write")
    workspace_id = Column(
        String, ForeignKey("workspaces.id"), nullable=True
    )  # Optional link to internal workspace
    integration_id = Column(
        String, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=True
    )
    installed_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class GitHubIntegration(Base):
    __tablename__ = "github_integrations"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    integration_id = Column(
        String, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )

    github_user_id = Column(String, nullable=False)
    github_username = Column(String, nullable=False)
    installation_id = Column(String, nullable=False)
    scopes = Column(String, nullable=True)

    # Access token storage
    access_token = Column(String, nullable=True)  # GitHub installation access token
    token_expires_at = Column(
        DateTime(timezone=True), nullable=True
    )  # Token expiry time

    # Status tracking
    is_active = Column(Boolean, default=True, nullable=False)  # False when suspended

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace = relationship("Workspace", backref="github_integrations")

    # Indexes for query performance
    __table_args__ = (Index("idx_github_integration_installation", "installation_id"),)


# Job Orchestration Models
class Job(Base):
    """
    Job lifecycle tracking for RCA orchestration

    Tracks the full lifecycle of AI-powered RCA requests from Slack,
    including retry logic, status tracking, and error handling.
    """

    __tablename__ = "jobs"

    # Primary key
    id = Column(String, primary_key=True)  # UUID

    # Workspace link
    vm_workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    # Slack context
    slack_integration_id = Column(
        String, ForeignKey("slack_installations.id"), nullable=True
    )
    trigger_channel_id = Column(String, nullable=True)  # Slack channel ID (C...)
    trigger_thread_ts = Column(String, nullable=True)  # Root thread timestamp
    trigger_message_ts = Column(
        String, nullable=True
    )  # Message timestamp that triggered bot

    # Lifecycle
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.QUEUED)
    priority = Column(Integer, default=0)  # Higher = more important
    retries = Column(Integer, default=0)  # Number of retry attempts
    max_retries = Column(
        Integer, default=settings.MAX_JOB_RETRIES
    )  # Maximum retry attempts
    backoff_until = Column(
        DateTime(timezone=True), nullable=True
    )  # Don't retry before this time

    # Context + timing + error
    requested_context = Column(JSON, nullable=True)  # User query, context data
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", backref="jobs")
    slack_integration = relationship("SlackInstallation", backref="jobs")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_jobs_workspace_status", "vm_workspace_id", "status"),
        Index("idx_jobs_slack_integration", "slack_integration_id"),
        Index("idx_jobs_created_at", "created_at"),
    )


class RateLimitTracking(Base):
    """
    Universal rate limit tracking for any resource type.
    Supports multiple time windows and resource types.
    """

    __tablename__ = "rate_limit_tracking"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    resource_type = Column(String, nullable=False)  # e.g., 'rca_request', 'api_call'
    window_key = Column(
        String, nullable=False
    )  # e.g., '2025-10-15' (daily), '2025-10-15-14' (hourly)
    count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", backref="rate_limit_tracking")

    # Indexes
    __table_args__ = (
        Index(
            "idx_rate_limit_unique",
            "workspace_id",
            "resource_type",
            "window_key",
            unique=True,
        ),
        Index("idx_rate_limit_workspace", "workspace_id"),
        Index("idx_rate_limit_resource", "resource_type"),
    )


class MailgunEmail(Base):
    """
    Tracks emails sent via Mailgun.
    Stores which user was sent an email and when.
    """

    __tablename__ = "mailgun_emails"

    id = Column(String, primary_key=True)  # UUID
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    sent_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )  # When the email was sent
    subject = Column(String, nullable=True)  # Email subject
    message_id = Column(String, nullable=True)  # Mailgun message ID for tracking
    status = Column(
        String, nullable=True
    )  # Status: 'sent', 'delivered', 'failed', etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="mailgun_emails")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_mailgun_emails_user", "user_id"),
        Index("idx_mailgun_emails_sent_at", "sent_at"),
        Index("idx_mailgun_emails_status", "status"),
    )


class AWSIntegration(Base):
    """
    Stores AWS IAM role ARN and temporary STS credentials for workspace integrations.
    Uses AssumeRole to get temporary credentials instead of storing long-term keys.
    Credentials are encrypted before storage.
    """

    __tablename__ = "aws_integrations"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    integration_id = Column(
        String, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )

    # IAM Role ARN for AssumeRole
    role_arn = Column(
        String, nullable=False
    )  # e.g., arn:aws:iam::123456789012:role/VibeMonitor

    # External ID for secure cross-account access (encrypted)
    external_id = Column(String, nullable=True)  # Encrypted external ID for AssumeRole

    # Encrypted temporary STS credentials (from AssumeRole response)
    access_key_id = Column(String, nullable=False)  # Encrypted temporary access key
    secret_access_key = Column(String, nullable=False)  # Encrypted temporary secret key
    session_token = Column(String, nullable=False)  # Encrypted session token

    # Credential expiration tracking
    credentials_expiration = Column(
        DateTime(timezone=True), nullable=False
    )  # When STS credentials expire

    # Optional region configuration
    aws_region = Column(String, nullable=True, default="us-west-1")

    # Status tracking
    is_active = Column(Boolean, default=True, nullable=False)
    last_verified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", backref="aws_integrations")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_aws_integration_workspace", "workspace_id"),
        Index("idx_aws_integration_active", "is_active"),
    )


class NewRelicIntegration(Base):
    """
    Stores New Relic integration credentials for workspace integrations.
    API keys are encrypted before storage.
    """

    __tablename__ = "newrelic_integrations"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    integration_id = Column(
        String, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )

    # New Relic Account ID
    account_id = Column(String, nullable=False)

    # Encrypted New Relic User API Key (must start with NRAK)
    api_key = Column(String, nullable=False)  # Encrypted API key

    # Status tracking
    last_verified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", backref="newrelic_integrations")


class DatadogIntegration(Base):
    """
    Stores Datadog integration credentials for workspace integrations.
    API keys and App keys are encrypted before storage.
    """

    __tablename__ = "datadog_integrations"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    integration_id = Column(
        String, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )

    # Datadog API Key (organization-level)
    api_key = Column(String, nullable=False)  # Encrypted API key

    # Datadog Application Key (organization-level with permissions)
    app_key = Column(String, nullable=False)  # Encrypted App key

    # Datadog Region code (e.g., us1, us5, eu1, ap1)
    region = Column(String, nullable=False)

    # Status tracking
    last_verified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", backref="datadog_integrations")

    # Indexes for query performance
    __table_args__ = (Index("idx_datadog_integration_workspace", "workspace_id"),)


class SecurityEventType(enum.Enum):
    PROMPT_INJECTION = "prompt_injection"
    GUARD_DEGRADED = "guard_degraded"


class SecurityEvent(Base):
    """
    Tracks security events such as prompt injection attempts and guard degradation.
    Used for monitoring and alerting on security threats.
    """

    __tablename__ = "security_events"

    id = Column(String, primary_key=True)

    # Event classification
    event_type = Column(Enum(SecurityEventType), nullable=False)
    severity = Column(
        String, nullable=False
    )  # e.g., 'low', 'medium', 'high', 'critical'

    # Context
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True)
    slack_integration_id = Column(
        String, ForeignKey("slack_installations.id"), nullable=True
    )
    slack_user_id = Column(
        String, nullable=True
    )  # Slack user ID who triggered the event

    # Event details
    message_preview = Column(
        Text, nullable=True
    )  # Preview of the message that triggered the event
    guard_response = Column(
        String, nullable=True
    )  # "true", "false", or null for guard degradation
    reason = Column(String, nullable=True)  # Human-readable reason for the event
    event_metadata = Column(
        JSON, nullable=True
    )  # Additional context (error details, etc.)

    # Timestamp
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workspace = relationship("Workspace", backref="security_events")
    slack_integration = relationship("SlackInstallation", backref="security_events")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_security_events_type", "event_type"),
        Index("idx_security_events_workspace", "workspace_id"),
        Index("idx_security_events_detected_at", "detected_at"),
        Index("idx_security_events_slack_user", "slack_user_id"),
        Index("idx_security_events_slack_integration", "slack_integration_id"),
    )
