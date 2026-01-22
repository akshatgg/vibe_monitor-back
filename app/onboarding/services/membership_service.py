"""
Membership Service for workspace invitation and member management.
"""

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    InvitationStatus,
    Membership,
    Role,
    User,
    Workspace,
    WorkspaceInvitation,
)

from ..schemas.schemas import InvitationCreate, InvitationResponse
from ..schemas.schemas import InvitationStatus as SchemaInvitationStatus
from ..schemas.schemas import MemberResponse, MemberRoleUpdate
from ..schemas.schemas import Role as SchemaRole
from ..schemas.schemas import WorkspaceWithMembership

logger = logging.getLogger(__name__)

# Constants
INVITATION_EXPIRY_DAYS = 7


class MembershipService:
    """Service for managing workspace invitations and memberships."""

    # =========================================================================
    # Invitation Management (Owner-only operations)
    # =========================================================================

    async def invite_member(
        self,
        workspace_id: str,
        inviter_id: str,
        invitation_data: InvitationCreate,
        db: AsyncSession,
    ) -> InvitationResponse:
        """
        Invite a user to a workspace.

        Validations:
        1. Inviter must be OWNER of workspace
        2. Invitee must not already be a member
        3. No pending invitation for same email exists
        4. Cannot invite yourself
        """
        # Get workspace and verify it exists
        workspace_result = await db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = workspace_result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Validation 1: Verify inviter is OWNER
        inviter_membership = await self._get_membership(
            workspace_id=workspace_id, user_id=inviter_id, db=db
        )

        if not inviter_membership or inviter_membership.role != Role.OWNER:
            raise HTTPException(
                status_code=403,
                detail="Only workspace owners can invite members",
            )

        # Get inviter info for response
        inviter_result = await db.execute(select(User).where(User.id == inviter_id))
        inviter = inviter_result.scalar_one_or_none()

        invitee_email = invitation_data.email.lower().strip()

        # Validation 5: Cannot invite yourself
        if inviter and inviter.email.lower() == invitee_email:
            raise HTTPException(
                status_code=400,
                detail="Cannot invite yourself to a workspace",
            )

        # Check if invitee already exists in the system
        invitee_result = await db.execute(
            select(User).where(func.lower(User.email) == invitee_email)
        )
        invitee = invitee_result.scalar_one_or_none()

        # Validation 3: Check if invitee is already a member
        if invitee:
            existing_membership = await self._get_membership(
                workspace_id=workspace_id, user_id=invitee.id, db=db
            )
            if existing_membership:
                raise HTTPException(
                    status_code=400,
                    detail="User is already a member of this workspace",
                )

        # Validation 4: Check for existing pending invitation
        existing_invitation_result = await db.execute(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.workspace_id == workspace_id,
                func.lower(WorkspaceInvitation.invitee_email) == invitee_email,
                WorkspaceInvitation.status == InvitationStatus.PENDING,
            )
        )
        existing_invitation = existing_invitation_result.scalar_one_or_none()

        if existing_invitation:
            # Check if invitation is expired
            if existing_invitation.expires_at < datetime.now(timezone.utc):
                # Mark as expired and allow re-invite
                existing_invitation.status = InvitationStatus.EXPIRED
                await db.flush()
            else:
                raise HTTPException(
                    status_code=400,
                    detail="A pending invitation already exists for this email",
                )

        # Create invitation
        invitation_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_EXPIRY_DAYS)

        # Map schema role to DB role
        db_role = Role.OWNER if invitation_data.role == SchemaRole.OWNER else Role.USER

        invitation = WorkspaceInvitation(
            id=invitation_id,
            workspace_id=workspace_id,
            inviter_id=inviter_id,
            invitee_email=invitee_email,
            invitee_id=invitee.id if invitee else None,
            role=db_role,
            status=InvitationStatus.PENDING,
            token=token,
            expires_at=expires_at,
        )

        db.add(invitation)
        await db.commit()
        await db.refresh(invitation)

        # Send invitation email
        try:
            from app.email_service.service import email_service

            await email_service.send_invitation_email(
                invitee_email=invitee_email,
                workspace_name=workspace.name,
                inviter_name=inviter.name if inviter else "A team member",
                role=invitation_data.role.value,
                token=token,
            )
        except Exception as e:
            # Log error but don't fail the invitation creation
            logger.error(f"Failed to send invitation email: {e}")

        return InvitationResponse(
            id=invitation.id,
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            inviter_name=inviter.name if inviter else "Unknown",
            invitee_email=invitation.invitee_email,
            role=SchemaRole(invitation.role.value),
            status=SchemaInvitationStatus(invitation.status.value),
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )

    async def list_workspace_invitations(
        self,
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> List[InvitationResponse]:
        """List pending invitations for a workspace (owner only)."""
        # Verify user is OWNER
        membership = await self._get_membership(
            workspace_id=workspace_id, user_id=user_id, db=db
        )

        if not membership or membership.role != Role.OWNER:
            raise HTTPException(
                status_code=403,
                detail="Only workspace owners can view invitations",
            )

        # Get workspace for name
        workspace_result = await db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = workspace_result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Query pending invitations
        query = (
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.inviter))
            .where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.status == InvitationStatus.PENDING,
            )
            .order_by(WorkspaceInvitation.created_at.desc())
        )

        result = await db.execute(query)
        invitations = result.scalars().all()

        # Mark expired invitations
        now = datetime.now(timezone.utc)
        responses = []
        for inv in invitations:
            status = inv.status
            if inv.expires_at < now:
                inv.status = InvitationStatus.EXPIRED
                status = InvitationStatus.EXPIRED
                await db.flush()

            if status == InvitationStatus.PENDING:
                responses.append(
                    InvitationResponse(
                        id=inv.id,
                        workspace_id=workspace.id,
                        workspace_name=workspace.name,
                        inviter_name=inv.inviter.name if inv.inviter else "Unknown",
                        invitee_email=inv.invitee_email,
                        role=SchemaRole(inv.role.value),
                        status=SchemaInvitationStatus(status.value),
                        expires_at=inv.expires_at,
                        created_at=inv.created_at,
                    )
                )

        await db.commit()
        return responses

    async def cancel_invitation(
        self,
        workspace_id: str,
        invitation_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> bool:
        """Cancel a pending invitation (owner only)."""
        # Verify user is OWNER
        membership = await self._get_membership(
            workspace_id=workspace_id, user_id=user_id, db=db
        )

        if not membership or membership.role != Role.OWNER:
            raise HTTPException(
                status_code=403,
                detail="Only workspace owners can cancel invitations",
            )

        # Get invitation
        invitation_result = await db.execute(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.id == invitation_id,
                WorkspaceInvitation.workspace_id == workspace_id,
            )
        )
        invitation = invitation_result.scalar_one_or_none()

        if not invitation:
            raise HTTPException(status_code=404, detail="Invitation not found")

        if invitation.status != InvitationStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel invitation with status: {invitation.status.value}",
            )

        # Delete the invitation
        await db.delete(invitation)
        await db.commit()

        return True

    # =========================================================================
    # User Invitation Operations
    # =========================================================================

    async def get_my_invitations(
        self,
        user_id: str,
        user_email: str,
        db: AsyncSession,
    ) -> List[InvitationResponse]:
        """Get all pending invitations for the current user."""
        user_email_lower = user_email.lower()

        # Query pending invitations for this email
        query = (
            select(WorkspaceInvitation)
            .options(
                selectinload(WorkspaceInvitation.workspace),
                selectinload(WorkspaceInvitation.inviter),
            )
            .where(
                func.lower(WorkspaceInvitation.invitee_email) == user_email_lower,
                WorkspaceInvitation.status == InvitationStatus.PENDING,
            )
            .order_by(WorkspaceInvitation.created_at.desc())
        )

        result = await db.execute(query)
        invitations = result.scalars().all()

        # Process invitations and mark expired ones
        now = datetime.now(timezone.utc)
        responses = []
        for inv in invitations:
            if inv.expires_at < now:
                inv.status = InvitationStatus.EXPIRED
                await db.flush()
                continue

            responses.append(
                InvitationResponse(
                    id=inv.id,
                    workspace_id=inv.workspace.id,
                    workspace_name=inv.workspace.name,
                    inviter_name=inv.inviter.name if inv.inviter else "Unknown",
                    invitee_email=inv.invitee_email,
                    role=SchemaRole(inv.role.value),
                    status=SchemaInvitationStatus(inv.status.value),
                    expires_at=inv.expires_at,
                    created_at=inv.created_at,
                )
            )

        await db.commit()
        return responses

    async def accept_invitation(
        self,
        invitation_id: str,
        user_id: str,
        user_email: str,
        db: AsyncSession,
    ) -> WorkspaceWithMembership:
        """
        Accept an invitation.

        Actions:
        1. Verify invitation is pending and not expired
        2. Verify user email matches invitee_email
        3. Create membership with specified role
        4. Update invitation status to ACCEPTED
        5. Return the workspace with membership
        """
        # Get invitation with workspace
        invitation_result = await db.execute(
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.workspace))
            .where(WorkspaceInvitation.id == invitation_id)
        )
        invitation = invitation_result.scalar_one_or_none()

        if not invitation:
            raise HTTPException(status_code=404, detail="Invitation not found")

        # Verify user email matches
        if user_email.lower() != invitation.invitee_email.lower():
            raise HTTPException(
                status_code=403,
                detail="This invitation was sent to a different email address",
            )

        # Verify invitation is pending
        if invitation.status != InvitationStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"Invitation has already been {invitation.status.value}",
            )

        # Check if expired
        if invitation.expires_at < datetime.now(timezone.utc):
            invitation.status = InvitationStatus.EXPIRED
            await db.commit()
            raise HTTPException(
                status_code=400,
                detail="This invitation has expired. Please ask for a new invitation.",
            )

        # Check if user is already a member
        existing_membership = await self._get_membership(
            workspace_id=invitation.workspace_id, user_id=user_id, db=db
        )
        if existing_membership:
            # Already a member, just mark invitation as accepted
            invitation.status = InvitationStatus.ACCEPTED
            invitation.responded_at = datetime.now(timezone.utc)
            invitation.invitee_id = user_id
            await db.commit()

            return WorkspaceWithMembership(
                id=invitation.workspace.id,
                name=invitation.workspace.name,
                domain=invitation.workspace.domain,
                visible_to_org=invitation.workspace.visible_to_org,
                is_paid=invitation.workspace.is_paid,
                created_at=invitation.workspace.created_at,
                user_role=SchemaRole(existing_membership.role.value),
            )

        # Create membership
        membership_id = str(uuid.uuid4())
        membership = Membership(
            id=membership_id,
            user_id=user_id,
            workspace_id=invitation.workspace_id,
            role=invitation.role,
        )
        db.add(membership)

        # Update invitation
        invitation.status = InvitationStatus.ACCEPTED
        invitation.responded_at = datetime.now(timezone.utc)
        invitation.invitee_id = user_id

        # Update user's last visited workspace to the newly joined workspace
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.last_visited_workspace_id = invitation.workspace_id

        await db.commit()
        await db.refresh(invitation.workspace)

        return WorkspaceWithMembership(
            id=invitation.workspace.id,
            name=invitation.workspace.name,
            domain=invitation.workspace.domain,
            visible_to_org=invitation.workspace.visible_to_org,
            is_paid=invitation.workspace.is_paid,
            created_at=invitation.workspace.created_at,
            user_role=SchemaRole(invitation.role.value),
        )

    async def decline_invitation(
        self,
        invitation_id: str,
        user_id: str,
        user_email: str,
        db: AsyncSession,
    ) -> bool:
        """Decline an invitation."""
        # Get invitation
        invitation_result = await db.execute(
            select(WorkspaceInvitation).where(WorkspaceInvitation.id == invitation_id)
        )
        invitation = invitation_result.scalar_one_or_none()

        if not invitation:
            raise HTTPException(status_code=404, detail="Invitation not found")

        # Verify user email matches
        if user_email.lower() != invitation.invitee_email.lower():
            raise HTTPException(
                status_code=403,
                detail="This invitation was sent to a different email address",
            )

        # Verify invitation is pending
        if invitation.status != InvitationStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"Invitation has already been {invitation.status.value}",
            )

        # Update invitation
        invitation.status = InvitationStatus.DECLINED
        invitation.responded_at = datetime.now(timezone.utc)
        invitation.invitee_id = user_id

        await db.commit()

        return True

    async def get_invitation_by_token(
        self,
        token: str,
        db: AsyncSession,
    ) -> Optional[InvitationResponse]:
        """
        Get invitation details by token (for accept flow).

        Returns invitation info without requiring authentication.
        """
        result = await db.execute(
            select(WorkspaceInvitation)
            .options(
                selectinload(WorkspaceInvitation.workspace),
                selectinload(WorkspaceInvitation.inviter),
            )
            .where(WorkspaceInvitation.token == token)
        )
        invitation = result.scalar_one_or_none()

        if not invitation:
            return None

        return InvitationResponse(
            id=invitation.id,
            workspace_id=invitation.workspace.id,
            workspace_name=invitation.workspace.name,
            inviter_name=invitation.inviter.name if invitation.inviter else "Unknown",
            invitee_email=invitation.invitee_email,
            role=SchemaRole(invitation.role.value),
            status=SchemaInvitationStatus(invitation.status.value),
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
        )

    async def accept_invitation_by_token(
        self,
        token: str,
        user_id: str,
        user_email: str,
        db: AsyncSession,
    ) -> WorkspaceWithMembership:
        """
        Accept an invitation using the token from the email.

        Same logic as accept_invitation but looks up by token.
        """
        # Get invitation by token
        result = await db.execute(
            select(WorkspaceInvitation)
            .options(selectinload(WorkspaceInvitation.workspace))
            .where(WorkspaceInvitation.token == token)
        )
        invitation = result.scalar_one_or_none()

        if not invitation:
            raise HTTPException(status_code=404, detail="Invalid invitation link")

        # Delegate to the standard accept method using the invitation ID
        return await self.accept_invitation(
            invitation_id=invitation.id,
            user_id=user_id,
            user_email=user_email,
            db=db,
        )

    # =========================================================================
    # Member Management
    # =========================================================================

    async def list_members(
        self,
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> List[MemberResponse]:
        """List all members of a workspace."""
        # Verify user is a member of the workspace
        user_membership = await self._get_membership(
            workspace_id=workspace_id, user_id=user_id, db=db
        )

        if not user_membership:
            raise HTTPException(
                status_code=403,
                detail="You are not a member of this workspace",
            )

        # Query all memberships
        query = (
            select(Membership)
            .options(selectinload(Membership.user))
            .where(Membership.workspace_id == workspace_id)
            .order_by(Membership.created_at)
        )

        result = await db.execute(query)
        memberships = result.scalars().all()

        return [
            MemberResponse(
                user_id=m.user.id,
                user_name=m.user.name,
                user_email=m.user.email,
                role=SchemaRole(m.role.value),
                joined_at=m.created_at,
            )
            for m in memberships
        ]

    async def update_member_role(
        self,
        workspace_id: str,
        member_user_id: str,
        role_update: MemberRoleUpdate,
        requesting_user_id: str,
        db: AsyncSession,
    ) -> MemberResponse:
        """
        Update a member's role.

        Validations:
        1. Requester must be OWNER
        2. Cannot demote the last OWNER
        3. Cannot change own role if sole owner
        """
        # Validation 1: Verify requester is OWNER
        requester_membership = await self._get_membership(
            workspace_id=workspace_id, user_id=requesting_user_id, db=db
        )

        if not requester_membership or requester_membership.role != Role.OWNER:
            raise HTTPException(
                status_code=403,
                detail="Only workspace owners can update member roles",
            )

        # Get target member's membership
        target_membership = await self._get_membership(
            workspace_id=workspace_id, user_id=member_user_id, db=db
        )

        if not target_membership:
            raise HTTPException(status_code=404, detail="Member not found")

        # Map schema role to DB role
        new_role = Role.OWNER if role_update.role == SchemaRole.OWNER else Role.USER

        # Validation 2 & 3: Check last owner protection
        if target_membership.role == Role.OWNER and new_role == Role.USER:
            # Demoting an owner - check if they're the last owner
            owner_count = await self._count_owners(workspace_id=workspace_id, db=db)
            if owner_count <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot demote the last owner. Promote another member to owner first.",
                )

        # Update role
        target_membership.role = new_role
        await db.commit()
        await db.refresh(target_membership)

        # Get user for response
        user_result = await db.execute(select(User).where(User.id == member_user_id))
        user = user_result.scalar_one()

        return MemberResponse(
            user_id=user.id,
            user_name=user.name,
            user_email=user.email,
            role=SchemaRole(target_membership.role.value),
            joined_at=target_membership.created_at,
        )

    async def remove_member(
        self,
        workspace_id: str,
        member_user_id: str,
        requesting_user_id: str,
        db: AsyncSession,
    ) -> bool:
        """
        Remove a member from workspace.

        Validations:
        1. Requester must be OWNER
        2. Cannot remove the last OWNER
        3. Cannot remove self if sole owner
        """
        # Validation 1: Verify requester is OWNER
        requester_membership = await self._get_membership(
            workspace_id=workspace_id, user_id=requesting_user_id, db=db
        )

        if not requester_membership or requester_membership.role != Role.OWNER:
            raise HTTPException(
                status_code=403,
                detail="Only workspace owners can remove members",
            )

        # Get target member's membership
        target_membership = await self._get_membership(
            workspace_id=workspace_id, user_id=member_user_id, db=db
        )

        if not target_membership:
            raise HTTPException(status_code=404, detail="Member not found")

        # Validation 2 & 3: Check last owner protection
        if target_membership.role == Role.OWNER:
            owner_count = await self._count_owners(workspace_id=workspace_id, db=db)
            if owner_count <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot remove the last owner. Transfer ownership to another member first.",
                )

        # Remove membership
        await db.delete(target_membership)
        await db.commit()

        return True

    async def leave_workspace(
        self,
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> bool:
        """
        Leave a workspace voluntarily.

        Validations:
        1. Cannot leave if sole OWNER (must transfer ownership or delete workspace)
        """
        # Get workspace
        workspace_result = await db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = workspace_result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Get user's membership
        membership = await self._get_membership(
            workspace_id=workspace_id, user_id=user_id, db=db
        )

        if not membership:
            raise HTTPException(
                status_code=400,
                detail="You are not a member of this workspace",
            )

        # Validation 1: Check last owner protection
        if membership.role == Role.OWNER:
            owner_count = await self._count_owners(workspace_id=workspace_id, db=db)
            if owner_count <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot leave as the last owner. Transfer ownership to another member or delete the workspace.",
                )

        # Remove membership
        await db.delete(membership)
        await db.commit()

        return True

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _get_membership(
        self,
        workspace_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Optional[Membership]:
        """Get a user's membership in a workspace."""
        result = await db.execute(
            select(Membership).where(
                Membership.workspace_id == workspace_id,
                Membership.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _count_owners(
        self,
        workspace_id: str,
        db: AsyncSession,
    ) -> int:
        """Count the number of owners in a workspace."""
        result = await db.execute(
            select(func.count(Membership.id)).where(
                Membership.workspace_id == workspace_id,
                Membership.role == Role.OWNER,
            )
        )
        return result.scalar() or 0
