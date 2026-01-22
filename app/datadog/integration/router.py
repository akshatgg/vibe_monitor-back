"""
Datadog Integration API router.
Provides 3 endpoints for managing Datadog integrations:
1. Create Datadog integration (store API key, App key, and site)
2. Check Datadog integration status
3. Delete Datadog integration
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.core.database import get_db
from app.integrations.utils import check_integration_permission
from app.models import Membership, User

from .schemas import (
    DatadogIntegrationCreate,
    DatadogIntegrationResponse,
    DatadogIntegrationStatusResponse,
)
from .service import (
    create_datadog_integration,
    delete_datadog_integration,
    get_datadog_integration_status,
)

router = APIRouter(prefix="/datadog", tags=["datadog-integration"])
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


@router.post("/integration", response_model=DatadogIntegrationResponse, status_code=201)
async def store_datadog_integration(
    request: DatadogIntegrationCreate,
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Setup Datadog integration for a workspace.

    This endpoint:
    1. Receives Datadog API Key, Application Key, and Region
    2. Validates the credentials format
    3. Verifies credentials with Datadog API
    4. Encrypts and stores the credentials in the database

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    - api_key: Datadog organization-level API key (request body)
    - app_key: Datadog organization-level Application Key with permissions (request body)
    - region: Datadog region code (e.g., us1, us5, eu1) (request body)
    """
    # Verify user has access to this workspace
    await verify_workspace_access(workspace_id, current_user, db)

    # Check workspace type restriction (Datadog blocked on personal workspaces)
    await check_integration_permission(workspace_id, "datadog", db)

    try:
        integration = await create_datadog_integration(
            db=db,
            user_id=current_user.id,
            workspace_id=workspace_id,
            integration_data=request,
        )
        return integration

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to setup Datadog integration: {str(e)}"
        )


@router.get("/integration/status", response_model=DatadogIntegrationStatusResponse)
async def get_integration_status(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if Datadog integration is configured for a workspace.

    Returns:
    - is_connected: Boolean indicating if the workspace is connected to Datadog
    - integration: Integration details if connected, null otherwise

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    """
    # Verify user has access to this workspace
    await verify_workspace_access(workspace_id, current_user, db)

    try:
        status = await get_datadog_integration_status(db=db, workspace_id=workspace_id)
        return status

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get Datadog integration status: {str(e)}",
        )


@router.delete("/integration")
async def delete_integration(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete Datadog integration for a specific workspace.

    This will remove the stored Datadog credentials from the database.

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    """
    # Verify user has access to this workspace
    await verify_workspace_access(workspace_id, current_user, db)

    try:
        deleted = await delete_datadog_integration(
            db=db, user_id=current_user.id, workspace_id=workspace_id
        )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="Datadog integration not found for this workspace",
            )

        return {
            "message": "Datadog integration deleted successfully",
            "workspace_id": workspace_id,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete Datadog integration: {str(e)}"
        )
