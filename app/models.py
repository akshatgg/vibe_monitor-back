"""
Unified database models for the application.
All SQLAlchemy models are defined here.
"""

from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

Base = declarative_base()


# Enums
class Role(enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


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