from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, validator


class SlackEventPayload(BaseModel):
    """
    Pydantic model for parsing Slack event payload
    Handles app_mention and message events
    """

    token: str
    team_id: str
    api_app_id: str
    event: Dict[str, Any]
    type: str
    event_id: str
    event_time: int

    @validator("event")
    def validate_event(cls, event):
        """
        Validate and extract key event information
        Ensure event has required fields

        Note: 'text' field is optional for certain message subtypes:
        - message_changed (edits)
        - file_share (file uploads)
        - message_deleted
        """
        # Text is optional if files are present (image-only messages)
        required_fields = ["type", "ts", "channel"]
        for field in required_fields:
            if field not in event:
                raise ValueError(f"Missing required event field: {field}")

        # Check if this is a message subtype that may not have text
        subtype = event.get("subtype")
        has_text = "text" in event and event["text"]

        # Allow messages with subtypes to not have text field
        # Only require text for regular messages (no subtype)
        if not has_text and not subtype:
            raise ValueError("Missing required event field: text")

        # If message has a subtype, it's valid even without text
        # (e.g., message_changed, file_share, message_deleted)
        if subtype:
            return event

        # Security: Require either user or bot_id for message tracking
        # User messages have 'user', bot messages (Grafana/Sentry) have 'bot_id'
        if not subtype and "user" not in event and "bot_id" not in event:
            raise ValueError(
                "Message must have either 'user' or 'bot_id' for proper tracking"
            )

        # Ensure either text or files are present
        if not event.get("text") and not event.get("files"):
            raise ValueError("Message must have either 'text' or 'files'")

        return event

    def extract_message_context(self) -> Dict[str, Any]:
        """
        Extract context details from Slack event
        Captures both user_id (for human messages) and bot_id (for bot alerts)
        """
        files = self.event.get("files", [])

        return {
            "user_id": self.event.get("user"),
            "bot_id": self.event.get("bot_id"),  # For bot messages (Grafana/Sentry)
            "channel_id": self.event.get("channel"),
            "timestamp": self.event.get("ts"),
            "text": self.event.get("text", "").strip(),
            "team_id": self.team_id,
            "thread_ts": self.event.get(
                "thread_ts"
            ),  # Thread timestamp for threaded replies
            "files": files,  # Attachments/images from Slack message
        }


class SlackEventResponse(BaseModel):
    """
    Model for standardized Slack event response
    """

    status: str = "success"
    message: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class SlackWebhookPayload(BaseModel):
    """
    Model for sending data to external webhook
    """

    event_context: Dict[str, Any]
    processed_at: str = Field(default_factory=lambda: str(datetime.now(timezone.utc)))

    def to_webhook_payload(self) -> Dict[str, Any]:
        """
        Transform Slack event context for external webhook
        """
        return {"source": "slack_bot", **self.event_context}


# OAuth Response Models
class SlackOAuthTeam(BaseModel):
    """Slack OAuth team information"""

    id: str
    name: str


class SlackOAuthResponse(BaseModel):
    """Response from Slack OAuth token exchange"""

    ok: bool
    access_token: str
    token_type: str = "bot"
    scope: str
    bot_user_id: Optional[str] = None
    app_id: str
    team: SlackOAuthTeam
    enterprise: Optional[Dict[str, Any]] = None
    authed_user: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# Installation Data Models
class SlackInstallationCreate(BaseModel):
    """Schema for creating a new Slack installation"""

    team_id: str
    team_name: str
    access_token: str
    bot_user_id: Optional[str] = None
    scope: str
    workspace_id: Optional[str] = None


class SlackInstallationResponse(BaseModel):
    """Schema for Slack installation response (includes access_token for internal use)"""

    id: str
    team_id: str
    team_name: str
    access_token: str  # Only used internally, never exposed in API responses
    bot_user_id: Optional[str] = None
    scope: str
    workspace_id: Optional[str] = None
    installed_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SlackInstallationPublic(BaseModel):
    """Public-facing installation data (without token)"""

    id: str
    team_id: str
    team_name: str
    bot_user_id: Optional[str] = None
    scope: str
    installed_at: datetime

    class Config:
        from_attributes = True
