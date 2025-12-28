"""
Pydantic schemas for environments endpoints.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# Request schemas
class EnvironmentCreate(BaseModel):
    """Request to create a new environment."""

    workspace_id: str = Field(..., description="Workspace ID")
    name: str = Field(..., min_length=1, max_length=255, description="Environment name")
    is_default: bool = Field(
        default=False, description="Whether this is the default environment for RCA"
    )
    auto_discovery_enabled: bool = Field(
        default=True, description="Whether to auto-add new repos when discovered"
    )


class EnvironmentUpdate(BaseModel):
    """Request to update an environment."""

    name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="New environment name"
    )
    auto_discovery_enabled: Optional[bool] = Field(
        None, description="Whether to auto-add new repos"
    )


# Response schemas
class EnvironmentRepositoryResponse(BaseModel):
    """Response for a repository configuration within an environment."""

    id: str
    repo_full_name: str
    branch_name: Optional[str] = None
    is_enabled: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EnvironmentResponse(BaseModel):
    """Response for an environment."""

    id: str
    workspace_id: str
    name: str
    is_default: bool
    auto_discovery_enabled: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    repository_configs: List[EnvironmentRepositoryResponse] = []

    class Config:
        from_attributes = True


class EnvironmentSummaryResponse(BaseModel):
    """Summary response for an environment (without repository configs)."""

    id: str
    workspace_id: str
    name: str
    is_default: bool
    auto_discovery_enabled: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EnvironmentListResponse(BaseModel):
    """Response for listing environments."""

    environments: List[EnvironmentSummaryResponse]
