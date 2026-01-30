"""
Workspace domain schemas for Service management.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.workspace.client_workspace_teams.schemas import TeamSummaryResponse

# Constants
FREE_TIER_SERVICE_LIMIT = 5


# ============================================================================
# Service Schemas
# ============================================================================


class ServiceCreate(BaseModel):
    """Schema for creating a new service."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Service name (should match what appears in observability logs)",
    )
    repository_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Repository name to link (format: owner/repo)",
    )


class ServiceUpdate(BaseModel):
    """Schema for updating an existing service."""

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Service name (should match what appears in observability logs)",
    )
    repository_name: Optional[str] = Field(
        None,
        max_length=255,
        description="Repository name to link (format: owner/repo)",
    )
    team_id: Optional[str] = Field(
        None,
        description="Team ID to assign this service to (set to null to unassign)",
    )
    enabled: Optional[bool] = Field(None, description="Whether the service is enabled")


class ServiceResponse(BaseModel):
    """Schema for service response."""

    id: str
    workspace_id: str
    name: str
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None
    team_id: Optional[str] = None
    team: Optional[TeamSummaryResponse] = Field(
        None,
        description="Team details if service is assigned to a team"
    )
    enabled: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ServiceListResponse(BaseModel):
    """Schema for list of services with pagination metadata."""

    services: list[ServiceResponse]
    total_count: int
    offset: int = Field(default=0, description="Current pagination offset")
    limit: int = Field(
        default=FREE_TIER_SERVICE_LIMIT,
        description="Page size",
    )
    limit_reached: bool = Field(
        default=False, description="True if at service tier limit (for billing)"
    )
    service_limit: int = Field(
        default=FREE_TIER_SERVICE_LIMIT,
        description="Maximum services allowed in current tier"
    )


class ServiceCountResponse(BaseModel):
    """Schema for service count and limit information."""

    current_count: int
    limit: int = Field(
        default=FREE_TIER_SERVICE_LIMIT,
        description="Maximum services allowed in current tier",
    )
    can_add_more: bool = Field(
        default=True, description="Whether more services can be added"
    )
    is_paid: bool = Field(
        default=False, description="Whether workspace is on paid tier"
    )
