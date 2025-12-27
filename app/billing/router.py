"""
Billing domain API router for Service management.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.core.database import get_db
from app.auth.services.google_auth_service import AuthService

from .schemas import (
    ServiceCreate,
    ServiceUpdate,
    ServiceResponse,
    ServiceListResponse,
    ServiceCountResponse,
)
from .services.service_service import ServiceService


router = APIRouter(prefix="/workspaces/{workspace_id}/services", tags=["services"])

auth_service = AuthService()
service_service = ServiceService()


@router.post("", response_model=ServiceResponse, status_code=201)
async def create_service(
    workspace_id: str,
    service_data: ServiceCreate,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new service in the workspace.

    - **name**: Service name (should match what appears in observability logs)
    - **repository_name**: Optional repository to link (format: owner/repo)

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
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all services in the workspace.

    Any workspace member can view services.
    """
    try:
        return await service_service.list_services(
            workspace_id=workspace_id,
            user_id=current_user.id,
            db=db,
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
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get service count and limit information for the workspace.

    Returns:
    - current_count: Number of services in workspace
    - limit: Maximum services allowed in current tier
    - can_add_more: Whether more services can be added
    - is_paid: Whether workspace is on paid tier
    """
    try:
        # Verify user is a member first
        from app.models import Membership
        from sqlalchemy import select

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
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a single service by ID.

    Any workspace member can view.
    """
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
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing service.

    - **name**: New service name (optional)
    - **repository_name**: New repository link (optional)
    - **enabled**: Enable/disable the service (optional)

    Only workspace owners can update services.
    """
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
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a service.

    Only workspace owners can delete services.
    """
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
