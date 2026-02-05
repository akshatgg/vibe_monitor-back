"""
Schemas for Review Orchestrator Service.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReviewGenerationRequest(BaseModel):
    """Request to generate a review."""

    review_id: str
    service_id: str
    workspace_id: str
    week_start: datetime
    week_end: datetime


class ReviewGenerationResult(BaseModel):
    """Result of review generation."""

    success: bool
    review_id: str
    error_message: Optional[str] = None
    generation_duration_seconds: Optional[int] = None
