"""
Integration health check API router.
Provides endpoints for managing and monitoring integrations.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.models import User, Workspace, Membership, WorkspaceType
from app.auth.services.google_auth_service import AuthService
from app.integrations.service import (
    check_integration_health,
    check_all_workspace_integrations_health,
    get_workspace_integrations,
    get_integration_by_id,
)
from app.integrations.schemas import (
    IntegrationResponse,
    IntegrationListResponse,
    HealthCheckResponse,
    AvailableIntegrationsResponse,
)
from app.integrations.utils import get_allowed_integrations, ALL_PROVIDERS

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workspaces/{workspace_id}/integrations", tags=["integrations"]
)
auth_service = AuthService()


@router.get("", response_model=IntegrationListResponse)
async def list_workspace_integrations(
    workspace_id: str,
    integration_type: str | None = None,
    status: str | None = None,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all integrations for a workspace.

    Query Parameters:
    - integration_type: Filter by type (github, aws, grafana, datadog, newrelic, slack)
    - status: Filter by status (active, disabled, error)
    """
    logger.info(
        f"API request: list integrations - workspace_id={workspace_id}, "
        f"user_id={current_user.id}, type_filter={integration_type}, status_filter={status}"
    )

    try:
        integrations = await get_workspace_integrations(
            workspace_id=workspace_id,
            db=db,
            integration_type=integration_type,
            status=status,
        )

        logger.info(
            f"API response: list integrations - workspace_id={workspace_id}, "
            f"count={len(integrations)}"
        )

        return IntegrationListResponse(
            integrations=[
                IntegrationResponse.from_orm(integration)
                for integration in integrations
            ],
            total=len(integrations),
        )

    except Exception as e:
        logger.exception(
            f"API error: list integrations failed - workspace_id={workspace_id}, "
            f"user_id={current_user.id}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch integrations: {str(e)}"
        )


@router.get("/{integration_id}", response_model=IntegrationResponse)
async def get_integration(
    workspace_id: str,
    integration_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a specific integration by ID.
    """
    logger.debug(
        f"API request: get integration - integration_id={integration_id}, "
        f"user_id={current_user.id}"
    )

    try:
        integration = await get_integration_by_id(integration_id, db)

        if not integration:
            logger.warning(
                f"API 404: integration not found - integration_id={integration_id}, "
                f"user_id={current_user.id}"
            )
            raise HTTPException(status_code=404, detail="Integration not found")

        logger.debug(
            f"API response: get integration - integration_id={integration_id}, "
            f"provider={integration.provider}, status={integration.status}"
        )
        return IntegrationResponse.from_orm(integration)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            f"API error: get integration failed - integration_id={integration_id}, "
            f"user_id={current_user.id}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch integration: {str(e)}"
        )


@router.post("/{integration_id}/health-check", response_model=HealthCheckResponse)
async def check_single_integration_health(
    workspace_id: str,
    integration_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a health check for a specific integration.

    This endpoint will:
    1. Test the integration credentials with the provider API
    2. Update the integration's health_status and last_verified_at
    3. Return the updated health status
    """
    logger.info(
        f"API request: health check - integration_id={integration_id}, "
        f"user_id={current_user.id}"
    )

    try:
        integration = await check_integration_health(integration_id, db)

        logger.info(
            f"API response: health check completed - integration_id={integration_id}, "
            f"provider={integration.provider}, health_status={integration.health_status}, "
            f"status={integration.status}"
        )

        return HealthCheckResponse(
            integration_id=integration.id,
            provider=integration.provider,
            health_status=integration.health_status,
            status=integration.status,
            last_verified_at=integration.last_verified_at,
            last_error=integration.last_error,
        )

    except ValueError as e:
        logger.warning(
            f"API 404: health check - integration not found - integration_id={integration_id}, "
            f"user_id={current_user.id}"
        )
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(
            f"API error: health check failed - integration_id={integration_id}, "
            f"user_id={current_user.id}"
        )
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.post("/health-check", response_model=List[HealthCheckResponse])
async def check_workspace_integrations_health(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger health checks for all integrations in a workspace.

    This endpoint will:
    1. Test all integration credentials with their respective provider APIs
    2. Update each integration's health_status and last_verified_at
    3. Return the updated health status for all integrations
    """
    logger.info(
        f"API request: bulk health check - workspace_id={workspace_id}, "
        f"user_id={current_user.id}"
    )

    try:
        integrations = await check_all_workspace_integrations_health(workspace_id, db)

        healthy = sum(1 for i in integrations if i.health_status == "healthy")
        failed = sum(1 for i in integrations if i.health_status == "failed")

        logger.info(
            f"API response: bulk health check completed - workspace_id={workspace_id}, "
            f"total={len(integrations)}, healthy={healthy}, failed={failed}"
        )

        return [
            HealthCheckResponse(
                integration_id=integration.id,
                provider=integration.provider,
                health_status=integration.health_status,
                status=integration.status,
                last_verified_at=integration.last_verified_at,
                last_error=integration.last_error,
            )
            for integration in integrations
        ]

    except Exception as e:
        logger.exception(
            f"API error: bulk health check failed - workspace_id={workspace_id}, "
            f"user_id={current_user.id}"
        )
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")


@router.get("/available", response_model=AvailableIntegrationsResponse)
async def get_available_integrations(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get list of integrations available for this workspace.

    Used by frontend to show/hide integration options based on workspace type.

    Returns:
    - workspace_type: The type of workspace (personal or team)
    - allowed_integrations: List of integration providers allowed for this workspace
    - restrictions: Dict mapping provider names to blocked status (True = blocked)
    - upgrade_message: Message to display for personal workspaces, null for team workspaces
    """
    logger.info(
        f"API request: get available integrations - workspace_id={workspace_id}, "
        f"user_id={current_user.id}"
    )

    try:
        membership_result = await db.execute(
            select(Membership).where(
                Membership.user_id == current_user.id,
                Membership.workspace_id == workspace_id,
            )
        )
        membership = membership_result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403, detail="User does not have access to this workspace"
            )

        workspace_result = await db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = workspace_result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        allowed = get_allowed_integrations(workspace.type)
        restrictions = {provider: provider not in allowed for provider in ALL_PROVIDERS}

        upgrade_message = (
            "Create a team workspace to access all integrations."
            if workspace.type == WorkspaceType.PERSONAL
            else None
        )

        logger.info(
            f"API response: available integrations - workspace_id={workspace_id}, "
            f"workspace_type={workspace.type.value}, allowed_count={len(allowed)}"
        )

        return AvailableIntegrationsResponse(
            workspace_type=workspace.type.value,
            allowed_integrations=sorted(list(allowed)),
            restrictions=restrictions,
            upgrade_message=upgrade_message,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            f"API error: get available integrations failed - workspace_id={workspace_id}, "
            f"user_id={current_user.id}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to get available integrations: {str(e)}"
        )
