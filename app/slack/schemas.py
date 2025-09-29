from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime


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
    
    @validator('event')
    def validate_event(cls, event):
        """
        Validate and extract key event information
        Ensure event has required fields
        """
        required_fields = ['type', 'user', 'text', 'ts', 'channel']
        for field in required_fields:
            if field not in event:
                raise ValueError(f"Missing required event field: {field}")
        return event

    def extract_message_context(self) -> Dict[str, Any]:
        """
        Extract context details from Slack event
        """
        return {
            "user_id": self.event.get('user'),
            "channel_id": self.event.get('channel'),
            "timestamp": self.event.get('ts'),
            "text": self.event.get('text', '').strip(),
            "team_id": self.team_id
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
    processed_at: str = Field(default_factory=lambda: str(datetime.utcnow()))
    
    def to_webhook_payload(self) -> Dict[str, Any]:
        """
        Transform Slack event context for external webhook
        """
        return {
            "source": "slack_bot",
            **self.event_context
        }