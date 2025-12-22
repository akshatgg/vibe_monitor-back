"""
Pydantic schemas for AWS Integration
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AWSIntegrationCreate(BaseModel):
    """Schema for creating an AWS integration using IAM role ARN"""

    role_arn: str = Field(
        ...,
        description="AWS IAM Role ARN (e.g., arn:aws:iam::123456789012:role/VibeMonitor)",
    )
    external_id: Optional[str] = Field(
        default=None,
        description="External ID for secure cross-account access (optional but recommended)",
    )
    aws_region: str = Field(
        default="us-west-1", description="AWS Region (defaults to us-west-1)"
    )


class AWSIntegrationResponse(BaseModel):
    """Schema for AWS integration response (without sensitive data)"""

    id: str = Field(..., description="Integration ID")
    workspace_id: str = Field(..., description="Workspace ID")
    role_arn: str = Field(..., description="AWS IAM Role ARN")
    has_external_id: bool = Field(
        ..., description="Whether an external ID is configured"
    )
    aws_region: Optional[str] = Field(None, description="AWS Region")
    is_active: bool = Field(..., description="Whether the integration is active")
    credentials_expiration: Optional[datetime] = Field(
        None, description="When temporary credentials expire"
    )
    last_verified_at: Optional[datetime] = Field(
        None, description="Last verification timestamp"
    )
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    class Config:
        from_attributes = True


class AWSIntegrationVerifyResponse(BaseModel):
    """Schema for AWS credentials verification response (internal use)"""

    is_valid: bool = Field(..., description="Whether the credentials are valid")
    message: str = Field(..., description="Verification result message")
    account_id: Optional[str] = Field(
        None, description="AWS Account ID if verification successful"
    )
