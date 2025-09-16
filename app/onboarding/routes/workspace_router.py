from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..schemas.schemas import (
    WorkspaceCreate, 
    WorkspaceResponse, 
    WorkspaceWithMembership
)
from ..services.workspace_service import WorkspaceService
from ..services.auth_service import AuthService
from ..models.models import User
from ...core.database import get_db

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
workspace_service = WorkspaceService()
auth_service = AuthService()


@router.post("/", response_model=WorkspaceResponse)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new workspace"""
    try:
        workspace = await workspace_service.create_workspace(
            workspace_data=workspace_data,
            owner_user_id=current_user.id,
            db=db
        )
        return workspace
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create workspace: {str(e)}")


@router.get("/", response_model=List[WorkspaceWithMembership])
async def get_user_workspaces(
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all workspaces where the current user is a member"""
    try:
        workspaces = await workspace_service.get_user_workspaces(
            user_id=current_user.id,
            db=db
        )
        return workspaces
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to get workspaces: {str(e)}")


@router.get("/{workspace_id}", response_model=WorkspaceWithMembership)
async def get_workspace(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific workspace by ID (only if user is a member)"""
    try:
        workspace = await workspace_service.get_workspace_by_id(
            workspace_id=workspace_id,
            user_id=current_user.id,
            db=db
        )
        
        if not workspace:
            raise HTTPException(
                status_code=404, 
                detail="Workspace not found or you don't have access"
            )
        
        return workspace
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to get workspace: {str(e)}")


@router.get("/discover/{domain}", response_model=List[WorkspaceResponse])
async def discover_workspaces_by_domain(
    domain: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Discover workspaces visible to users with the given domain"""
    try:
        workspaces = await workspace_service.get_visible_workspaces_by_domain(
            domain=domain,
            db=db
        )
        return workspaces
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to discover workspaces: {str(e)}")