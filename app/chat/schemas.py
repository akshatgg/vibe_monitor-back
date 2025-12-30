"""
Pydantic schemas for chat endpoints.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models import StepStatus, StepType, TurnStatus


# Request schemas
class SendMessageRequest(BaseModel):
    """Request to send a chat message."""

    session_id: Optional[str] = Field(
        None, description="Existing session ID. If not provided, creates a new session."
    )
    message: str = Field(
        ..., min_length=1, max_length=10000, description="User message"
    )


class UpdateSessionRequest(BaseModel):
    """Request to update a session (e.g., rename)."""

    title: str = Field(
        ..., min_length=1, max_length=255, description="New session title"
    )


class SubmitFeedbackRequest(BaseModel):
    """Request to submit feedback on a turn."""

    is_positive: bool = Field(
        ..., description="True for thumbs up, False for thumbs down"
    )
    comment: Optional[str] = Field(
        None, max_length=1000, description="Optional feedback comment"
    )


# Response schemas
class TurnStepResponse(BaseModel):
    """Response for a single processing step."""

    id: str
    step_type: StepType
    tool_name: Optional[str] = None
    content: Optional[str] = None
    status: StepStatus
    sequence: int
    created_at: datetime

    class Config:
        from_attributes = True


class ChatTurnResponse(BaseModel):
    """Response for a single chat turn."""

    id: str
    session_id: str
    user_message: str
    final_response: Optional[str] = None
    status: TurnStatus
    job_id: Optional[str] = None
    feedback_score: Optional[int] = None
    feedback_comment: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    steps: List[TurnStepResponse] = []

    class Config:
        from_attributes = True


class ChatTurnSummary(BaseModel):
    """Summary of a turn (without steps, for session list)."""

    id: str
    user_message: str
    final_response: Optional[str] = None
    status: TurnStatus
    feedback_score: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatSessionResponse(BaseModel):
    """Response for a chat session."""

    id: str
    workspace_id: str
    user_id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    turns: List[ChatTurnSummary] = []

    class Config:
        from_attributes = True


class ChatSessionSummary(BaseModel):
    """Summary of a session (for list view)."""

    id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    turn_count: int = 0
    last_message_preview: Optional[str] = None

    class Config:
        from_attributes = True


class SendMessageResponse(BaseModel):
    """Response after sending a message."""

    turn_id: str
    session_id: str
    message: str = "Message received. Connect to SSE endpoint to stream response."


class FeedbackResponse(BaseModel):
    """Response after submitting feedback."""

    turn_id: str
    is_positive: bool
    comment: Optional[str] = None
    message: str = "Feedback submitted successfully."


# SSE Event schemas
class SSEEvent(BaseModel):
    """Base SSE event."""

    event: str
    data: dict


class SSEStatusEvent(BaseModel):
    """Status update event."""

    event: str = "status"
    content: str


class SSEToolStartEvent(BaseModel):
    """Tool execution started event."""

    event: str = "tool_start"
    tool_name: str
    step_id: str


class SSEToolEndEvent(BaseModel):
    """Tool execution completed event."""

    event: str = "tool_end"
    tool_name: str
    status: str
    content: Optional[str] = None


class SSECompleteEvent(BaseModel):
    """Processing complete event."""

    event: str = "complete"
    final_response: str


class SSEErrorEvent(BaseModel):
    """Error event."""

    event: str = "error"
    message: str


# Search schemas
class ChatSearchResult(BaseModel):
    """Search result for a chat session."""

    session_id: str
    title: Optional[str] = None
    matched_content: str
    match_type: str  # 'title' or 'message'
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatSearchResponse(BaseModel):
    """Response for chat search."""

    results: List[ChatSearchResult] = []
