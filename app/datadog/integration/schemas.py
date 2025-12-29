"""
Pydantic schemas for Datadog Integration
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class DatadogIntegrationCreate(BaseModel):
    """Schema for creating a Datadog integration"""

    api_key: str = Field(..., description="Datadog organization-level API key")
    app_key: str = Field(
        ..., description="Datadog organization-level Application Key with permissions"
    )
    region: str = Field(
        ..., description="Datadog region (e.g., us1, us3, us5, eu1, ap1, us1-fed)"
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate that API key is not empty and has minimum length"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Datadog API key cannot be empty")
        if len(v) < 32:
            raise ValueError("Datadog API key is too short")
        return v.strip()

    @field_validator("app_key")
    @classmethod
    def validate_app_key(cls, v: str) -> str:
        """Validate that Application key is not empty and has minimum length"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Datadog Application key cannot be empty")
        if len(v) < 40:
            raise ValueError("Datadog Application key is too short")
        return v.strip()

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        """Validate that region is a valid Datadog region"""
        valid_regions = ["us1", "us3", "us5", "eu1", "ap1", "us1-fed"]
        v_lower = v.lower().strip()
        if v_lower not in valid_regions:
            raise ValueError(
                f"Invalid Datadog region. Must be one of: {', '.join(valid_regions)}"
            )
        return v_lower


class DatadogIntegrationResponse(BaseModel):
    """Schema for Datadog integration response (without sensitive data)"""

    id: str = Field(..., description="Integration ID")
    workspace_id: str = Field(..., description="Workspace ID")
    region: str = Field(..., description="Datadog region")
    last_verified_at: Optional[datetime] = Field(
        None, description="Last verification timestamp"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    class Config:
        from_attributes = True


class DatadogIntegrationStatusResponse(BaseModel):
    """Schema for Datadog integration status response"""

    is_connected: bool = Field(
        ..., description="Whether the workspace is connected to Datadog"
    )
    integration: Optional[DatadogIntegrationResponse] = Field(
        None, description="Integration details if connected"
    )
