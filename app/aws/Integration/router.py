"""
AWS Integration API router.
Provides 3 endpoints for managing AWS integrations:
1. Store AWS credentials
2. Check AWS integration status
3. Delete AWS integration
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.core.database import get_db
from app.integrations.utils import check_integration_permission
from app.models import Membership, User

from .schemas import (
    AWSIntegrationCreate,
    AWSIntegrationResponse,
    AWSIntegrationStatusResponse,
)
from .service import aws_integration_service

router = APIRouter(prefix="/aws", tags=["aws-integration"])
auth_service = AuthService()


async def verify_workspace_access(
    workspace_id: str, user: User, db: AsyncSession
) -> None:
    """
    Verify that the user has access to the workspace

    Args:
        workspace_id: Workspace ID to check
        user: Authenticated user
        db: Database session

    Raises:
        HTTPException: 403 if user doesn't have access to workspace
    """
    # Check if user is a member of the workspace
    membership_query = select(Membership).where(
        Membership.workspace_id == workspace_id, Membership.user_id == user.id
    )

    result = await db.execute(membership_query)
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied. You do not have permission to access workspace: {workspace_id}",
        )


@router.post("/integration", response_model=AWSIntegrationResponse, status_code=201)
async def store_aws_integration(
    request: AWSIntegrationCreate,
    workspace_id: str,
    user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Setup AWS integration for a workspace using IAM role ARN.

    This endpoint:
    1. Receives AWS IAM Role ARN
    2. Assumes the role to get temporary credentials
    3. Encrypts and stores the temporary credentials in the database
    4. Automatically refreshes credentials when they expire

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    - role_arn: AWS IAM Role ARN (e.g., arn:aws:iam::123456789012:role/VibeMonitor)
    - aws_region: AWS Region (optional, defaults to us-west-1)

    The IAM role must have:
    - Trust relationship allowing this service to assume it
    - Permissions: logs:DescribeLogGroups, cloudwatch:*, xray:*
    """
    # Verify user has access to this workspace
    await verify_workspace_access(workspace_id, user, db)

    # Check workspace type restriction (AWS blocked on personal workspaces)
    await check_integration_permission(workspace_id, "aws", db)

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
            status_code=500, detail=f"Failed to setup AWS integration: {str(e)}"
        )


@router.get("/integration/status", response_model=AWSIntegrationStatusResponse)
async def get_aws_integration_status(
    workspace_id: str,
    user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if AWS integration is configured for a workspace.

    Returns:
    - is_connected: Boolean indicating if the workspace is connected to AWS
    - integration: Integration details if connected, null otherwise

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    """
    # Verify user has access to this workspace
    await verify_workspace_access(workspace_id, user, db)

    try:
        integration = await aws_integration_service.get_aws_integration(
            db=db, workspace_id=workspace_id
        )

        if not integration:
            return AWSIntegrationStatusResponse(is_connected=False, integration=None)

        return AWSIntegrationStatusResponse(is_connected=True, integration=integration)

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get AWS integration status: {str(e)}"
        )


@router.delete("/integration")
async def delete_aws_integration(
    workspace_id: str,
    user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete AWS integration for a specific workspace.

    This will remove the stored AWS credentials from the database.

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    """
    # Verify user has access to this workspace
    await verify_workspace_access(workspace_id, user, db)

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
