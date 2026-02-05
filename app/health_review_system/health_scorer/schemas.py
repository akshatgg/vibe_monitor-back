"""
Schemas for Health Scorer Service.
"""

from pydantic import BaseModel, Field


class HealthScores(BaseModel):
    """Health scores for a service."""

    overall: int = Field(ge=0, le=100)
    reliability: int = Field(ge=0, le=100)
    performance: int = Field(ge=0, le=100)
    observability: int = Field(ge=0, le=100)
