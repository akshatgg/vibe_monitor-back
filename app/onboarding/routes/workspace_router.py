from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from ..schemas.schemas import (
    WorkspaceCreate, 
    WorkspaceUpdate,
    WorkspaceResponse, 
    WorkspaceWithMembership
)
from ..services.workspace_service import WorkspaceService
from ..services.auth_service import AuthService
from app.models import User
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


@router.get("/discover", response_model=List[WorkspaceResponse])
async def discover_workspaces_for_current_user(
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Discover workspaces available to the current user based on their email domain (excludes workspaces they're already in)"""
    try:
        workspaces = await workspace_service.discover_workspaces_for_user(
            user_id=current_user.id,
            user_email=current_user.email,
            db=db
        )
        return workspaces
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to discover workspaces: {str(e)}")



@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    workspace_update: WorkspaceUpdate,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update workspace settings (only owners can update visibility)"""
    try:
        # Handle visibility update with auto-domain setting
        if workspace_update.visible_to_org is not None:
            workspace = await workspace_service.update_workspace_visibility(
                workspace_id=workspace_id,
                user_id=current_user.id,
                visible_to_org=workspace_update.visible_to_org,
                db=db
            )
            return workspace
        
        # For other updates (like name), you can extend this logic
        raise HTTPException(status_code=400, detail="No valid updates provided")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update workspace: {str(e)}")


@router.delete("/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a workspace (only owners can delete)"""
    try:
        success = await workspace_service.delete_workspace(
            workspace_id=workspace_id,
            user_id=current_user.id,
            db=db
        )
        
        if success:
            return {"message": "Workspace deleted successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to delete workspace")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to delete workspace: {str(e)}")