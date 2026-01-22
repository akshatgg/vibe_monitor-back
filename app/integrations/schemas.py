"""
Pydantic schemas for integration API responses.
"""

from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict


class IntegrationResponse(BaseModel):
    """Response model for a single integration."""

    id: str
    workspace_id: str
    provider: str
    status: str
    health_status: str | None
    last_verified_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IntegrationListResponse(BaseModel):
    """Response model for list of integrations."""

    integrations: List[IntegrationResponse]
    total: int


class HealthCheckResponse(BaseModel):
    """Response model for health check results."""

    integration_id: str
    provider: str
    health_status: str | None
    status: str
    last_verified_at: datetime | None
    last_error: str | None


class AvailableIntegrationsResponse(BaseModel):
    """Response model for available integrations."""

    allowed_integrations: List[str]
    restrictions: dict[str, bool]
