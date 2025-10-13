"""
Unified database models for the application.
All SQLAlchemy models are defined here.
"""

from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Enum, Integer, Text, Index
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

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


class GrafanaIntegration(Base):
    __tablename__ = "grafana_integrations"

    id = Column(String, primary_key=True)
    vm_workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
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
    installed_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
class GitHubIntegration(Base):
    __tablename__ = "github_integrations"

    id = Column(String, primary_key=True)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)

    github_user_id = Column(String, nullable=False)
    github_username = Column(String, nullable=False)
    installation_id = Column(String, nullable=False)
    scopes = Column(String, nullable=True)

    # Access token storage
    access_token = Column(String, nullable=True)  # GitHub installation access token
    token_expires_at = Column(DateTime(timezone=True), nullable=True)  # Token expiry time

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace = relationship("Workspace", backref="github_integrations")


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
    slack_integration_id = Column(String, ForeignKey("slack_installations.id"), nullable=True)
    trigger_channel_id = Column(String, nullable=True)  # Slack channel ID (C...)
    trigger_thread_ts = Column(String, nullable=True)  # Root thread timestamp
    trigger_message_ts = Column(String, nullable=True)  # Message timestamp that triggered bot

    # Lifecycle
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.QUEUED)
    priority = Column(Integer, default=0)  # Higher = more important
    retries = Column(Integer, default=0)  # Number of retry attempts
    max_retries = Column(Integer, default=3)  # Maximum retry attempts
    backoff_until = Column(DateTime(timezone=True), nullable=True)  # Don't retry before this time

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
        Index('idx_jobs_workspace_status', 'vm_workspace_id', 'status'),
        Index('idx_jobs_slack_integration', 'slack_integration_id'),
        Index('idx_jobs_created_at', 'created_at'),
    )
    

class RepositoryService(Base):
    __tablename__ = "repository_services"

    id = Column(String, primary_key=True)  # UUID
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    repo_name = Column(String, nullable=False)  # Full repo name (owner/repo)
    services = Column(JSON, nullable=False)  # Detected services (e.g., CI/CD, Docker, etc.)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    workspace = relationship("Workspace", backref="repository_services")

    # Unique constraint to prevent duplicate entries
    __table_args__ = (
        Index('idx_repo_workspace', 'workspace_id', 'repo_name', unique=True),
    )
    
