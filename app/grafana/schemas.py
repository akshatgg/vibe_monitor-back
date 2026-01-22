"""
Pydantic schemas for Grafana integration API
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GrafanaConnectRequest(BaseModel):
    """Request model for connecting Grafana"""

    grafana_url: str = Field(
        ...,
        description="Grafana instance URL",
        examples=["https://your-grafana-instance.com"],
    )
    api_token: str = Field(..., description="Grafana API token")


class GrafanaConnectionResponse(BaseModel):
    """Response model for Grafana connection status"""

    id: str
    workspace_id: str
    grafana_url: str
    connected: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GrafanaDisconnectResponse(BaseModel):
    """Response model for disconnecting Grafana"""

    message: str
    workspace_id: str


class GrafanaStatusResponse(BaseModel):
    """Response model for Grafana integration status check"""

    connected: bool = Field(
        ..., description="Whether the workspace is connected to Grafana"
    )
    integration: Optional[GrafanaConnectionResponse] = Field(
        None, description="Integration details if connected"
    )
