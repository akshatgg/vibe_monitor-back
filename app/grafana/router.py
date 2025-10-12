"""
Grafana integration API router.
Provides endpoints for connecting and managing Grafana integrations.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import User
from app.onboarding.services.auth_service import AuthService
from .schemas import (
    GrafanaConnectRequest,
    GrafanaConnectionResponse,
    GrafanaDisconnectResponse,
)
from .service import GrafanaService

router = APIRouter(prefix="/grafana", tags=["grafana"])
auth_service = AuthService()
grafana_service = GrafanaService()


@router.post("/connect", response_model=GrafanaConnectionResponse)
async def connect_grafana(
    request: GrafanaConnectRequest,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Connect Grafana to a workspace.

    Flow:
    1. User provides Grafana instance URL and API token
    2. Validate credentials by testing connectivity
    3. Backend encrypts and stores the token
    4. Return connection status

    Required:
    - workspace_id: VibeMonitor workspace ID
    - grafana_url: Grafana instance URL (e.g., https://your-grafana-instance.com)
    - api_token: Grafana API token
    """
    try:
        # Validate credentials before storing
        is_valid = await grafana_service.validate_credentials(
            grafana_url=request.grafana_url,
            api_token=request.api_token
        )

        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail="Invalid Grafana credentials. Please check your URL and API token."
            )

        # Store integration after validation passes
        integration = await grafana_service.create_integration(
            workspace_id=request.workspace_id,
            grafana_url=request.grafana_url,
            api_token=request.api_token,
            db=db,
        )

        return GrafanaConnectionResponse(
            id=integration.id,
            workspace_id=integration.vm_workspace_id,
            grafana_url=integration.grafana_url,
            connected=True,
            created_at=integration.created_at,
            updated_at=integration.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to connect Grafana: {str(e)}"
        )


@router.get("/status/{workspace_id}", response_model=GrafanaConnectionResponse)
async def get_grafana_status(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get Grafana connection status for a workspace.

    Returns connection details without exposing the API token.
    """
    try:
        integration = await grafana_service.get_integration(workspace_id, db)

        if not integration:
            raise HTTPException(
                status_code=404,
                detail="No Grafana integration found for this workspace",
            )

        return GrafanaConnectionResponse(
            id=integration.id,
            workspace_id=integration.vm_workspace_id,
            grafana_url=integration.grafana_url,
            connected=True,
            created_at=integration.created_at,
            updated_at=integration.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get Grafana status: {str(e)}"
        )


@router.delete("/disconnect/{workspace_id}", response_model=GrafanaDisconnectResponse)
async def disconnect_grafana(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnect Grafana from a workspace.

    Deletes the stored integration and encrypted token.
    """
    try:
        deleted = await grafana_service.delete_integration(workspace_id, db)

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="No Grafana integration found for this workspace",
            )

        return GrafanaDisconnectResponse(
            message="Grafana integration disconnected successfully",
            workspace_id=workspace_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to disconnect Grafana: {str(e)}"
        )
