import logging
import uuid
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import GitHubIntegration, Membership, PlanType, Role, User, Workspace
from app.core.otel_metrics import WORKSPACE_METRICS
from app.billing.services.subscription_service import SubscriptionService

from ..schemas.schemas import (
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceWithMembership,
)

logger = logging.getLogger(__name__)


class WorkspaceService:
    def __init__(self):
        self.subscription_service = SubscriptionService()

    async def create_workspace(
        self, workspace_data: WorkspaceCreate, owner_user_id: str, db: AsyncSession
    ) -> WorkspaceWithMembership:
        """Create a new workspace and assign the creator as owner"""

        # Get user info to extract domain if needed
        user_result = await db.execute(select(User).where(User.id == owner_user_id))
        user = user_result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

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

        # Create FREE subscription for new workspace
        free_plan = await self.subscription_service.get_plan_by_type(db, PlanType.FREE)
        if free_plan:
            await self.subscription_service.create_subscription(
                db=db,
                workspace_id=workspace_id,
                plan_id=free_plan.id,
            )
            logger.info(f"Created FREE subscription for workspace {workspace_id}")
        else:
            logger.warning(
                f"FREE plan not found, workspace {workspace_id} created without subscription"
            )

        await db.commit()

        # Refresh to get the updated workspace
        await db.refresh(new_workspace)

        if metric := WORKSPACE_METRICS.get("workspace_created_total"):
            metric.add(1)
        if metric := WORKSPACE_METRICS.get("active_workspaces"):
            metric.add(1)

        # Return workspace with membership role
        workspace_data_dict = {
            "id": new_workspace.id,
            "name": new_workspace.name,
            "domain": new_workspace.domain,
            "visible_to_org": new_workspace.visible_to_org,
            "is_paid": new_workspace.is_paid,
            "created_at": new_workspace.created_at,
            "user_role": Role.OWNER,  # Creator is always the owner
        }

        return WorkspaceWithMembership.model_validate(workspace_data_dict)

    async def ensure_user_has_default_workspace(
        self, user_id: str, user_name: str, db: AsyncSession
    ) -> Optional[WorkspaceWithMembership]:
        """
        Ensure user has at least one workspace. If not, create a default one.

        Args:
            user_id: User ID to check/create workspace for
            user_name: User's name for creating workspace name
            db: Database session

        Returns:
            The created workspace if one was created, None if user already has workspaces
        """
        # Check if user already has any workspaces
        existing_workspaces = await self.get_user_workspaces(user_id=user_id, db=db)

        if existing_workspaces:
            logger.info(
                f"User {user_id} already has {len(existing_workspaces)} workspace(s), "
                "skipping default workspace creation"
            )
            return None

        # Create default workspace
        default_workspace_data = WorkspaceCreate(
            name=f"{user_name}'s Workspace",
            domain=None,
            visible_to_org=False,
        )
        workspace = await self.create_workspace(
            workspace_data=default_workspace_data, owner_user_id=user_id, db=db
        )

        # Update user's last_visited_workspace_id
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        if user:
            user.last_visited_workspace_id = workspace.id
            await db.commit()

        logger.info(f"Created default workspace {workspace.id} for user {user_id}")
        return workspace

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

        # Delete S3 files before cascade delete removes DB records
        await self._delete_workspace_files(workspace_id, db)

        # Delete the workspace (cascade will handle related records)
        await db.delete(workspace)
        await db.commit()

        if metric := WORKSPACE_METRICS.get("active_workspaces"):
            metric.add(-1)

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

    async def _delete_workspace_files(
        self, workspace_id: str, db: AsyncSession
    ) -> None:
        """Delete all S3 files associated with a workspace.

        This must be called before cascade delete removes the DB records,
        otherwise we lose the S3 keys needed to clean up the files.
        """
        from app.services.s3.client import s3_client

        # Get all S3 keys for files in this workspace
        query = (
            select(ChatFile.s3_key)
            .join(ChatTurn, ChatFile.turn_id == ChatTurn.id)
            .join(ChatSession, ChatTurn.session_id == ChatSession.id)
            .where(ChatSession.workspace_id == workspace_id)
        )
        result = await db.execute(query)
        s3_keys = [row[0] for row in result.fetchall()]

        if s3_keys:
            await s3_client.delete_files(s3_keys)
            logger.info(f"Deleted {len(s3_keys)} S3 files for workspace {workspace_id}")
