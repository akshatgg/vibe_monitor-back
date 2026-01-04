"""
Pydantic schemas for environments endpoints.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# Request schemas
class EnvironmentCreate(BaseModel):
    """Request to create a new environment."""

    name: str = Field(..., min_length=1, max_length=255, description="Environment name")
    is_default: bool = Field(
        default=False, description="Whether this is the default environment for RCA"
    )


class EnvironmentUpdate(BaseModel):
    """Request to update an environment."""

    name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="New environment name"
    )
    is_default: Optional[bool] = Field(
        None, description="Whether this is the default environment for RCA"
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
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EnvironmentListResponse(BaseModel):
    """Response for listing environments."""

    environments: List[EnvironmentSummaryResponse]


# Repository configuration schemas
class EnvironmentRepositoryCreate(BaseModel):
    """Request to add a repository to an environment."""

    repo_full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Repository full name (owner/repo)",
    )
    branch_name: Optional[str] = Field(
        None, max_length=255, description="Branch name (optional context, not required)"
    )
    is_enabled: bool = Field(
        default=True,
        description="Whether the repository is enabled for this environment",
    )


class EnvironmentRepositoryUpdate(BaseModel):
    """Request to update a repository configuration."""

    branch_name: Optional[str] = Field(None, max_length=255, description="Branch name")
    is_enabled: Optional[bool] = Field(
        None, description="Whether the repository is enabled"
    )


class EnvironmentRepositoryListResponse(BaseModel):
    """Response for listing repository configurations."""

    repositories: List[EnvironmentRepositoryResponse]


# GitHub helper schemas
class AvailableRepository(BaseModel):
    """A repository available from GitHub that can be added to an environment."""

    full_name: str
    default_branch: Optional[str] = None
    is_private: bool


class AvailableRepositoriesResponse(BaseModel):
    """Response for listing available repositories."""

    repositories: List[AvailableRepository]


class BranchListResponse(BaseModel):
    """Response for listing branches of a repository."""

    branches: List[str]
