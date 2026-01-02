"""
Pydantic schemas for deployments endpoints.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models import DeploymentSource, DeploymentStatus


# Request schemas
class DeploymentCreate(BaseModel):
    """Request to create a deployment record."""

    repo_full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Repository full name (owner/repo)",
    )
    branch: Optional[str] = Field(
        None, max_length=255, description="Deployed branch name"
    )
    commit_sha: Optional[str] = Field(
        None, min_length=7, max_length=40, description="Commit SHA"
    )
    status: DeploymentStatus = Field(
        default=DeploymentStatus.SUCCESS, description="Deployment status"
    )
    source: DeploymentSource = Field(
        default=DeploymentSource.MANUAL, description="Source of deployment record"
    )
    deployed_at: Optional[datetime] = Field(
        None, description="When the deployment occurred (defaults to now)"
    )
    extra_data: Optional[Dict[str, Any]] = Field(
        None, description="Additional metadata from CI/CD"
    )


class WebhookDeploymentCreate(BaseModel):
    """Request to create a deployment via webhook."""

    environment: str = Field(..., min_length=1, description="Environment name or ID")
    repository: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Repository full name (owner/repo)",
    )
    branch: Optional[str] = Field(
        None, max_length=255, description="Deployed branch name"
    )
    commit_sha: Optional[str] = Field(
        None, min_length=7, max_length=40, description="Commit SHA"
    )
    status: Optional[str] = Field(
        "success",
        description="Deployment status (pending, in_progress, success, failed, cancelled)",
    )
    source: Optional[str] = Field(
        "webhook",
        description="Source identifier (github_actions, jenkins, argocd, etc.)",
    )
    deployed_at: Optional[datetime] = Field(
        None, description="When the deployment occurred (defaults to now)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="Additional metadata from CI/CD"
    )


# Response schemas
class DeploymentResponse(BaseModel):
    """Response for a deployment record."""

    id: str
    environment_id: str
    repo_full_name: str
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    status: str
    source: str
    deployed_at: Optional[datetime] = None
    extra_data: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DeploymentListResponse(BaseModel):
    """Response for listing deployments."""

    deployments: List[DeploymentResponse]
    total: int


# API Key schemas
class ApiKeyCreate(BaseModel):
    """Request to create an API key."""

    name: str = Field(
        ..., min_length=1, max_length=100, description="Name for the API key"
    )


class ApiKeyResponse(BaseModel):
    """Response for an API key (without the actual key)."""

    id: str
    name: str
    key_prefix: str
    last_used_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ApiKeyCreateResponse(BaseModel):
    """Response when creating an API key (includes the actual key, shown only once)."""

    id: str
    name: str
    key: str  # The full API key, shown only on creation
    key_prefix: str
    created_at: datetime


class ApiKeyListResponse(BaseModel):
    """Response for listing API keys."""

    api_keys: List[ApiKeyResponse]
