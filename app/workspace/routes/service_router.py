"""
Service management API routes.
Handles CRUD operations for services within workspaces.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.core.database import get_db
from app.models import Membership
from app.workspace.client_workspace_services.schemas import (
    ServiceCountResponse,
    ServiceCreate,
    ServiceListResponse,
    ServiceResponse,
    ServiceUpdate,
)
from app.workspace.client_workspace_services.service_service import ServiceService

logger = logging.getLogger(__name__)

auth_service = AuthService()
service_service = ServiceService()

router = APIRouter(
    prefix="/workspaces/{workspace_id}/services", tags=["services"]
)


@router.post("", response_model=ServiceResponse, status_code=201)
async def create_service(
    workspace_id: str,
    service_data: ServiceCreate,
    current_user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new service in the workspace.

    Only workspace owners can create services.
    Free tier limit: 5 services per workspace.
    """
    try:
        return await service_service.create_service(
            workspace_id=workspace_id,
            service_data=service_data,
            user_id=current_user.id,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to create service: {str(e)}"
        )


@router.get("", response_model=ServiceListResponse)
async def list_services(
    workspace_id: str,
    search: Optional[str] = Query(None, description="Filter by service name (case-insensitive)"),
    team_id: Optional[str] = Query(None, description="Filter by team ID"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
    current_user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all services in the workspace with optional search, filter, and pagination."""
    try:
        return await service_service.list_services(
            workspace_id=workspace_id,
            user_id=current_user.id,
            db=db,
            search=search,
            team_id=team_id,
            offset=offset,
            limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to list services: {str(e)}"
        )


@router.get("/count", response_model=ServiceCountResponse)
async def get_service_count(
    workspace_id: str,
    current_user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get service count and limit information for the workspace."""
    try:
        membership_query = select(Membership).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == current_user.id,
        )
        result = await db.execute(membership_query)
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=403, detail="You are not a member of this workspace"
            )

        return await service_service.get_service_count(
            workspace_id=workspace_id,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to get service count: {str(e)}"
        )


@router.get("/{service_id}", response_model=ServiceResponse)
async def get_service(
    workspace_id: str,
    service_id: str,
    current_user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single service by ID."""
    try:
        return await service_service.get_service(
            workspace_id=workspace_id,
            service_id=service_id,
            user_id=current_user.id,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to get service: {str(e)}")


@router.patch("/{service_id}", response_model=ServiceResponse)
async def update_service(
    workspace_id: str,
    service_id: str,
    service_data: ServiceUpdate,
    current_user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing service. Only workspace owners can update."""
    try:
        return await service_service.update_service(
            workspace_id=workspace_id,
            service_id=service_id,
            service_data=service_data,
            user_id=current_user.id,
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to update service: {str(e)}"
        )


@router.delete("/{service_id}", status_code=204)
async def delete_service(
    workspace_id: str,
    service_id: str,
    current_user = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a service. Only workspace owners can delete."""
    try:
        await service_service.delete_service(
            workspace_id=workspace_id,
            service_id=service_id,
            user_id=current_user.id,
            db=db,
        )
        return None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to delete service: {str(e)}"
        )
