from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
import uuid

from ..models.models import Workspace, Membership, User, Role
from ..schemas.schemas import WorkspaceCreate, WorkspaceResponse, WorkspaceWithMembership


class WorkspaceService:
    
    async def create_workspace(
        self, 
        workspace_data: WorkspaceCreate, 
        owner_user_id: str, 
        db: AsyncSession
    ) -> WorkspaceResponse:
        """Create a new workspace and assign the creator as owner"""
        
        # Create workspace
        workspace_id = str(uuid.uuid4())
        new_workspace = Workspace(
            id=workspace_id,
            name=workspace_data.name,
            domain=workspace_data.domain,
            visible_to_org=workspace_data.visible_to_org
        )
        
        db.add(new_workspace)
        await db.flush()  # Flush to get the workspace ID
        
        # Create membership with OWNER role for the creator
        membership_id = str(uuid.uuid4())
        membership = Membership(
            id=membership_id,
            user_id=owner_user_id,
            workspace_id=workspace_id,
            role=Role.OWNER
        )
        
        db.add(membership)
        await db.commit()
        
        # Refresh to get the updated workspace
        await db.refresh(new_workspace)
        
        return WorkspaceResponse.model_validate(new_workspace)
    
    async def get_user_workspaces(
        self, 
        user_id: str, 
        db: AsyncSession
    ) -> List[WorkspaceWithMembership]:
        """Get all workspaces where the user is a member"""
        
        # Query memberships with workspace data
        query = select(Membership).options(
            selectinload(Membership.workspace)
        ).where(Membership.user_id == user_id)
        
        result = await db.execute(query)
        memberships = result.scalars().all()
        
        workspaces_with_membership = []
        for membership in memberships:
            workspace_data = {
                "id": membership.workspace.id,
                "name": membership.workspace.name,
                "domain": membership.workspace.domain,
                "visible_to_org": membership.workspace.visible_to_org,
                "is_paid": membership.workspace.is_paid,
                "created_at": membership.workspace.created_at,
                "user_role": membership.role
            }
            workspaces_with_membership.append(
                WorkspaceWithMembership.model_validate(workspace_data)
            )
        
        return workspaces_with_membership
    
    async def get_workspace_by_id(
        self, 
        workspace_id: str, 
        user_id: str, 
        db: AsyncSession
    ) -> Optional[WorkspaceWithMembership]:
        """Get a specific workspace if user is a member"""
        
        # Query membership to verify user has access and get role
        membership_query = select(Membership).options(
            selectinload(Membership.workspace)
        ).where(
            Membership.workspace_id == workspace_id,
            Membership.user_id == user_id
        )
        
        result = await db.execute(membership_query)
        membership = result.scalar_one_or_none()
        
        if not membership:
            return None
        
        workspace_data = {
            "id": membership.workspace.id,
            "name": membership.workspace.name,
            "domain": membership.workspace.domain,
            "visible_to_org": membership.workspace.visible_to_org,
            "is_paid": membership.workspace.is_paid,
            "created_at": membership.workspace.created_at,
            "user_role": membership.role
        }
        
        return WorkspaceWithMembership.model_validate(workspace_data)
    
    async def get_visible_workspaces_by_domain(
        self, 
        domain: str, 
        db: AsyncSession
    ) -> List[WorkspaceResponse]:
        """Get workspaces that are visible to users with the given domain"""
        
        query = select(Workspace).where(
            Workspace.domain == domain,
            Workspace.visible_to_org == True
        )
        
        result = await db.execute(query)
        workspaces = result.scalars().all()
        
        return [WorkspaceResponse.model_validate(ws) for ws in workspaces]
    
    async def create_personal_workspace(
        self, 
        user: User, 
        db: AsyncSession
    ) -> WorkspaceResponse:
        """Create a personal workspace for a user"""
        
        # Extract username from email for workspace name
        username = user.email.split('@')[0]
        workspace_name = f"{username}-personal"
        
        workspace_data = WorkspaceCreate(
            name=workspace_name,
            domain=None,  # Personal workspaces don't have a domain
            visible_to_org=False  # Personal workspaces are not visible to org
        )
        
        return await self.create_workspace(
            workspace_data=workspace_data,
            owner_user_id=user.id,
            db=db
        )