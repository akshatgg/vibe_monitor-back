"""
Integration tests for membership router endpoints.

Tests cover:
- POST   /api/v1/workspaces/{workspace_id}/invitations - Invite a user
- GET    /api/v1/workspaces/{workspace_id}/invitations - List pending invitations
- DELETE /api/v1/workspaces/{workspace_id}/invitations/{id} - Cancel invitation
- GET    /api/v1/invitations - List my pending invitations
- POST   /api/v1/invitations/{id}/accept - Accept invitation
- POST   /api/v1/invitations/{id}/decline - Decline invitation
- GET    /api/v1/invitations/token/{token} - Get invitation by token
- POST   /api/v1/invitations/token/{token}/accept - Accept invitation by token
- GET    /api/v1/workspaces/{workspace_id}/members - List workspace members
- PATCH  /api/v1/workspaces/{workspace_id}/members/{user_id} - Update member role
- DELETE /api/v1/workspaces/{workspace_id}/members/{user_id} - Remove member
- POST   /api/v1/workspaces/{workspace_id}/leave - Leave workspace
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.conftest import API_PREFIX


@pytest.mark.asyncio
async def test_invite_member(auth_client, test_user, test_workspace):
    """Test inviting a new member to a workspace."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/invitations",
        json={
            "email": "newmember@example.com",
            "role": "USER",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["invitee_email"] == "newmember@example.com"
    assert data["role"] == "USER"
    assert data["status"] == "PENDING"
    assert data["workspace_id"] == test_workspace.id


@pytest.mark.asyncio
async def test_invite_member_as_owner_role(auth_client, test_user, test_workspace):
    """Test inviting a new member with owner role."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/invitations",
        json={
            "email": "newowner@example.com",
            "role": "OWNER",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "OWNER"


@pytest.mark.asyncio
async def test_list_workspace_invitations(
    auth_client, test_db, test_user, test_workspace
):
    """Test listing pending invitations for a workspace."""
    from app.models import InvitationStatus, Role, WorkspaceInvitation

    # Create an invitation
    invitation = WorkspaceInvitation(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        inviter_id=test_user.id,
        invitee_email="pending@example.com",
        role=Role.USER,
        status=InvitationStatus.PENDING,
        token=str(uuid.uuid4()),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    test_db.add(invitation)
    await test_db.commit()

    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/invitations"
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    emails = [inv["invitee_email"] for inv in data]
    assert "pending@example.com" in emails


@pytest.mark.asyncio
async def test_cancel_invitation(auth_client, test_db, test_user, test_workspace):
    """Test cancelling a pending invitation."""
    from app.models import InvitationStatus, Role, WorkspaceInvitation

    invitation = WorkspaceInvitation(
        id=str(uuid.uuid4()),
        workspace_id=test_workspace.id,
        inviter_id=test_user.id,
        invitee_email="tocancel@example.com",
        role=Role.USER,
        status=InvitationStatus.PENDING,
        token=str(uuid.uuid4()),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    test_db.add(invitation)
    await test_db.commit()

    response = await auth_client.delete(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/invitations/{invitation.id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Invitation cancelled successfully"


@pytest.mark.asyncio
async def test_get_my_invitations(auth_client, test_db, test_user, second_user):
    """Test getting pending invitations for the current user."""
    from app.models import (
        InvitationStatus,
        Membership,
        Role,
        Workspace,
        WorkspaceInvitation,
    )

    # Create a workspace owned by second_user
    other_workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Other Team Workspace",
    )
    test_db.add(other_workspace)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=other_workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)

    # Create an invitation for test_user
    invitation = WorkspaceInvitation(
        id=str(uuid.uuid4()),
        workspace_id=other_workspace.id,
        inviter_id=second_user.id,
        invitee_email=test_user.email,
        invitee_id=test_user.id,
        role=Role.USER,
        status=InvitationStatus.PENDING,
        token=str(uuid.uuid4()),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    test_db.add(invitation)
    await test_db.commit()

    response = await auth_client.get(f"{API_PREFIX}/invitations")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    invitation_ids = [inv["id"] for inv in data]
    assert invitation.id in invitation_ids


@pytest.mark.asyncio
async def test_accept_invitation(auth_client, test_db, test_user, second_user):
    """Test accepting an invitation."""
    from app.models import (
        InvitationStatus,
        Membership,
        Role,
        Workspace,
        WorkspaceInvitation,
    )

    # Create a workspace owned by second_user
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Team to Join",
    )
    test_db.add(workspace)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)

    invitation = WorkspaceInvitation(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        inviter_id=second_user.id,
        invitee_email=test_user.email,
        invitee_id=test_user.id,
        role=Role.USER,
        status=InvitationStatus.PENDING,
        token=str(uuid.uuid4()),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    test_db.add(invitation)
    await test_db.commit()

    response = await auth_client.post(
        f"{API_PREFIX}/invitations/{invitation.id}/accept"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == workspace.id
    assert "user_role" in data


@pytest.mark.asyncio
async def test_decline_invitation(auth_client, test_db, test_user, second_user):
    """Test declining an invitation."""
    from app.models import (
        InvitationStatus,
        Membership,
        Role,
        Workspace,
        WorkspaceInvitation,
    )

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Team to Decline",
    )
    test_db.add(workspace)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)

    invitation = WorkspaceInvitation(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        inviter_id=second_user.id,
        invitee_email=test_user.email,
        invitee_id=test_user.id,
        role=Role.USER,
        status=InvitationStatus.PENDING,
        token=str(uuid.uuid4()),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    test_db.add(invitation)
    await test_db.commit()

    response = await auth_client.post(
        f"{API_PREFIX}/invitations/{invitation.id}/decline"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Invitation declined"


@pytest.mark.asyncio
async def test_get_invitation_by_token(client, test_db, test_user, second_user):
    """Test getting invitation details by token (unauthenticated)."""
    from app.models import (
        InvitationStatus,
        Membership,
        Role,
        Workspace,
        WorkspaceInvitation,
    )

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Token Test Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)

    token = str(uuid.uuid4())
    invitation = WorkspaceInvitation(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        inviter_id=second_user.id,
        invitee_email="tokentest@example.com",
        role=Role.USER,
        status=InvitationStatus.PENDING,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    test_db.add(invitation)
    await test_db.commit()

    # Note: This endpoint doesn't require authentication
    response = await client.get(f"{API_PREFIX}/invitations/token/{token}")
    assert response.status_code == 200
    data = response.json()
    assert data["invitee_email"] == "tokentest@example.com"
    assert data["workspace_name"] == "Token Test Workspace"


@pytest.mark.asyncio
async def test_get_invitation_by_invalid_token(client, test_db):
    """Test getting invitation with invalid token returns 404."""
    response = await client.get(f"{API_PREFIX}/invitations/token/invalid-token")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_accept_invitation_by_token(auth_client, test_db, test_user, second_user):
    """Test accepting an invitation using a token."""
    from app.models import (
        InvitationStatus,
        Membership,
        Role,
        Workspace,
        WorkspaceInvitation,
    )

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Token Accept Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(membership)

    token = str(uuid.uuid4())
    invitation = WorkspaceInvitation(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        inviter_id=second_user.id,
        invitee_email=test_user.email,
        role=Role.USER,
        status=InvitationStatus.PENDING,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    test_db.add(invitation)
    await test_db.commit()

    response = await auth_client.post(f"{API_PREFIX}/invitations/token/{token}/accept")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == workspace.id


@pytest.mark.asyncio
async def test_list_members(auth_client, test_user, test_workspace):
    """Test listing workspace members."""
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/members"
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # test_user should be in the members list
    user_ids = [m["user_id"] for m in data]
    assert test_user.id in user_ids


@pytest.mark.asyncio
async def test_list_members_includes_role(auth_client, test_user, test_workspace):
    """Test that member list includes role information."""
    response = await auth_client.get(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/members"
    )
    assert response.status_code == 200
    data = response.json()
    member = next(m for m in data if m["user_id"] == test_user.id)
    assert member["role"] == "OWNER"
    assert "user_name" in member
    assert "user_email" in member


@pytest.mark.asyncio
async def test_update_member_role(
    auth_client, test_db, test_user, test_workspace, second_user
):
    """Test updating a member's role as owner."""
    from app.models import Membership, Role

    # Add second_user as a member
    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=test_workspace.id,
        role=Role.USER,
    )
    test_db.add(membership)
    await test_db.commit()

    # Update their role to owner
    response = await auth_client.patch(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/members/{second_user.id}",
        json={"role": "OWNER"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "OWNER"


@pytest.mark.asyncio
async def test_remove_member(
    auth_client, test_db, test_user, test_workspace, second_user
):
    """Test removing a member from a workspace."""
    from app.models import Membership, Role

    # Add second_user as a member
    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=test_workspace.id,
        role=Role.USER,
    )
    test_db.add(membership)
    await test_db.commit()

    response = await auth_client.delete(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/members/{second_user.id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Member removed successfully"


@pytest.mark.asyncio
async def test_leave_workspace(auth_client, test_db, test_user, second_user):
    """Test a user leaving a workspace voluntarily."""
    from app.models import Membership, Role, Workspace

    # Create a workspace with two owners
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Workspace to Leave",
    )
    test_db.add(workspace)
    await test_db.flush()

    # Add test_user as member (not owner)
    test_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.USER,
    )
    test_db.add(test_membership)

    # Add second_user as owner
    owner_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(owner_membership)
    await test_db.commit()

    response = await auth_client.post(f"{API_PREFIX}/workspaces/{workspace.id}/leave")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Successfully left the workspace"


@pytest.mark.asyncio
async def test_cannot_leave_as_sole_owner(auth_client, test_user, test_workspace):
    """Test that sole owner cannot leave workspace."""
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{test_workspace.id}/leave"
    )
    # Should fail because test_user is the sole owner
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_non_owner_cannot_invite(auth_client, test_db, test_user, second_user):
    """Test that non-owners cannot invite members."""
    from app.models import Membership, Role, Workspace

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Restricted Workspace",
    )
    test_db.add(workspace)
    await test_db.flush()

    # second_user is owner
    owner_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(owner_membership)

    # test_user is just a member
    member_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.USER,
    )
    test_db.add(member_membership)
    await test_db.commit()

    # Try to invite as test_user (who is just a member)
    response = await auth_client.post(
        f"{API_PREFIX}/workspaces/{workspace.id}/invitations",
        json={"email": "shouldfail@example.com", "role": "USER"},
    )
    assert response.status_code in [400, 403]


@pytest.mark.asyncio
async def test_non_owner_cannot_remove_member(
    auth_client, test_db, test_user, second_user
):
    """Test that non-owners cannot remove members."""
    from app.models import Membership, Role, User, Workspace

    # Create a third user
    third_user = User(
        id=str(uuid.uuid4()),
        name="Third User",
        email="third@example.com",
        is_verified=True,
    )
    test_db.add(third_user)

    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Restricted Workspace 2",
    )
    test_db.add(workspace)
    await test_db.flush()

    # second_user is owner
    owner_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=second_user.id,
        workspace_id=workspace.id,
        role=Role.OWNER,
    )
    test_db.add(owner_membership)

    # test_user is just a member
    member_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        workspace_id=workspace.id,
        role=Role.USER,
    )
    test_db.add(member_membership)

    # third_user is also a member
    third_membership = Membership(
        id=str(uuid.uuid4()),
        user_id=third_user.id,
        workspace_id=workspace.id,
        role=Role.USER,
    )
    test_db.add(third_membership)
    await test_db.commit()

    # Try to remove third_user as test_user (who is just a member)
    response = await auth_client.delete(
        f"{API_PREFIX}/workspaces/{workspace.id}/members/{third_user.id}"
    )
    assert response.status_code in [400, 403]
