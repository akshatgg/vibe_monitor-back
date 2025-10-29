"""
Pydantic schemas for AWS Integration
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AWSIntegrationCreate(BaseModel):
    """Schema for creating an AWS integration"""
    aws_access_key_id: str = Field(..., description="AWS Access Key ID")
    aws_secret_access_key: str = Field(..., description="AWS Secret Access Key")
    aws_region: Optional[str] = Field(default=None, description="AWS Region")


class AWSIntegrationResponse(BaseModel):
    """Schema for AWS integration response (without sensitive data)"""
    id: str = Field(..., description="Integration ID")
    workspace_id: str = Field(..., description="Workspace ID")
    aws_region: Optional[str] = Field(None, description="AWS Region")
    is_active: bool = Field(..., description="Whether the integration is active")
    last_verified_at: Optional[datetime] = Field(None, description="Last verification timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    # Masked credentials for display
    aws_access_key_id_masked: str = Field(..., description="Masked AWS Access Key ID")

    class Config:
        from_attributes = True


class AWSIntegrationVerifyResponse(BaseModel):
    """Schema for AWS credentials verification response (internal use)"""
    is_valid: bool = Field(..., description="Whether the credentials are valid")
    message: str = Field(..., description="Verification result message")
    account_id: Optional[str] = Field(None, description="AWS Account ID if verification successful")
