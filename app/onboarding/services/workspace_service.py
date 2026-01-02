import logging
import uuid
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import GitHubIntegration, Membership, Role, User, Workspace
from app.models import WorkspaceType as DBWorkspaceType

from ..schemas.schemas import (
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceType,
    WorkspaceWithMembership,
)

logger = logging.getLogger(__name__)


class WorkspaceService:
    async def create_workspace(
        self, workspace_data: WorkspaceCreate, owner_user_id: str, db: AsyncSession
    ) -> WorkspaceResponse:
        """Create a new workspace and assign the creator as owner"""

        # Get user info to extract domain if needed
        user_result = await db.execute(select(User).where(User.id == owner_user_id))
        user = user_result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Determine workspace type (default to TEAM)
        workspace_type = (
            workspace_data.type if workspace_data.type else WorkspaceType.TEAM
        )

        # Validation for personal workspaces
        if workspace_type == WorkspaceType.PERSONAL:
            # Check if user already has a personal workspace
            existing_personal = await self._get_user_personal_workspace(
                user_id=owner_user_id, db=db
            )
            if existing_personal:
                raise HTTPException(
                    status_code=400,
                    detail="User already has a personal workspace. Only one personal workspace is allowed.",
                )
            # Personal workspaces cannot be visible to org or have a domain
            domain = None
            visible_to_org = False
        else:
            # Auto-set domain if visible_to_org is True and no domain provided
            domain = workspace_data.domain
            if workspace_data.visible_to_org and not domain:
                user_email = user.email
                domain = user_email.split("@")[1] if "@" in user_email else None
            visible_to_org = workspace_data.visible_to_org

        # Create workspace
        workspace_id = str(uuid.uuid4())
        new_workspace = Workspace(
            id=workspace_id,
            name=workspace_data.name,
            type=DBWorkspaceType(workspace_type.value),
            domain=domain,
            visible_to_org=visible_to_org,
        )

        db.add(new_workspace)
        await db.flush()  # Flush to get the workspace ID

        # Create membership with OWNER role for the creator
        membership_id = str(uuid.uuid4())
        membership = Membership(
            id=membership_id,
            user_id=owner_user_id,
            workspace_id=workspace_id,
            role=Role.OWNER,
        )

        db.add(membership)
        await db.commit()

        # Refresh to get the updated workspace
        await db.refresh(new_workspace)

        return WorkspaceResponse.model_validate(new_workspace)

    async def _get_user_personal_workspace(
        self, user_id: str, db: AsyncSession
    ) -> Optional[Workspace]:
        """Get user's personal workspace if it exists"""
        query = (
            select(Workspace)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(
                Membership.user_id == user_id,
                Workspace.type == DBWorkspaceType.PERSONAL,
            )
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_workspaces(
        self, user_id: str, db: AsyncSession
    ) -> List[WorkspaceWithMembership]:
        """Get all workspaces where the user is a member"""

        # Query memberships with workspace data, ordered by workspace creation date
        query = (
            select(Membership)
            .join(Workspace, Membership.workspace_id == Workspace.id)
            .options(selectinload(Membership.workspace))
            .where(Membership.user_id == user_id)
            .order_by(Workspace.created_at)
        )

        result = await db.execute(query)
        memberships = result.scalars().all()

        workspaces_with_membership = []
        for membership in memberships:
            workspace_data = {
                "id": membership.workspace.id,
                "name": membership.workspace.name,
                "type": WorkspaceType(membership.workspace.type.value),
                "domain": membership.workspace.domain,
                "visible_to_org": membership.workspace.visible_to_org,
                "is_paid": membership.workspace.is_paid,
                "created_at": membership.workspace.created_at,
                "user_role": membership.role,
            }
            workspaces_with_membership.append(
                WorkspaceWithMembership.model_validate(workspace_data)
            )

        return workspaces_with_membership

    async def get_workspace_by_id(
        self, workspace_id: str, user_id: str, db: AsyncSession
    ) -> Optional[WorkspaceWithMembership]:
        """Get a specific workspace if user is a member"""

        # Query membership to verify user has access and get role
        membership_query = (
            select(Membership)
            .options(selectinload(Membership.workspace))
            .where(
                Membership.workspace_id == workspace_id, Membership.user_id == user_id
            )
        )

        result = await db.execute(membership_query)
        membership = result.scalar_one_or_none()

        if not membership:
            return None

        workspace_data = {
            "id": membership.workspace.id,
            "name": membership.workspace.name,
            "type": WorkspaceType(membership.workspace.type.value),
            "domain": membership.workspace.domain,
            "visible_to_org": membership.workspace.visible_to_org,
            "is_paid": membership.workspace.is_paid,
            "created_at": membership.workspace.created_at,
            "user_role": membership.role,
        }

        return WorkspaceWithMembership.model_validate(workspace_data)

    async def update_last_visited_workspace(
        self, user_id: str, workspace_id: str, db: AsyncSession
    ) -> bool:
        """Update the last visited workspace for a user"""
        # Verify user has access to this workspace
        membership_query = select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user_id
        )
        result = await db.execute(membership_query)
        membership = result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403,
                detail="User does not have access to this workspace",
            )

        # Update the user's last visited workspace
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.last_visited_workspace_id = workspace_id
        await db.commit()

        return True

    async def get_visible_workspaces_by_domain(
        self, domain: str, db: AsyncSession
    ) -> List[WorkspaceResponse]:
        """Get workspaces that are visible to users with the given domain"""

        query = select(Workspace).where(
            Workspace.domain == domain, Workspace.visible_to_org is True
        )

        result = await db.execute(query)
        workspaces = result.scalars().all()

        return [WorkspaceResponse.model_validate(ws) for ws in workspaces]

    async def discover_workspaces_for_user(
        self, user_id: str, user_email: str, db: AsyncSession
    ) -> List[WorkspaceResponse]:
        """Discover workspaces available to a user based on their email domain (excludes workspaces they're already in)"""

        # Extract domain from user email
        domain = user_email.split("@")[1] if "@" in user_email else None

        if not domain:
            return []

        # Get all visible workspaces for this domain
        visible_workspaces = await self.get_visible_workspaces_by_domain(
            domain=domain, db=db
        )

        # Get workspaces where user is already a member
        user_memberships_query = select(Membership.workspace_id).where(
            Membership.user_id == user_id
        )
        result = await db.execute(user_memberships_query)
        user_workspace_ids = {row[0] for row in result.fetchall()}

        # Filter out workspaces where user is already a member
        discoverable_workspaces = [
            ws for ws in visible_workspaces if ws.id not in user_workspace_ids
        ]

        return discoverable_workspaces

    async def update_workspace_visibility(
        self, workspace_id: str, user_id: str, visible_to_org: bool, db: AsyncSession
    ) -> WorkspaceResponse:
        """Update workspace visibility and auto-set domain if needed"""

        # First verify user is owner of the workspace
        membership_query = (
            select(Membership)
            .options(selectinload(Membership.workspace), selectinload(Membership.user))
            .where(
                Membership.workspace_id == workspace_id,
                Membership.user_id == user_id,
                Membership.role == Role.OWNER,
            )
        )

        result = await db.execute(membership_query)
        membership = result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403,
                detail="Only workspace owners can update visibility settings",
            )

        workspace = membership.workspace

        # If setting visible_to_org to True, auto-set domain from owner's email
        if visible_to_org and not workspace.domain:
            user_email = membership.user.email
            domain = user_email.split("@")[1] if "@" in user_email else None
            workspace.domain = domain

        # If setting visible_to_org to False, optionally clear domain (keep for now)
        # This allows users to keep domain set even when not visible to org

        workspace.visible_to_org = visible_to_org

        await db.commit()
        await db.refresh(workspace)

        return WorkspaceResponse.model_validate(workspace)

    async def update_workspace_name(
        self, workspace_id: str, user_id: str, new_name: str, db: AsyncSession
    ) -> WorkspaceResponse:
        """Update workspace name (only owners can update)"""

        # First verify user is owner of the workspace
        membership_query = (
            select(Membership)
            .options(selectinload(Membership.workspace))
            .where(
                Membership.workspace_id == workspace_id,
                Membership.user_id == user_id,
                Membership.role == Role.OWNER,
            )
        )

        result = await db.execute(membership_query)
        membership = result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403,
                detail="Only workspace owners can update workspace name",
            )

        workspace = membership.workspace
        workspace.name = new_name

        await db.commit()
        await db.refresh(workspace)

        return WorkspaceResponse.model_validate(workspace)

    async def create_personal_workspace(
        self, user: User, db: AsyncSession
    ) -> WorkspaceResponse:
        """Create a personal workspace for a user"""

        # Use full name for workspace name
        workspace_name = f"{user.name}'s Workspace"

        workspace_data = WorkspaceCreate(
            name=workspace_name,
            type=WorkspaceType.PERSONAL,  # Explicitly set as personal workspace
            domain=None,  # Personal workspaces don't have a domain
            visible_to_org=False,  # Personal workspaces are not visible to org
        )

        return await self.create_workspace(
            workspace_data=workspace_data, owner_user_id=user.id, db=db
        )

    async def delete_workspace(
        self, workspace_id: str, user_id: str, db: AsyncSession
    ) -> bool:
        """Delete a workspace if user is the owner.

        This also revokes any GitHub App installations associated with the workspace
        to ensure clean removal of external integrations.
        """

        # Verify user is the owner of the workspace
        membership_query = (
            select(Membership)
            .options(selectinload(Membership.workspace))
            .where(
                Membership.workspace_id == workspace_id,
                Membership.user_id == user_id,
                Membership.role == Role.OWNER,
            )
        )

        result = await db.execute(membership_query)
        membership = result.scalar_one_or_none()

        if not membership:
            raise HTTPException(
                status_code=403, detail="Only workspace owners can delete workspaces"
            )

        workspace = membership.workspace

        # Revoke GitHub App installations before deleting workspace
        await self._revoke_github_installations(workspace_id, db)

        # Delete the workspace (cascade will handle related records)
        await db.delete(workspace)
        await db.commit()

        return True

    async def _revoke_github_installations(
        self, workspace_id: str, db: AsyncSession
    ) -> None:
        """Revoke GitHub App installations for a workspace.

        This ensures the GitHub App is uninstalled from the user's GitHub account
        when the workspace is deleted, preventing orphaned installations.
        """
        # Import here to avoid circular imports
        from app.github.oauth.service import GitHubAppService

        github_service = GitHubAppService()

        # Find all GitHub integrations for this workspace
        github_query = select(GitHubIntegration).where(
            GitHubIntegration.workspace_id == workspace_id
        )
        result = await db.execute(github_query)
        github_integrations = result.scalars().all()

        for integration in github_integrations:
            try:
                await github_service.uninstall_github_app(integration.installation_id)
                logger.info(
                    f"Revoked GitHub App installation {integration.installation_id} "
                    f"for workspace {workspace_id}"
                )
            except Exception as e:
                # Log but don't fail - the installation might already be revoked
                # or the user might have manually removed it
                logger.warning(
                    f"Failed to revoke GitHub App installation {integration.installation_id} "
                    f"for workspace {workspace_id}: {e}. Continuing with workspace deletion."
                )
