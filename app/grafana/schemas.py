"""
Pydantic schemas for Grafana integration API
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class GrafanaConnectRequest(BaseModel):
    """Request model for connecting Grafana Cloud"""

    workspace_id: str = Field(..., description="VibeMonitor workspace ID")
    grafana_url: str = Field(
        ...,
        description="Grafana Cloud stack URL",
        examples=["https://akshatgg.grafana.net"],
    )
    api_token: str = Field(
        ..., description="Grafana Cloud Access Policy token"
    )


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
