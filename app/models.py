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
    UniqueConstraint,
    text,
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


class JobSource(enum.Enum):
    """Source channel that triggered the job"""

    SLACK = "slack"
    WEB = "web"
    MSTEAMS = "msteams"  # Future


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
    environments = relationship(
        "Environment", back_populates="workspace", cascade="all, delete-orphan"
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

    # Source channel (slack, web, msteams)
    source = Column(
        Enum(JobSource, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=JobSource.SLACK,
    )  # Default to slack for backward compatibility

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
    workspace = relationship("Workspace", backref="chat_sessions")
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
    Feedback is collected at the turn level, not individual message level.
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

    # Feedback (at turn level)
    feedback_score = Column(Integer, nullable=True)  # 1 = thumbs down, 5 = thumbs up
    feedback_comment = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    session = relationship("ChatSession", back_populates="turns")
    job = relationship("Job", backref="chat_turn")
    steps = relationship(
        "TurnStep", back_populates="turn", cascade="all, delete-orphan"
    )

    # Indexes for query performance
    __table_args__ = (
        Index("idx_chat_turns_session", "session_id"),
        Index("idx_chat_turns_job", "job_id"),
        Index("idx_chat_turns_status", "status"),
        Index("idx_chat_turns_created_at", "created_at"),
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
    auto_discovery_enabled = Column(
        Boolean, default=True, nullable=False
    )  # Auto-add new repos when discovered

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
    Maps a repository to a specific branch for that environment.

    Repositories are disabled by default until a branch is configured.
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
    )  # e.g., "main", "develop" - nullable until configured
    is_enabled = Column(
        Boolean, default=False, nullable=False
    )  # Disabled until branch configured

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
