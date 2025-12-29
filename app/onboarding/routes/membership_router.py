"""
Membership Router for workspace invitations and member management.

Endpoints:
- POST   /workspaces/{workspace_id}/invitations       - Invite a user (Owner only)
- GET    /workspaces/{workspace_id}/invitations       - List pending invitations (Owner only)
- DELETE /workspaces/{workspace_id}/invitations/{id}  - Cancel invitation (Owner only)
- GET    /invitations                                  - List my pending invitations
- POST   /invitations/{id}/accept                      - Accept invitation
- POST   /invitations/{id}/decline                     - Decline invitation
- GET    /workspaces/{workspace_id}/members           - List workspace members
- PATCH  /workspaces/{workspace_id}/members/{user_id} - Update member role (Owner only)
- DELETE /workspaces/{workspace_id}/members/{user_id} - Remove member (Owner only)
- POST   /workspaces/{workspace_id}/leave             - Leave workspace voluntarily
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.models import User

from ...core.database import get_db
from ..schemas.schemas import (
    InvitationCreate,
    InvitationResponse,
    MemberResponse,
    MemberRoleUpdate,
    WorkspaceWithMembership,
)
from ..services.membership_service import MembershipService

router = APIRouter(tags=["membership"])
membership_service = MembershipService()
auth_service = AuthService()


# =============================================================================
# Invitation Management (Owner-only operations)
# =============================================================================


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationResponse,
)
async def invite_member(
    workspace_id: str,
    invitation_data: InvitationCreate,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Invite a user to a workspace (Owner only).

    The invited user will receive an email with an invitation link.
    Invitations expire after 7 days.
    """
    try:
        invitation = await membership_service.invite_member(
            workspace_id=workspace_id,
            inviter_id=current_user.id,
            invitation_data=invitation_data,
            db=db,
        )
        return invitation
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to send invitation: {str(e)}"
        )


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=List[InvitationResponse],
)
async def list_workspace_invitations(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List pending invitations for a workspace (Owner only).
    """
    try:
        invitations = await membership_service.list_workspace_invitations(
            workspace_id=workspace_id,
            user_id=current_user.id,
            db=db,
        )
        return invitations
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to list invitations: {str(e)}"
        )


@router.delete("/workspaces/{workspace_id}/invitations/{invitation_id}")
async def cancel_invitation(
    workspace_id: str,
    invitation_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cancel a pending invitation (Owner only).
    """
    try:
        success = await membership_service.cancel_invitation(
            workspace_id=workspace_id,
            invitation_id=invitation_id,
            user_id=current_user.id,
            db=db,
        )
        if success:
            return {"message": "Invitation cancelled successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to cancel invitation")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to cancel invitation: {str(e)}"
        )


# =============================================================================
# User Invitation Operations
# =============================================================================


@router.get("/invitations", response_model=List[InvitationResponse])
async def get_my_invitations(
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get all pending invitations for the current user.
    """
    try:
        invitations = await membership_service.get_my_invitations(
            user_id=current_user.id,
            user_email=current_user.email,
            db=db,
        )
        return invitations
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to get invitations: {str(e)}"
        )


@router.post(
    "/invitations/{invitation_id}/accept", response_model=WorkspaceWithMembership
)
async def accept_invitation(
    invitation_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept an invitation to join a workspace.

    Returns the workspace with the user's new membership.
    """
    try:
        workspace = await membership_service.accept_invitation(
            invitation_id=invitation_id,
            user_id=current_user.id,
            user_email=current_user.email,
            db=db,
        )
        return workspace
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to accept invitation: {str(e)}"
        )


@router.post("/invitations/{invitation_id}/decline")
async def decline_invitation(
    invitation_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Decline an invitation to join a workspace.
    """
    try:
        success = await membership_service.decline_invitation(
            invitation_id=invitation_id,
            user_id=current_user.id,
            user_email=current_user.email,
            db=db,
        )
        if success:
            return {"message": "Invitation declined"}
        else:
            raise HTTPException(status_code=400, detail="Failed to decline invitation")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to decline invitation: {str(e)}"
        )


# =============================================================================
# Member Management
# =============================================================================


@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=List[MemberResponse],
)
async def list_members(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all members of a workspace.

    Any member can view the member list.
    """
    try:
        members = await membership_service.list_members(
            workspace_id=workspace_id,
            user_id=current_user.id,
            db=db,
        )
        return members
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to list members: {str(e)}")


@router.patch(
    "/workspaces/{workspace_id}/members/{member_user_id}",
    response_model=MemberResponse,
)
async def update_member_role(
    workspace_id: str,
    member_user_id: str,
    role_update: MemberRoleUpdate,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update a member's role (Owner only).

    Cannot demote the last owner.
    """
    try:
        member = await membership_service.update_member_role(
            workspace_id=workspace_id,
            member_user_id=member_user_id,
            role_update=role_update,
            requesting_user_id=current_user.id,
            db=db,
        )
        return member
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to update member role: {str(e)}"
        )


@router.delete("/workspaces/{workspace_id}/members/{member_user_id}")
async def remove_member(
    workspace_id: str,
    member_user_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a member from the workspace (Owner only).

    Cannot remove the last owner.
    """
    try:
        success = await membership_service.remove_member(
            workspace_id=workspace_id,
            member_user_id=member_user_id,
            requesting_user_id=current_user.id,
            db=db,
        )
        if success:
            return {"message": "Member removed successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to remove member")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to remove member: {str(e)}"
        )


@router.post("/workspaces/{workspace_id}/leave")
async def leave_workspace(
    workspace_id: str,
    current_user: User = Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Leave a workspace voluntarily.

    Cannot leave if you are the sole owner.
    Cannot leave personal workspace (delete instead).
    """
    try:
        success = await membership_service.leave_workspace(
            workspace_id=workspace_id,
            user_id=current_user.id,
            db=db,
        )
        if success:
            return {"message": "Successfully left the workspace"}
        else:
            raise HTTPException(status_code=400, detail="Failed to leave workspace")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Failed to leave workspace: {str(e)}"
        )
