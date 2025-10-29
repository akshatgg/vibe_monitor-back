"""
AWS Integration API router.
Provides 3 endpoints for managing AWS integrations:
1. Store AWS credentials
2. Check AWS integration status
3. Delete AWS integration
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import User
from app.onboarding.services.auth_service import AuthService
from .schemas import (
    AWSIntegrationCreate,
    AWSIntegrationResponse,
)
from .service import aws_integration_service

router = APIRouter(prefix="/aws", tags=["aws-integration"])
auth_service = AuthService()


@router.post("/integration", response_model=AWSIntegrationResponse, status_code=201)
async def store_aws_credentials(
    request: AWSIntegrationCreate,
    workspace_id: str,
    _: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Store AWS credentials for a workspace (encrypted in database).

    This endpoint:
    1. Receives AWS Access Key ID and Secret Access Key
    2. Encrypts the credentials using token_processor
    3. Stores them in the database linked to the workspace

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    - aws_access_key_id: AWS Access Key ID
    - aws_secret_access_key: AWS Secret Access Key
    - aws_region: AWS Region (optional, defaults to us-east-1)
    """
    try:
        integration = await aws_integration_service.create_aws_integration(
            db=db,
            workspace_id=workspace_id,
            integration_data=request,
        )
        return integration

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to store AWS credentials: {str(e)}"
        )


@router.get("/integration/status", response_model=AWSIntegrationResponse)
async def get_aws_integration_status(
    workspace_id: str,
    _: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if AWS integration is configured for a workspace.

    Returns:
    - Integration details if configured
    - 404 error if not configured

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    """
    try:
        integration = await aws_integration_service.get_aws_integration(
            db=db, workspace_id=workspace_id
        )

        if not integration:
            raise HTTPException(
                status_code=404,
                detail="AWS integration not configured for this workspace",
            )

        return integration

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get AWS integration status: {str(e)}"
        )


@router.delete("/integration")
async def delete_aws_integration(
    workspace_id: str,
    _: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete AWS integration for a specific workspace.

    This will remove the stored AWS credentials from the database.

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    """
    try:
        deleted = await aws_integration_service.delete_aws_integration(
            db=db, workspace_id=workspace_id
        )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="AWS integration not found for this workspace",
            )

        return {
            "message": "AWS integration deleted successfully",
            "workspace_id": workspace_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete AWS integration: {str(e)}"
        )
