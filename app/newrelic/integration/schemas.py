"""
Pydantic schemas for New Relic Integration
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


class NewRelicIntegrationCreate(BaseModel):
    """Schema for creating a New Relic integration"""
    account_id: str = Field(..., description="New Relic Account ID")
    api_key: str = Field(..., description="New Relic User API Key (must start with NRAK)")

    @field_validator('api_key')
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Validate that API key starts with NRAK"""
        if not v.startswith('NRAK'):
            raise ValueError('New Relic User API Key must start with NRAK')
        if len(v) < 10:
            raise ValueError('New Relic User API Key is too short')
        return v


class NewRelicIntegrationResponse(BaseModel):
    """Schema for New Relic integration response (without sensitive data)"""
    id: str = Field(..., description="Integration ID")
    workspace_id: str = Field(..., description="Workspace ID")
    account_id: str = Field(..., description="New Relic Account ID")
    last_verified_at: Optional[datetime] = Field(None, description="Last verification timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    class Config:
        from_attributes = True


class NewRelicIntegrationStatusResponse(BaseModel):
    """Schema for New Relic integration status response"""
    is_connected: bool = Field(..., description="Whether the workspace is connected to New Relic")
    integration: Optional[NewRelicIntegrationResponse] = Field(None, description="Integration details if connected")
