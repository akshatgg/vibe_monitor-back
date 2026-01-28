"""
Pydantic schemas for team-related requests and responses.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class TeamResponse(BaseModel):
    """Team response model."""

    id: str
    workspace_id: str
    name: str
    geography: Optional[str] = None
    membership_count: int = Field(default=0, description="Number of team members")
    service_count: int = Field(default=0, description="Number of services owned by team")
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TeamListResponse(BaseModel):
    """Response for listing teams with pagination."""

    teams: List[TeamResponse]
    total_count: int
    offset: int
    limit: int


class TeamDetailResponse(BaseModel):
    """Detailed team response with members and services."""

    id: str
    workspace_id: str
    name: str
    geography: Optional[str] = None
    membership_count: int
    service_count: int
    membership: List[dict] = Field(
        default_factory=list, description="List of team members with user details (TeamMembership join records)"
    )
    services: List[dict] = Field(
        default_factory=list, description="List of services owned by team"
    )
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TeamCreate(BaseModel):
    """Request model for creating a team."""

    name: str = Field(..., min_length=1, max_length=255)
    geography: Optional[str] = Field(None, max_length=255)
    membership_ids: Optional[List[str]] = Field(
        None, description="Optional list of user IDs to add to team"
    )


class TeamUpdate(BaseModel):
    """Request model for updating a team."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    geography: Optional[str] = Field(None, max_length=255)


class TeamMemberAdd(BaseModel):
    """Request model for adding a member to a team."""

    user_id: str


class TeamMemberResponse(BaseModel):
    """Team member response model."""

    id: str
    user: dict = Field(description="User details (id, name, email)")
    created_at: datetime

    class Config:
        from_attributes = True
