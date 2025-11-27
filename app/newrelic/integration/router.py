"""
New Relic Integration API router.
Provides 3 endpoints for managing New Relic integrations:
1. Create New Relic integration (store account ID and API key)
2. Check New Relic integration status
3. Delete New Relic integration
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import User
from app.onboarding.services.auth_service import AuthService
from .schemas import (
    NewRelicIntegrationCreate,
    NewRelicIntegrationResponse,
    NewRelicIntegrationStatusResponse,
)
from .service import (
    create_newrelic_integration,
    get_newrelic_integration_status,
    delete_newrelic_integration,
)

router = APIRouter(prefix="/newrelic", tags=["newrelic-integration"])
auth_service = AuthService()


@router.post("/integration", response_model=NewRelicIntegrationResponse, status_code=201)
async def store_newrelic_integration(
    request: NewRelicIntegrationCreate,
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Setup New Relic integration for a workspace.

    This endpoint:
    1. Receives New Relic Account ID and User API Key
    2. Validates that the API key starts with NRAK
    3. Verifies credentials with New Relic API
    4. Encrypts and stores the credentials in the database

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    - account_id: New Relic Account ID (request body)
    - api_key: New Relic User API Key (must start with NRAK) (request body)
    """
    try:
        integration = await create_newrelic_integration(
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
            status_code=500, detail=f"Failed to setup New Relic integration: {str(e)}"
        )


@router.get("/integration/status", response_model=NewRelicIntegrationStatusResponse)
async def get_integration_status(
    workspace_id: str,
    _: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if New Relic integration is configured for a workspace.

    Returns:
    - is_connected: Boolean indicating if the workspace is connected to New Relic
    - integration: Integration details if connected, null otherwise

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    """
    try:
        status = await get_newrelic_integration_status(
            db=db, workspace_id=workspace_id
        )
        return status

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get New Relic integration status: {str(e)}"
        )


@router.delete("/integration")
async def delete_integration(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete New Relic integration for a specific workspace.

    This will remove the stored New Relic credentials from the database.

    Required:
    - workspace_id: VibeMonitor workspace ID (query parameter)
    """
    try:
        deleted = await delete_newrelic_integration(
            db=db, user_id=current_user.id, workspace_id=workspace_id
        )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="New Relic integration not found for this workspace",
            )

        return {
            "message": "New Relic integration deleted successfully",
            "workspace_id": workspace_id,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete New Relic integration: {str(e)}"
        )
