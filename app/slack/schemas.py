from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime, timezone


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
        """
        required_fields = ["type", "user", "text", "ts", "channel"]
        for field in required_fields:
            if field not in event:
                raise ValueError(f"Missing required event field: {field}")
        return event

    def extract_message_context(self) -> Dict[str, Any]:
        """
        Extract context details from Slack event
        """
        return {
            "user_id": self.event.get("user"),
            "channel_id": self.event.get("channel"),
            "timestamp": self.event.get("ts"),
            "text": self.event.get("text", "").strip(),
            "team_id": self.team_id,
            "thread_ts": self.event.get(
                "thread_ts"
            ),  # Thread timestamp for threaded replies
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
