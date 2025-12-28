"""
Billing domain schemas for Service management.
"""

from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Optional


# Constants
FREE_TIER_SERVICE_LIMIT = 5


# Request Schemas
class ServiceCreate(BaseModel):
    """Schema for creating a new service."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Service name (should match what appears in observability logs)",
    )
    repository_name: Optional[str] = Field(
        None,
        max_length=255,
        description="Optional repository name to link (format: owner/repo)",
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
    enabled: Optional[bool] = Field(None, description="Whether the service is enabled")


# Response Schemas
class ServiceResponse(BaseModel):
    """Schema for service response."""

    id: str
    workspace_id: str
    name: str
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None
    enabled: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ServiceListResponse(BaseModel):
    """Schema for list of services with metadata."""

    services: list[ServiceResponse]
    total_count: int
    limit: int = Field(
        default=FREE_TIER_SERVICE_LIMIT,
        description="Maximum services allowed in current tier",
    )
    limit_reached: bool = Field(
        default=False, description="True if at tier limit and cannot add more"
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
