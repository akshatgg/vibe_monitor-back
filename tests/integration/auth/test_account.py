"""
Integration tests for account management endpoints.

These tests use a real test database to verify:
- Account profile retrieval
- Account profile updates
- Account deletion preview
- Account deletion

Endpoints tested:
- GET /api/v1/account/
- PATCH /api/v1/account/
- GET /api/v1/account/deletion-preview
- DELETE /api/v1/account/
"""

import uuid

import pytest
from sqlalchemy import select

from app.auth.credential.service import pwd_context
from app.auth.google.service import AuthService
from app.models import Membership, RefreshToken, Role, User, Workspace, WorkspaceType

# Use shared fixtures from conftest.py
# API prefix for all routes
API_PREFIX = "/api/v1"


# =============================================================================
# Test Data Factories
# =============================================================================


async def create_test_user(
    test_db,
    email: str = "test@example.com",
    name: str = "Test User",
    password_hash: str = None,
    is_verified: bool = True,
    newsletter_subscribed: bool = True,
) -> User:
    """Create a user in the test database."""
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name=name,
        password_hash=password_hash,
        is_verified=is_verified,
        newsletter_subscribed=newsletter_subscribed,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


async def create_workspace(
    test_db,
    name: str = "Test Workspace",
    workspace_type: WorkspaceType = WorkspaceType.PERSONAL,
) -> Workspace:
    """Create a workspace in the test database."""
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name=name,
        type=workspace_type,
    )
    test_db.add(workspace)
    await test_db.commit()
    await test_db.refresh(workspace)
    return workspace


async def create_membership(
    test_db,
    user_id: str,
    workspace_id: str,
    role: Role = Role.OWNER,
) -> Membership:
    """Create a membership in the test database."""
    membership = Membership(
        id=str(uuid.uuid4()),
        user_id=user_id,
        workspace_id=workspace_id,
        role=role,
    )
    test_db.add(membership)
    await test_db.commit()
    await test_db.refresh(membership)
    return membership


def get_auth_headers(user: User) -> dict:
    """Generate auth headers for a user."""
    auth_service = AuthService()
    access_token = auth_service.create_access_token(
        data={"sub": user.id, "email": user.email}
    )
    return {"Authorization": f"Bearer {access_token}"}


# =============================================================================
# Tests: GET /api/v1/account/
# =============================================================================


class TestGetAccountProfile:
    """Integration tests for GET /api/v1/account/ endpoint."""

    @pytest.mark.asyncio
    async def test_get_profile_returns_user_data(self, client, test_db):
        """Authenticated user can retrieve their profile."""
        user = await create_test_user(
            test_db,
            email="profile@example.com",
            name="Profile User",
            is_verified=True,
            newsletter_subscribed=True,
        )
        headers = get_auth_headers(user)

        response = await client.get(f"{API_PREFIX}/account/", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user.id
        assert data["name"] == "Profile User"
        assert data["email"] == "profile@example.com"
        assert data["is_verified"] is True
        assert data["newsletter_subscribed"] is True
        assert data["auth_provider"] == "google"  # No password_hash means OAuth

    @pytest.mark.asyncio
    async def test_get_profile_credential_user_shows_credentials_provider(
        self, client, test_db
    ):
        """User with password shows credentials auth provider."""
        user = await create_test_user(
            test_db,
            email="creduser@example.com",
            password_hash=pwd_context.hash("SecurePass123"),
        )
        headers = get_auth_headers(user)

        response = await client.get(f"{API_PREFIX}/account/", headers=headers)

        assert response.status_code == 200
        assert response.json()["auth_provider"] == "credentials"

    @pytest.mark.asyncio
    async def test_get_profile_without_auth_returns_403(self, client, test_db):
        """Request without authentication returns 403."""
        response = await client.get(f"{API_PREFIX}/account/")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_profile_with_invalid_token_returns_401(self, client, test_db):
        """Request with invalid token returns 401."""
        headers = {"Authorization": "Bearer invalid-token"}

        response = await client.get(f"{API_PREFIX}/account/", headers=headers)

        assert response.status_code == 401


# =============================================================================
# Tests: PATCH /api/v1/account/
# =============================================================================


class TestUpdateAccountProfile:
    """Integration tests for PATCH /api/v1/account/ endpoint."""

    @pytest.mark.asyncio
    async def test_update_name_returns_updated_profile(self, client, test_db):
        """User can update their name."""
        user = await create_test_user(test_db, name="Old Name")
        headers = get_auth_headers(user)

        response = await client.patch(
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"name": "New Name"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"

    @pytest.mark.asyncio
    async def test_update_name_persists_to_database(self, client, test_db):
        """Name update is persisted to database."""
        user = await create_test_user(
            test_db, email="updatename@example.com", name="Old Name"
        )
        headers = get_auth_headers(user)

        await client.patch(
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"name": "New Name"},
        )

        await test_db.refresh(user)
        assert user.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_newsletter_subscription(self, client, test_db):
        """User can update newsletter subscription."""
        user = await create_test_user(test_db, newsletter_subscribed=True)
        headers = get_auth_headers(user)

        response = await client.patch(
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"newsletter_subscribed": False},
        )

        assert response.status_code == 200
        assert response.json()["newsletter_subscribed"] is False

        await test_db.refresh(user)
        assert user.newsletter_subscribed is False

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, client, test_db):
        """User can update multiple fields at once."""
        user = await create_test_user(
            test_db, name="Old Name", newsletter_subscribed=True
        )
        headers = get_auth_headers(user)

        response = await client.patch(
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"name": "New Name", "newsletter_subscribed": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["newsletter_subscribed"] is False

    @pytest.mark.asyncio
    async def test_update_with_empty_body_returns_current_profile(
        self, client, test_db
    ):
        """Empty update body returns current profile unchanged."""
        user = await create_test_user(test_db, name="Unchanged Name")
        headers = get_auth_headers(user)

        response = await client.patch(
            f"{API_PREFIX}/account/",
            headers=headers,
            json={},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Unchanged Name"

    @pytest.mark.asyncio
    async def test_update_without_auth_returns_403(self, client, test_db):
        """Update without authentication returns 403."""
        response = await client.patch(
            f"{API_PREFIX}/account/",
            json={"name": "New Name"},
        )

        assert response.status_code == 403


# =============================================================================
# Tests: GET /api/v1/account/deletion-preview
# =============================================================================


class TestDeletionPreview:
    """Integration tests for GET /api/v1/account/deletion-preview endpoint."""

    @pytest.mark.asyncio
    async def test_deletion_preview_user_with_no_workspaces(self, client, test_db):
        """User with no workspaces can be deleted."""
        user = await create_test_user(test_db, email="noworkspaces@example.com")
        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/account/deletion-preview", headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["can_delete"] is True
        assert data["blocking_workspaces"] == []
        assert data["workspaces_to_delete"] == []
        assert data["workspaces_to_leave"] == []

    @pytest.mark.asyncio
    async def test_deletion_preview_sole_member_workspace_will_be_deleted(
        self, client, test_db
    ):
        """Workspace where user is sole member will be deleted."""
        user = await create_test_user(test_db, email="solemember@example.com")
        workspace = await create_workspace(test_db, name="Solo Workspace")
        await create_membership(test_db, user.id, workspace.id, Role.OWNER)
        headers = get_auth_headers(user)

        response = await client.get(
            f"{API_PREFIX}/account/deletion-preview", headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["can_delete"] is True
        assert len(data["workspaces_to_delete"]) == 1
        assert data["workspaces_to_delete"][0]["id"] == workspace.id
        assert data["workspaces_to_delete"][0]["name"] == "Solo Workspace"

    @pytest.mark.asyncio
    async def test_deletion_preview_member_of_workspace_will_leave(
        self, client, test_db
    ):
        """Workspace where user is member (not owner) will be left."""
        # Create owner
        owner = await create_test_user(test_db, email="owner@example.com")
        workspace = await create_workspace(test_db, name="Team Workspace")
        await create_membership(test_db, owner.id, workspace.id, Role.OWNER)

        # Create member who wants to delete account
        member = await create_test_user(test_db, email="member@example.com")
        await create_membership(test_db, member.id, workspace.id, Role.USER)
        headers = get_auth_headers(member)

        response = await client.get(
            f"{API_PREFIX}/account/deletion-preview", headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["can_delete"] is True
        assert len(data["workspaces_to_leave"]) == 1
        assert data["workspaces_to_leave"][0]["id"] == workspace.id

    @pytest.mark.asyncio
    async def test_deletion_preview_sole_owner_with_members_blocks_deletion(
        self, client, test_db
    ):
        """Sole owner of workspace with other members cannot delete account."""
        # Create owner who wants to delete
        owner = await create_test_user(test_db, email="blockowner@example.com")
        workspace = await create_workspace(
            test_db, name="Blocking Workspace", workspace_type=WorkspaceType.TEAM
        )
        await create_membership(test_db, owner.id, workspace.id, Role.OWNER)

        # Add another member
        member = await create_test_user(test_db, email="teammember@example.com")
        await create_membership(test_db, member.id, workspace.id, Role.USER)

        headers = get_auth_headers(owner)

        response = await client.get(
            f"{API_PREFIX}/account/deletion-preview", headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["can_delete"] is False
        assert len(data["blocking_workspaces"]) == 1
        assert data["blocking_workspaces"][0]["id"] == workspace.id
        assert "action_required" in data["blocking_workspaces"][0]

    @pytest.mark.asyncio
    async def test_deletion_preview_without_auth_returns_403(self, client, test_db):
        """Deletion preview without auth returns 403."""
        response = await client.get(f"{API_PREFIX}/account/deletion-preview")

        assert response.status_code == 403


# =============================================================================
# Tests: DELETE /api/v1/account/
# =============================================================================


class TestDeleteAccount:
    """Integration tests for DELETE /api/v1/account/ endpoint."""

    @pytest.mark.asyncio
    async def test_delete_account_with_confirmation_delete(self, client, test_db):
        """Account deleted when confirmation is 'DELETE'."""
        user = await create_test_user(test_db, email="deleteme@example.com")
        user_id = user.id
        headers = get_auth_headers(user)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify user is deleted from database
        result = await test_db.execute(select(User).where(User.id == user_id))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_account_with_email_confirmation(self, client, test_db):
        """Account deleted when confirmation is user's email."""
        user = await create_test_user(test_db, email="emailconfirm@example.com")
        headers = get_auth_headers(user)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "emailconfirm@example.com"},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_delete_account_wrong_confirmation_returns_400(self, client, test_db):
        """Wrong confirmation text returns 400."""
        user = await create_test_user(test_db, email="wrongconfirm@example.com")
        headers = get_auth_headers(user)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "wrong-text"},
        )

        assert response.status_code == 400
        assert "delete" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_credential_account_requires_password(self, client, test_db):
        """Credential user must provide password to delete account."""
        user = await create_test_user(
            test_db,
            email="creddelete@example.com",
            password_hash=pwd_context.hash("SecurePass123"),
        )
        headers = get_auth_headers(user)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "DELETE"},  # No password
        )

        assert response.status_code == 400
        assert "password" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_credential_account_with_wrong_password(self, client, test_db):
        """Credential user with wrong password cannot delete account."""
        user = await create_test_user(
            test_db,
            email="wrongpass@example.com",
            password_hash=pwd_context.hash("CorrectPass123"),
        )
        headers = get_auth_headers(user)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "DELETE", "password": "WrongPass123"},
        )

        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_credential_account_with_correct_password(
        self, client, test_db
    ):
        """Credential user with correct password can delete account."""
        user = await create_test_user(
            test_db,
            email="correctpass@example.com",
            password_hash=pwd_context.hash("SecurePass123"),
        )
        headers = get_auth_headers(user)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "DELETE", "password": "SecurePass123"},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_delete_account_deletes_sole_member_workspaces(self, client, test_db):
        """Deleting account also deletes workspaces where user is sole member."""
        user = await create_test_user(test_db, email="deletews@example.com")
        workspace = await create_workspace(test_db, name="Delete Me Workspace")
        await create_membership(test_db, user.id, workspace.id, Role.OWNER)
        workspace_id = workspace.id
        headers = get_auth_headers(user)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 200
        assert workspace_id in response.json()["deleted_workspaces"]

        # Verify workspace is deleted
        result = await test_db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_account_leaves_other_workspaces(self, client, test_db):
        """Deleting account removes membership from workspaces with other members."""
        # Create owner
        owner = await create_test_user(test_db, email="stayowner@example.com")
        workspace = await create_workspace(test_db, name="Stay Workspace")
        await create_membership(test_db, owner.id, workspace.id, Role.OWNER)
        workspace_id = workspace.id

        # Create member who will delete
        member = await create_test_user(test_db, email="leavemember@example.com")
        await create_membership(test_db, member.id, workspace.id, Role.USER)
        headers = get_auth_headers(member)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 200
        assert workspace_id in response.json()["left_workspaces"]

        # Verify workspace still exists
        result = await test_db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        assert result.scalar_one_or_none() is not None

    @pytest.mark.asyncio
    async def test_delete_account_blocked_by_sole_owner_workspace(
        self, client, test_db
    ):
        """Cannot delete account when sole owner of workspace with members."""
        owner = await create_test_user(test_db, email="blockedowner@example.com")
        workspace = await create_workspace(
            test_db, name="Block Workspace", workspace_type=WorkspaceType.TEAM
        )
        await create_membership(test_db, owner.id, workspace.id, Role.OWNER)

        # Add member to block deletion
        member = await create_test_user(test_db, email="blockmember@example.com")
        await create_membership(test_db, member.id, workspace.id, Role.USER)

        headers = get_auth_headers(owner)

        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 400
        assert "cannot delete" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_delete_account_deletes_refresh_tokens(self, client, test_db):
        """Deleting account also deletes user's refresh tokens."""
        from datetime import datetime, timedelta, timezone

        user = await create_test_user(test_db, email="deletetokens@example.com")
        # Create a refresh token
        refresh_token = RefreshToken(
            token="test-refresh-token",
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        test_db.add(refresh_token)
        await test_db.commit()

        headers = get_auth_headers(user)

        await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            headers=headers,
            json={"confirmation": "DELETE"},
        )

        # Verify refresh token is deleted
        result = await test_db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_account_without_auth_returns_403(self, client, test_db):
        """Delete without authentication returns 403."""
        response = await client.request(
            "DELETE",
            f"{API_PREFIX}/account/",
            json={"confirmation": "DELETE"},
        )

        assert response.status_code == 403
