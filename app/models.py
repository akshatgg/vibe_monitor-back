"""
Unified database models for the application.
All SQLAlchemy models are defined here.
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import backref, relationship
from sqlalchemy.sql import func

from app.core.config import settings

Base = declarative_base()


# Enums
class Role(enum.Enum):
    OWNER = "owner"
    USER = "user"  # Renamed from MEMBER


class JobStatus(enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"


class JobSource(enum.Enum):
    """Source channel that triggered the job"""

    SLACK = "slack"
    WEB = "web"
    MSTEAMS = "msteams"  # Future


class FeedbackSource(enum.Enum):
    """Source of feedback (web UI or Slack)"""

    WEB = "web"
    SLACK = "slack"


class TurnStatus(enum.Enum):
    """Status of a chat turn"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StepType(enum.Enum):
    """Type of processing step within a turn"""

    TOOL_CALL = "tool_call"
    THINKING = "thinking"
    STATUS = "status"


class StepStatus(enum.Enum):
    """Status of a processing step"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InvitationStatus(enum.Enum):
    """Status of a workspace invitation"""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"


class DeploymentStatus(enum.Enum):
    """Status of a deployment"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentSource(enum.Enum):
    """Source that reported the deployment"""

    MANUAL = "manual"
    WEBHOOK = "webhook"
    GITHUB_ACTIONS = "github_actions"
    GITHUB_DEPLOYMENTS = "github_deployments"
    ARGOCD = "argocd"
    JENKINS = "jenkins"


class LLMProvider(enum.Enum):
    """Available LLM providers for BYOLLM"""

    VIBEMONITOR = "vibemonitor"  # Default (uses Groq)
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    GEMINI = "gemini"


class LLMConfigStatus(enum.Enum):
    """Status of LLM provider configuration"""

    ACTIVE = "active"
    ERROR = "error"
    UNCONFIGURED = "unconfigured"


# User and Workspace Models
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)

    # Authentication fields
    password_hash = Column(String, nullable=True)  # Null for Google OAuth users
    is_verified = Column(Boolean, default=False, nullable=False)

    # Preferences
    newsletter_subscribed = Column(Boolean, default=True, nullable=False)

    # Onboarding status (True when GitHub integrated to any owned workspace)
    is_onboarded = Column(Boolean, default=False, nullable=False)

    # Workspace tracking
    last_visited_workspace_id = Column(
        String, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    memberships = relationship("Membership", back_populates="user")
    team_memberships = relationship("TeamMembership", back_populates="user")
    last_visited_workspace = relationship(
        "Workspace", foreign_keys=[last_visited_workspace_id]
    )


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

    # Relationships - all with cascade delete to clean up when workspace is deleted
    memberships = relationship(
        "Membership", back_populates="workspace", cascade="all, delete-orphan"
    )
    teams = relationship(
        "Team", back_populates="workspace", cascade="all, delete-orphan"
    )
    grafana_integration = relationship(
        "GrafanaIntegration",
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    services = relationship(
        "Service", back_populates="workspace", cascade="all, delete-orphan"
    )
    subscription = relationship(
        "Subscription",
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    llm_config = relationship(
        "LLMProviderConfig",
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    environments = relationship(
        "Environment",
        back_populates="workspace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    api_keys = relationship(
        "WorkspaceApiKey", back_populates="workspace", cascade="all, delete-orphan"
    )


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    role = Column(
        Enum(Role, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=Role.USER,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="memberships")
    workspace = relationship("Workspace", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint(
            "user_id", "workspace_id", name="uq_membership_user_workspace"
        ),
    )


class Team(Base):
    """
    Represents a team within a workspace.
    Teams are used to organize users and services within a workspace.
    """

    __tablename__ = "teams"

    id = Column(String, primary_key=True)
    workspace_id = Column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)
    geography = Column(String(255), nullable=True)  # Team location/region
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="teams")
    memberships = relationship(
        "TeamMembership", back_populates="team", cascade="all, delete-orphan"
    )
    services = relationship("Service", back_populates="team")

    # Constraints and Indexes
    __table_args__ = (
        Index("uq_team_workspace_name", "workspace_id", "name", unique=True),
        Index("idx_teams_workspace", "workspace_id"),
        Index("idx_teams_name", "name"),
    )


class TeamMembership(Base):
    """
    Many-to-many relationship between Teams and Users.
    Tracks which users belong to which teams.
    """

    __tablename__ = "team_membership"

    id = Column(String, primary_key=True)
    team_id = Column(String, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    team = relationship("Team", back_populates="memberships")
    user = relationship("User", back_populates="team_memberships")

    # Constraints and Indexes
    __table_args__ = (
        Index("uq_team_membership", "team_id", "user_id", unique=True),
        Index("idx_team_membership_team", "team_id"),
        Index("idx_team_membership_user", "user_id"),
    )


class WorkspaceInvitation(Base):
    """
    Invitation to join a team workspace.
    Allows workspace owners to invite users by email.
    """

    __tablename__ = "workspace_invitations"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    inviter_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    invitee_email = Column(String, nullable=False)
    invitee_id = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )  # Null if user doesn't exist yet
    role = Column(
        Enum(Role, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=Role.USER,
    )
    status = Column(
        Enum(InvitationStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=InvitationStatus.PENDING,
    )

    # Token for email invitation link
    token = Column(String, unique=True, nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workspace = relationship(
        "Workspace", backref=backref("invitations", cascade="all, delete-orphan")
    )
    inviter = relationship(
        "User", foreign_keys=[inviter_id], backref="sent_invitations"
    )
    invitee = relationship(
        "User", foreign_keys=[invitee_id], backref="received_invitations"
    )

    # Indexes for query performance
    __table_args__ = (
        Index("idx_invitation_workspace", "workspace_id"),
        Index("idx_invitation_invitee_email", "invitee_email"),
        Index("idx_invitation_token", "token"),
        Index("idx_invitation_status", "status"),
        Index("idx_invitation_expires_at", "expires_at"),
    )


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
    workspace = relationship(
        "Workspace",
        backref=backref("github_integrations", cascade="all, delete-orphan"),
    )

    # Indexes and constraints
    __table_args__ = (
        Index("idx_github_integration_installation", "installation_id"),
        UniqueConstraint(
            "installation_id", name="uq_github_integrations_installation_id"
        ),
    )


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

    # Source channel (slack, web, msteams)
    source = Column(
        Enum(JobSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=JobSource.SLACK,
    )  # Default to slack for backward compatibility

    # Slack context
    slack_integration_id = Column(
        String, ForeignKey("slack_installations.id", ondelete="CASCADE"), nullable=True
    )
    trigger_channel_id = Column(String, nullable=True)  # Slack channel ID (C...)
    trigger_thread_ts = Column(String, nullable=True)  # Root thread timestamp
    trigger_message_ts = Column(
        String, nullable=True
    )  # Message timestamp that triggered bot

    # Lifecycle
    status = Column(
        Enum(JobStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=JobStatus.QUEUED,
    )
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
    workspace = relationship(
        "Workspace", backref=backref("jobs", cascade="all, delete-orphan")
    )
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
    workspace = relationship(
        "Workspace",
        backref=backref("rate_limit_tracking", cascade="all, delete-orphan"),
    )

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


class Email(Base):
    """
    Tracks emails sent to users.
    Stores which user was sent an email and when.
    """

    __tablename__ = "emails"

    id = Column(String, primary_key=True)  # UUID
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    sent_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )  # When the email was sent
    subject = Column(String, nullable=True)  # Email subject
    message_id = Column(String, nullable=True)  # Provider message ID for tracking
    status = Column(
        String, nullable=True
    )  # Status: 'sent', 'delivered', 'failed', etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="emails")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_emails_user", "user_id"),
        Index("idx_emails_sent_at", "sent_at"),
        Index("idx_emails_status", "status"),
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
    workspace = relationship(
        "Workspace", backref=backref("aws_integrations", cascade="all, delete-orphan")
    )

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
    workspace = relationship(
        "Workspace",
        backref=backref("newrelic_integrations", cascade="all, delete-orphan"),
    )


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
    workspace = relationship(
        "Workspace",
        backref=backref("datadog_integrations", cascade="all, delete-orphan"),
    )

    # Indexes for query performance
    __table_args__ = (Index("idx_datadog_integration_workspace", "workspace_id"),)


class SecurityEventType(enum.Enum):
    PROMPT_INJECTION = "prompt_injection"
    GUARD_DEGRADED = "guard_degraded"


class PlanType(enum.Enum):
    """Billing plan types"""

    FREE = "free"
    PRO = "pro"


class SubscriptionStatus(enum.Enum):
    """Subscription status mirroring Stripe's subscription states"""

    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    TRIALING = "trialing"


class SecurityEvent(Base):
    """
    Tracks security events such as prompt injection attempts and guard degradation.
    Used for monitoring and alerting on security threats.
    """

    __tablename__ = "security_events"

    id = Column(String, primary_key=True)

    # Event classification
    event_type = Column(
        Enum(SecurityEventType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    severity = Column(
        String, nullable=False
    )  # e.g., 'low', 'medium', 'high', 'critical'

    # Context
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True)
    slack_integration_id = Column(
        String, ForeignKey("slack_installations.id", ondelete="CASCADE"), nullable=True
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
    workspace = relationship(
        "Workspace", backref=backref("security_events", cascade="all, delete-orphan")
    )
    slack_integration = relationship("SlackInstallation", backref="security_events")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_security_events_type", "event_type"),
        Index("idx_security_events_workspace", "workspace_id"),
        Index("idx_security_events_detected_at", "detected_at"),
        Index("idx_security_events_slack_user", "slack_user_id"),
        Index("idx_security_events_slack_integration", "slack_integration_id"),
    )


# Chat Models
class ChatSession(Base):
    """
    A conversation session between a user and the RCA bot within a workspace.
    Contains multiple turns (question/answer pairs).

    Unified model for both Web and Slack:
    - Web: session_id (UUID), user_id references users table
    - Slack: team_id + channel_id + thread_ts, slack_user_id for Slack user
    """

    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    # Source channel (web, slack, msteams)
    source = Column(
        Enum(JobSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=JobSource.WEB,
    )

    # Web user (nullable - Slack users aren't in our users table)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)

    # Slack-specific identifiers (nullable for web sessions)
    slack_team_id = Column(String, nullable=True)
    slack_channel_id = Column(String, nullable=True)
    slack_thread_ts = Column(String, nullable=True)  # Identifies the thread
    slack_user_id = Column(String, nullable=True)  # Slack user who started it

    # Session metadata
    title = Column(
        String(255), nullable=True
    )  # Auto-generated from first message, user can rename

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship(
        "Workspace", backref=backref("chat_sessions", cascade="all, delete-orphan")
    )
    user = relationship("User", backref="chat_sessions")
    turns = relationship(
        "ChatTurn", back_populates="session", cascade="all, delete-orphan"
    )

    # Indexes for query performance
    __table_args__ = (
        Index("idx_chat_sessions_workspace", "workspace_id"),
        Index("idx_chat_sessions_user", "user_id"),
        Index("idx_chat_sessions_workspace_user", "workspace_id", "user_id"),
        Index("idx_chat_sessions_created_at", "created_at"),
        Index("idx_chat_sessions_source", "source"),
        # Unique constraint for Slack threads
        Index(
            "idx_chat_sessions_slack_thread",
            "slack_team_id",
            "slack_channel_id",
            "slack_thread_ts",
            unique=True,
            postgresql_where=text("source = 'slack'"),
        ),
    )


class ChatTurn(Base):
    """
    A single turn in a chat conversation: user message + bot response.
    Feedback is stored in separate tables (turn_feedbacks, turn_comments).
    """

    __tablename__ = "chat_turns"

    id = Column(String, primary_key=True)  # UUID
    session_id = Column(
        String, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )

    # User's question/message
    user_message = Column(Text, nullable=False)

    # Bot's final response (filled when processing completes)
    final_response = Column(Text, nullable=True)

    # Processing status
    status = Column(
        Enum(TurnStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TurnStatus.PENDING,
    )

    # Link to the RCA job that processes this turn
    job_id = Column(String, ForeignKey("jobs.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    session = relationship("ChatSession", back_populates="turns")
    job = relationship("Job", backref="chat_turn")
    steps = relationship(
        "TurnStep", back_populates="turn", cascade="all, delete-orphan"
    )
    feedbacks = relationship(
        "TurnFeedback", back_populates="turn", cascade="all, delete-orphan"
    )
    comments = relationship(
        "TurnComment", back_populates="turn", cascade="all, delete-orphan"
    )
    files = relationship(
        "ChatFile", back_populates="turn", cascade="all, delete-orphan"
    )

    @property
    def attachments(self):
        """Compute attachments from files relationship for API compatibility."""
        if not self.files:
            return None
        return [
            {
                "name": file.filename,
                "size": file.size_bytes,
                "relative_path": file.relative_path,
                "file_id": file.id,
                "s3_key": file.s3_key,
            }
            for file in self.files
        ]

    # Indexes for query performance
    __table_args__ = (
        Index("idx_chat_turns_session", "session_id"),
        Index("idx_chat_turns_job", "job_id"),
        Index("idx_chat_turns_status", "status"),
        Index("idx_chat_turns_created_at", "created_at"),
    )


class ChatFile(Base):
    """
    File uploaded in chat, stored in S3.
    Linked to a chat turn with metadata and extracted text for search.
    """

    __tablename__ = "chat_files"

    id = Column(String, primary_key=True)  # UUID
    turn_id = Column(
        String, ForeignKey("chat_turns.id", ondelete="CASCADE"), nullable=False
    )

    # S3 storage
    s3_bucket = Column(String, nullable=False)
    s3_key = Column(String, nullable=False)

    # File metadata
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    relative_path = Column(String(500), nullable=True)

    extracted_text = Column(Text, nullable=True)

    # Audit
    uploaded_by = Column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    turn = relationship("ChatTurn", back_populates="files")
    uploader = relationship("User")

    # for query performance
    __table_args__ = (
        Index("idx_chat_files_turn_id", "turn_id"),
        Index("idx_chat_files_uploaded_by", "uploaded_by"),
        Index("idx_chat_files_created_at", "created_at"),
    )


class TurnFeedback(Base):
    """
    Individual feedback (thumbs up/down) on a chat turn.
    Supports multiple users giving feedback on the same turn.
    """

    __tablename__ = "turn_feedbacks"

    id = Column(String, primary_key=True)  # UUID
    turn_id = Column(
        String, ForeignKey("chat_turns.id", ondelete="CASCADE"), nullable=False
    )

    # User identification (one of these should be set)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    slack_user_id = Column(String(255), nullable=True)  # For Slack users not in our DB

    # Feedback
    is_positive = Column(
        Boolean, nullable=False
    )  # True = thumbs up, False = thumbs down

    # Source tracking
    source = Column(
        Enum(FeedbackSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=FeedbackSource.WEB,
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    turn = relationship("ChatTurn", back_populates="feedbacks")
    user = relationship("User")

    # Indexes and constraints
    __table_args__ = (
        Index("idx_turn_feedbacks_turn_id", "turn_id"),
        Index("idx_turn_feedbacks_user_id", "user_id"),
        Index("idx_turn_feedbacks_slack_user_id", "slack_user_id"),
        # One feedback per web user per turn
        UniqueConstraint("turn_id", "user_id", name="uq_turn_feedback_user"),
        # One feedback per Slack user per turn
        UniqueConstraint(
            "turn_id", "slack_user_id", name="uq_turn_feedback_slack_user"
        ),
    )


class TurnComment(Base):
    """
    Comments on a chat turn.
    Supports multiple comments from multiple users on the same turn.
    """

    __tablename__ = "turn_comments"

    id = Column(String, primary_key=True)  # UUID
    turn_id = Column(
        String, ForeignKey("chat_turns.id", ondelete="CASCADE"), nullable=False
    )

    # User identification (one of these should be set)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    slack_user_id = Column(String(255), nullable=True)  # For Slack users not in our DB

    # Comment content
    comment = Column(Text, nullable=False)

    # Source tracking
    source = Column(
        Enum(FeedbackSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=FeedbackSource.WEB,
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    turn = relationship("ChatTurn", back_populates="comments")
    user = relationship("User")

    # Indexes
    __table_args__ = (
        Index("idx_turn_comments_turn_id", "turn_id"),
        Index("idx_turn_comments_user_id", "user_id"),
        Index("idx_turn_comments_slack_user_id", "slack_user_id"),
        Index("idx_turn_comments_created_at", "created_at"),
    )


class TurnStep(Base):
    """
    Individual processing steps within a turn.
    Used for SSE streaming to show progress (tool calls, thinking, etc.).
    """

    __tablename__ = "turn_steps"

    id = Column(String, primary_key=True)  # UUID
    turn_id = Column(
        String, ForeignKey("chat_turns.id", ondelete="CASCADE"), nullable=False
    )

    # Step details
    step_type = Column(
        Enum(StepType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    tool_name = Column(String(100), nullable=True)  # For tool_call type
    content = Column(Text, nullable=True)  # Step output/content

    # Processing status
    status = Column(
        Enum(StepStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=StepStatus.PENDING,
    )

    # Ordering
    sequence = Column(Integer, nullable=False)  # Order of steps within turn

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    turn = relationship("ChatTurn", back_populates="steps")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_turn_steps_turn", "turn_id"),
        Index("idx_turn_steps_turn_sequence", "turn_id", "sequence"),
    )


# Billing Models
class Service(Base):
    """
    Represents a billable service within a workspace.
    Services are the billing unit for the platform:
    - Free tier: 5 services
    - Paid tier: $30/month for 5 services + $5/month per additional service

    Service names should match what appears in observability logs/traces.
    One service can be linked to one repository (optional).
    One repository can have multiple services.
    """

    __tablename__ = "services"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String(255), nullable=False)

    # Optional team assignment (one service -> one team, one team -> many services)
    team_id = Column(String, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)

    # Optional repository link (one service -> one repo, but one repo -> many services)
    repository_id = Column(
        String, ForeignKey("github_integrations.id", ondelete="SET NULL"), nullable=True
    )
    repository_name = Column(String(255), nullable=True)  # Denormalized for display

    # Status
    enabled = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="services")
    team = relationship("Team", back_populates="services")
    repository = relationship("GitHubIntegration", backref="services")

    # Constraints and Indexes
    __table_args__ = (
        Index("uq_workspace_service_name", "workspace_id", "name", unique=True),
        Index("idx_services_workspace", "workspace_id"),
        Index("idx_services_team", "team_id"),
        Index("idx_services_repository", "repository_id"),
        Index("idx_services_enabled", "enabled"),
    )


class Plan(Base):
    """
    Billing plans - seeded data, rarely changes.
    Defines the pricing tiers for VibeMonitor.
    """

    __tablename__ = "plans"

    id = Column(String, primary_key=True)  # UUID
    name = Column(String(50), unique=True, nullable=False)  # "Free", "Pro"
    plan_type = Column(
        Enum(PlanType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )
    stripe_price_id = Column(String(255), nullable=True)  # Null for free plan
    base_service_count = Column(Integer, default=5, nullable=False)  # Included services
    base_price_cents = Column(Integer, default=0, nullable=False)  # 3000 = $30.00
    additional_service_price_cents = Column(
        Integer, default=500, nullable=False
    )  # 500 = $5.00 per additional service
    rca_session_limit_daily = Column(
        Integer, default=10, nullable=False
    )  # Daily RCA session limit
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    subscriptions = relationship("Subscription", back_populates="plan")


class Subscription(Base):
    """
    Workspace subscriptions - one per workspace.
    Tracks the billing relationship between a workspace and Stripe.
    """

    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False)

    # Stripe identifiers
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)

    # Subscription state
    status = Column(
        Enum(SubscriptionStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
    )
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)

    # Service tracking for billing
    billable_service_count = Column(
        Integer, default=0, nullable=False
    )  # Services above base

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="subscription")
    plan = relationship("Plan", back_populates="subscriptions")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_subscriptions_workspace", "workspace_id"),
        Index("idx_subscriptions_stripe_customer", "stripe_customer_id"),
        Index("idx_subscriptions_stripe_subscription", "stripe_subscription_id"),
        Index("idx_subscriptions_status", "status"),
    )


class LLMProviderConfig(Base):
    """
    Workspace-level LLM provider configuration for BYOLLM (Bring Your Own LLM).

    Allows workspace owners to configure their own LLM provider (OpenAI, Azure OpenAI,
    Google Gemini) instead of using VibeMonitor's default AI (Groq).

    Benefits:
    - BYOLLM users: No rate limits on AI sessions
    - VibeMonitor AI users: Subject to workspace.daily_request_limit

    API keys are encrypted using Fernet symmetric encryption (TokenProcessor).
    """

    __tablename__ = "llm_provider_configs"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One config per workspace
    )

    # Provider: 'vibemonitor' | 'openai' | 'azure_openai' | 'gemini'
    provider = Column(
        Enum(LLMProvider, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=LLMProvider.VIBEMONITOR,
    )

    # Model name (e.g., "gpt-4-turbo", "gemini-1.5-pro")
    # Null means use default model for the provider
    model_name = Column(String(100), nullable=True)

    # Encrypted JSON config blob containing API keys and provider-specific settings
    # Use TokenProcessor.encrypt() before storing, TokenProcessor.decrypt() when reading
    # Structure varies by provider:
    # - OpenAI: {"api_key": "sk-..."}
    # - Azure OpenAI: {"api_key": "...", "endpoint": "https://xxx.openai.azure.com/",
    #                  "api_version": "2024-02-01", "deployment_name": "gpt-4"}
    # - Gemini: {"api_key": "AIza..."}
    # - VibeMonitor: {} (no config needed, uses global settings)
    config_encrypted = Column(Text, nullable=True)

    # Status: 'active' | 'error' | 'unconfigured'
    status = Column(
        Enum(LLMConfigStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=LLMConfigStatus.ACTIVE,
    )

    # Verification tracking
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="llm_config")

    # Indexes for query performance
    __table_args__ = (
        Index("idx_llm_provider_config_workspace", "workspace_id"),
        Index("idx_llm_provider_config_provider", "provider"),
    )


# Environment Models
class Environment(Base):
    """
    Deployment environment configuration for a workspace.
    Examples: Production, Staging, Development.

    Environments allow workspace owners to define deployment contexts that map
    to specific branches in their GitHub repositories. This enables the RCA bot
    to query the correct code version based on the environment context from logs.
    """

    __tablename__ = "environments"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(
        String(255), nullable=False
    )  # e.g., "Production", "Staging", "Development"
    is_default = Column(
        Boolean, default=False, nullable=False
    )  # Only one per workspace can be default

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="environments")
    repository_configs = relationship(
        "EnvironmentRepository",
        back_populates="environment",
        cascade="all, delete-orphan",
    )

    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_environment_workspace_name"),
        Index("ix_environments_workspace_id", "workspace_id"),
    )


class EnvironmentRepository(Base):
    """
    Repository configuration within an environment.
    Links a repository to an environment for deployment tracking.

    Branch is optional context - the commit SHA in deployments is the
    source of truth for identifying deployed code.
    When auto_discovery_enabled is true on the parent Environment,
    new repositories are automatically added here when discovered.
    """

    __tablename__ = "environment_repositories"

    id = Column(String, primary_key=True)  # UUID
    environment_id = Column(
        String, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    repo_full_name = Column(String(255), nullable=False)  # e.g., "owner/repo-name"
    branch_name = Column(
        String(255), nullable=True
    )  # Optional context, e.g., "main", "develop"
    is_enabled = Column(
        Boolean, default=True, nullable=False
    )  # Whether repo is active in this environment

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    environment = relationship("Environment", back_populates="repository_configs")

    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint("environment_id", "repo_full_name", name="uq_env_repo"),
        Index("ix_environment_repositories_environment_id", "environment_id"),
    )


class Deployment(Base):
    """
    Deployment record tracking which branch/commit is deployed to an environment.

    Each deployment record represents a point in time when code was deployed.
    This enables RCA to query the correct code version based on what was
    actually deployed, rather than just what branch is configured.
    """

    __tablename__ = "deployments"

    id = Column(String, primary_key=True)  # UUID
    environment_id = Column(
        String, ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    repo_full_name = Column(String(255), nullable=False)  # e.g., "owner/repo-name"
    branch = Column(String(255), nullable=True)  # The deployed branch
    commit_sha = Column(String(40), nullable=True)  # The specific commit SHA
    status = Column(
        Enum(DeploymentStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DeploymentStatus.SUCCESS,
    )
    source = Column(
        Enum(DeploymentSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DeploymentSource.MANUAL,
    )
    deployed_at = Column(
        DateTime(timezone=True), nullable=True
    )  # When deployment occurred
    extra_data = Column(JSON, nullable=True)  # Flexible field for CI/CD specific data

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    environment = relationship(
        "Environment", backref=backref("deployments", passive_deletes=True)
    )

    # Indexes for fast "latest deployment" queries
    __table_args__ = (
        Index(
            "ix_deployments_env_repo_deployed",
            "environment_id",
            "repo_full_name",
            "deployed_at",
        ),
        Index("ix_deployments_environment_id", "environment_id"),
    )


class WorkspaceApiKey(Base):
    """
    API keys for workspace-level authentication.

    Used primarily for CI/CD webhook authentication to report deployments.
    Keys are stored as SHA-256 hashes for security.
    """

    __tablename__ = "workspace_api_keys"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    key_hash = Column(String(64), nullable=False)  # SHA-256 hash of the key
    key_prefix = Column(String(8), nullable=False)  # First 8 chars for identification
    name = Column(String(100), nullable=False)  # e.g., "CI/CD Webhook Key"
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="api_keys")

    # Indexes
    __table_args__ = (
        Index("ix_workspace_api_keys_workspace_id", "workspace_id"),
        Index("ix_workspace_api_keys_key_hash", "key_hash"),
    )
