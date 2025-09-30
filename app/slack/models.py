from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.onboarding.models.models import Base


class SlackInstallation(Base):
    """
    Stores Slack bot OAuth installation data for multi-workspace support

    Each installation represents a bot installed in a Slack workspace.
    The access_token is used to send messages and interact with that workspace.
    """
    __tablename__ = "slack_installations"

    id = Column(String, primary_key=True)  # UUID
    team_id = Column(String, unique=True, nullable=False)  # Slack workspace ID (e.g., T123456)
    team_name = Column(String, nullable=False)  # Slack workspace name
    access_token = Column(String, nullable=False)  # Bot OAuth token (xoxb-...) - TODO: Encrypt in production
    bot_user_id = Column(String, nullable=True)  # Slack bot user ID (e.g., U987654)
    scope = Column(String, nullable=True)  # OAuth scopes granted (e.g., "app_mentions:read,chat:write")
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=True)  # Optional link to internal workspace
    installed_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())