"""
Account service for handling account deletion with workspace ownership constraints.
"""

import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.models import (
    User,
    Workspace,
    Membership,
    Role,
    RefreshToken,
    EmailVerification,
    Email,
    ChatSession,
)
from app.auth.schemas.account_schemas import (
    DeletionPreviewResponse,
    BlockingWorkspace,
    WorkspacePreview,
    AccountDeleteResponse,
    WorkspaceType,
    Role as SchemaRole,
)

logger = logging.getLogger(__name__)


class AccountService:
    """Service for account management including deletion."""

    def __init__(self, credential_auth_service=None):
        """
        Initialize account service.

        Args:
            credential_auth_service: Optional CredentialAuthService instance for password verification
        """
        self.credential_auth_service = credential_auth_service

    async def get_deletion_preview(
        self,
        user_id: str,
        db: AsyncSession,
    ) -> DeletionPreviewResponse:
        """
        Analyze what will happen when user deletes their account.

        Returns a preview with:
        - can_delete: Whether deletion is allowed
        - blocking_workspaces: Workspaces that prevent deletion (sole owner with other members)
        - workspaces_to_delete: Workspaces that will be deleted (sole member)
        - workspaces_to_leave: Workspaces user will be removed from (co-owner or member)

        Args:
            user_id: ID of the user requesting deletion
            db: Database session

        Returns:
            DeletionPreviewResponse with deletion analysis
        """
        # Get all memberships for the user with workspace data
        memberships_query = (
            select(Membership)
            .options(selectinload(Membership.workspace))
            .where(Membership.user_id == user_id)
        )
        result = await db.execute(memberships_query)
        user_memberships = result.scalars().all()

        blocking_workspaces: list[BlockingWorkspace] = []
        workspaces_to_delete: list[WorkspacePreview] = []
        workspaces_to_leave: list[WorkspacePreview] = []

        for membership in user_memberships:
            workspace = membership.workspace
            user_role = membership.role

            # Get workspace statistics
            stats = await self._get_workspace_member_stats(workspace.id, db)
            total_members = stats["total_members"]
            total_owners = stats["total_owners"]

            workspace_type = WorkspaceType(workspace.type.value)
            schema_role = SchemaRole(user_role.value)

            # Decision logic based on workspace type and ownership
            if user_role == Role.OWNER:
                is_sole_owner = total_owners == 1
                has_other_members = total_members > 1

                if is_sole_owner and has_other_members:
                    # BLOCK: Sole owner with other members
                    other_member_count = total_members - 1
                    blocking_workspaces.append(
                        BlockingWorkspace(
                            id=workspace.id,
                            name=workspace.name,
                            type=workspace_type,
                            member_count=total_members,
                            action_required=f"Transfer ownership to another member or remove all {other_member_count} other member{'s' if other_member_count > 1 else ''}",
                        )
                    )
                elif is_sole_owner and not has_other_members:
                    # DELETE: Sole owner and sole member (personal workspace or empty team)
                    workspaces_to_delete.append(
                        WorkspacePreview(
                            id=workspace.id,
                            name=workspace.name,
                            type=workspace_type,
                            user_role=schema_role,
                        )
                    )
                else:
                    # LEAVE: Co-owner (there are other owners)
                    workspaces_to_leave.append(
                        WorkspacePreview(
                            id=workspace.id,
                            name=workspace.name,
                            type=workspace_type,
                            user_role=schema_role,
                        )
                    )
            else:
                # LEAVE: User is just a member (not an owner)
                workspaces_to_leave.append(
                    WorkspacePreview(
                        id=workspace.id,
                        name=workspace.name,
                        type=workspace_type,
                        user_role=schema_role,
                    )
                )

        # Determine if deletion is possible
        can_delete = len(blocking_workspaces) == 0

        # Generate human-readable message
        if not can_delete:
            blocking_count = len(blocking_workspaces)
            message = f"Cannot delete account. You are the sole owner of {blocking_count} workspace{'s' if blocking_count > 1 else ''} with other members. Please transfer ownership or remove members first."
        else:
            parts = []
            if workspaces_to_delete:
                parts.append(
                    f"{len(workspaces_to_delete)} workspace{'s' if len(workspaces_to_delete) > 1 else ''} will be deleted"
                )
            if workspaces_to_leave:
                parts.append(
                    f"you will be removed from {len(workspaces_to_leave)} workspace{'s' if len(workspaces_to_leave) > 1 else ''}"
                )

            if parts:
                message = f"Your account can be deleted. {' and '.join(parts)}."
            else:
                message = "Your account can be deleted."

        return DeletionPreviewResponse(
            can_delete=can_delete,
            blocking_workspaces=blocking_workspaces,
            workspaces_to_delete=workspaces_to_delete,
            workspaces_to_leave=workspaces_to_leave,
            message=message,
        )

    async def delete_account(
        self,
        user_id: str,
        confirmation: str,
        password: Optional[str],
        db: AsyncSession,
    ) -> AccountDeleteResponse:
        """
        Delete user account with all constraints.

        Steps:
        1. Verify confirmation string (must be 'DELETE' or user's email)
        2. For password-based accounts, verify password
        3. Re-run deletion preview to ensure still valid
        4. If blocking workspaces exist, raise error
        5. Delete workspaces where user is sole owner
        6. Remove memberships where user is not sole owner
        7. Cascade delete: refresh tokens, email verifications, emails, chat sessions
        8. Delete user record
        9. Return summary

        Args:
            user_id: ID of the user to delete
            confirmation: Must be 'DELETE' or user's email
            password: Required for credential-based accounts
            db: Database session

        Returns:
            AccountDeleteResponse with deletion summary
        """
        # Get user
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Verify confirmation string
        if confirmation != "DELETE" and confirmation.lower() != user.email.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please type 'DELETE' or your email address to confirm account deletion.",
            )

        # For credential-based accounts (has password), verify password
        if user.password_hash is not None:
            if password is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password is required for credential-based accounts.",
                )

            if self.credential_auth_service is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Password verification service not available.",
                )

            if not self.credential_auth_service.verify_password(
                password, user.password_hash
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid password.",
                )
        else:
            # OAuth user provides password
            if password is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Password not required for OAuth accounts.",
                )

        # Re-run deletion preview to ensure still valid (state might have changed)
        preview = await self.get_deletion_preview(user_id, db)

        if not preview.can_delete:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=preview.message,
            )

        deleted_workspaces: list[str] = []
        left_workspaces: list[str] = []

        try:
            # Process workspaces to delete (where user is sole owner with no other members)
            for ws_preview in preview.workspaces_to_delete:
                await self._delete_workspace_and_data(ws_preview.id, db)
                deleted_workspaces.append(ws_preview.id)
                logger.info(
                    f"Deleted workspace {ws_preview.id} ({ws_preview.name}) during account deletion for user {user_id}"
                )

            # Process workspaces to leave (remove membership)
            for ws_preview in preview.workspaces_to_leave:
                await self._remove_user_from_workspace(user_id, ws_preview.id, db)
                left_workspaces.append(ws_preview.id)
                logger.info(
                    f"Removed user {user_id} from workspace {ws_preview.id} ({ws_preview.name})"
                )

            # Delete user-related data (cascade)
            await self._delete_user_data(user_id, db)

            # Finally, delete the user record
            await db.delete(user)
            await db.commit()

            logger.info(
                f"Successfully deleted account for user {user_id} ({user.email})"
            )

            return AccountDeleteResponse(
                success=True,
                deleted_workspaces=deleted_workspaces,
                left_workspaces=left_workspaces,
                message=f"Account deleted successfully. {len(deleted_workspaces)} workspace(s) deleted, removed from {len(left_workspaces)} workspace(s).",
            )

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to delete account for user {user_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete account. Please try again later.",
            )

    async def _get_workspace_member_stats(
        self,
        workspace_id: str,
        db: AsyncSession,
    ) -> dict:
        """
        Get member count and owner count for a workspace.

        Args:
            workspace_id: Workspace ID
            db: Database session

        Returns:
            Dict with 'total_members' and 'total_owners'
        """
        # Count total members
        total_members_result = await db.execute(
            select(func.count(Membership.id)).where(
                Membership.workspace_id == workspace_id
            )
        )
        total_members = total_members_result.scalar() or 0

        # Count total owners
        total_owners_result = await db.execute(
            select(func.count(Membership.id)).where(
                Membership.workspace_id == workspace_id,
                Membership.role == Role.OWNER,
            )
        )
        total_owners = total_owners_result.scalar() or 0

        return {
            "total_members": total_members,
            "total_owners": total_owners,
        }

    async def _delete_workspace_and_data(
        self,
        workspace_id: str,
        db: AsyncSession,
    ) -> None:
        """
        Delete a workspace and all its related data.

        The order matters due to foreign key constraints.

        Args:
            workspace_id: Workspace ID to delete
            db: Database session
        """
        # Delete all memberships first
        await db.execute(
            delete(Membership).where(Membership.workspace_id == workspace_id)
        )

        # Get and delete the workspace
        # Note: Many tables have CASCADE delete on workspace_id, so they'll be auto-deleted
        workspace_result = await db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = workspace_result.scalar_one_or_none()

        if workspace:
            await db.delete(workspace)

        # Flush to apply changes before continuing
        await db.flush()

    async def _remove_user_from_workspace(
        self,
        user_id: str,
        workspace_id: str,
        db: AsyncSession,
    ) -> None:
        """
        Remove a user's membership from a workspace.

        Args:
            user_id: User ID
            workspace_id: Workspace ID
            db: Database session
        """
        await db.execute(
            delete(Membership).where(
                Membership.user_id == user_id,
                Membership.workspace_id == workspace_id,
            )
        )
        await db.flush()

    async def _delete_user_data(
        self,
        user_id: str,
        db: AsyncSession,
    ) -> None:
        """
        Delete all user-related data except the user record itself.

        Deletion order matters due to foreign key constraints.

        Args:
            user_id: User ID
            db: Database session
        """
        # Delete refresh tokens
        await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))

        # Delete email verifications
        await db.execute(
            delete(EmailVerification).where(EmailVerification.user_id == user_id)
        )

        # Delete emails
        await db.execute(delete(Email).where(Email.user_id == user_id))

        # Delete chat sessions (this will cascade to turns and steps)
        await db.execute(delete(ChatSession).where(ChatSession.user_id == user_id))

        # Clear last_visited_workspace_id reference (to avoid FK issues)
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.last_visited_workspace_id = None

        await db.flush()


# Singleton instance (will be initialized with credential_auth_service later)
account_service = AccountService()
