"""
Test suite for AccountService - account deletion with workspace ownership constraints.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock

from app.auth.services.account_service import AccountService
from app.auth.schemas.account_schemas import (
    WorkspaceType,
    Role as SchemaRole,
)
from app.models import Workspace, Membership, Role, WorkspaceType as DBWorkspaceType


class TestDeletionPreview:
    """Tests for get_deletion_preview method."""

    @pytest.mark.asyncio
    async def test_preview_personal_workspace_only(
        self, mock_db, mock_user, mock_personal_workspace
    ):
        """User with only personal workspace should be able to delete."""
        # Setup
        service = AccountService()

        # Create owner membership for personal workspace
        membership = MagicMock(spec=Membership)
        membership.id = str(uuid.uuid4())
        membership.user_id = mock_user.id
        membership.workspace_id = mock_personal_workspace.id
        membership.role = Role.OWNER
        membership.workspace = mock_personal_workspace

        # Mock membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = [membership]

        # Mock member count (1 member - the user)
        member_count_result = MagicMock()
        member_count_result.scalar.return_value = 1

        # Mock owner count (1 owner - the user)
        owner_count_result = MagicMock()
        owner_count_result.scalar.return_value = 1

        mock_db.execute = AsyncMock(
            side_effect=[memberships_result, member_count_result, owner_count_result]
        )

        # Execute
        result = await service.get_deletion_preview(mock_user.id, mock_db)

        # Assert
        assert result.can_delete is True
        assert len(result.blocking_workspaces) == 0
        assert len(result.workspaces_to_delete) == 1
        assert len(result.workspaces_to_leave) == 0
        assert result.workspaces_to_delete[0].id == mock_personal_workspace.id
        assert result.workspaces_to_delete[0].type == WorkspaceType.PERSONAL

    @pytest.mark.asyncio
    async def test_preview_sole_owner_with_other_members_blocks_deletion(
        self, mock_db, mock_user, mock_team_workspace
    ):
        """Sole owner of team workspace with other members should be blocked."""
        # Setup
        service = AccountService()

        # Create owner membership for team workspace
        membership = MagicMock(spec=Membership)
        membership.id = str(uuid.uuid4())
        membership.user_id = mock_user.id
        membership.workspace_id = mock_team_workspace.id
        membership.role = Role.OWNER
        membership.workspace = mock_team_workspace

        # Mock membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = [membership]

        # Mock member count (3 members including the user)
        member_count_result = MagicMock()
        member_count_result.scalar.return_value = 3

        # Mock owner count (1 owner - the user)
        owner_count_result = MagicMock()
        owner_count_result.scalar.return_value = 1

        mock_db.execute = AsyncMock(
            side_effect=[memberships_result, member_count_result, owner_count_result]
        )

        # Execute
        result = await service.get_deletion_preview(mock_user.id, mock_db)

        # Assert
        assert result.can_delete is False
        assert len(result.blocking_workspaces) == 1
        assert len(result.workspaces_to_delete) == 0
        assert len(result.workspaces_to_leave) == 0
        assert result.blocking_workspaces[0].id == mock_team_workspace.id
        assert result.blocking_workspaces[0].member_count == 3
        assert "Transfer ownership" in result.blocking_workspaces[0].action_required

    @pytest.mark.asyncio
    async def test_preview_co_owner_can_delete(
        self, mock_db, mock_user, mock_team_workspace
    ):
        """Co-owner (not sole owner) should be able to leave workspace."""
        # Setup
        service = AccountService()

        # Create owner membership for team workspace
        membership = MagicMock(spec=Membership)
        membership.id = str(uuid.uuid4())
        membership.user_id = mock_user.id
        membership.workspace_id = mock_team_workspace.id
        membership.role = Role.OWNER
        membership.workspace = mock_team_workspace

        # Mock membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = [membership]

        # Mock member count (3 members)
        member_count_result = MagicMock()
        member_count_result.scalar.return_value = 3

        # Mock owner count (2 owners - user is co-owner)
        owner_count_result = MagicMock()
        owner_count_result.scalar.return_value = 2

        mock_db.execute = AsyncMock(
            side_effect=[memberships_result, member_count_result, owner_count_result]
        )

        # Execute
        result = await service.get_deletion_preview(mock_user.id, mock_db)

        # Assert
        assert result.can_delete is True
        assert len(result.blocking_workspaces) == 0
        assert len(result.workspaces_to_delete) == 0
        assert len(result.workspaces_to_leave) == 1
        assert result.workspaces_to_leave[0].id == mock_team_workspace.id
        assert result.workspaces_to_leave[0].user_role == SchemaRole.OWNER

    @pytest.mark.asyncio
    async def test_preview_member_can_delete(
        self, mock_db, mock_user, mock_team_workspace
    ):
        """Member (not owner) should be able to leave workspace."""
        # Setup
        service = AccountService()

        # Create member membership for team workspace
        membership = MagicMock(spec=Membership)
        membership.id = str(uuid.uuid4())
        membership.user_id = mock_user.id
        membership.workspace_id = mock_team_workspace.id
        membership.role = Role.USER
        membership.workspace = mock_team_workspace

        # Mock membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = [membership]

        # Mock member count (5 members)
        member_count_result = MagicMock()
        member_count_result.scalar.return_value = 5

        # Mock owner count (1 owner - not the user)
        owner_count_result = MagicMock()
        owner_count_result.scalar.return_value = 1

        mock_db.execute = AsyncMock(
            side_effect=[memberships_result, member_count_result, owner_count_result]
        )

        # Execute
        result = await service.get_deletion_preview(mock_user.id, mock_db)

        # Assert
        assert result.can_delete is True
        assert len(result.blocking_workspaces) == 0
        assert len(result.workspaces_to_delete) == 0
        assert len(result.workspaces_to_leave) == 1
        assert result.workspaces_to_leave[0].id == mock_team_workspace.id
        assert result.workspaces_to_leave[0].user_role == SchemaRole.USER

    @pytest.mark.asyncio
    async def test_preview_mixed_workspaces(self, mock_db, mock_user):
        """Test with mix of personal, empty team, and shared workspaces."""
        # Setup
        service = AccountService()

        # Personal workspace (sole owner, sole member) -> should delete
        personal_ws = MagicMock(spec=Workspace)
        personal_ws.id = str(uuid.uuid4())
        personal_ws.name = "Personal"
        personal_ws.type = DBWorkspaceType.PERSONAL

        personal_membership = MagicMock(spec=Membership)
        personal_membership.id = str(uuid.uuid4())
        personal_membership.workspace = personal_ws
        personal_membership.role = Role.OWNER

        # Team workspace (sole owner, no other members) -> should delete
        empty_team_ws = MagicMock(spec=Workspace)
        empty_team_ws.id = str(uuid.uuid4())
        empty_team_ws.name = "Empty Team"
        empty_team_ws.type = DBWorkspaceType.TEAM

        empty_team_membership = MagicMock(spec=Membership)
        empty_team_membership.id = str(uuid.uuid4())
        empty_team_membership.workspace = empty_team_ws
        empty_team_membership.role = Role.OWNER

        # Team workspace (member only) -> should leave
        shared_team_ws = MagicMock(spec=Workspace)
        shared_team_ws.id = str(uuid.uuid4())
        shared_team_ws.name = "Shared Team"
        shared_team_ws.type = DBWorkspaceType.TEAM

        shared_membership = MagicMock(spec=Membership)
        shared_membership.id = str(uuid.uuid4())
        shared_membership.workspace = shared_team_ws
        shared_membership.role = Role.USER

        # Mock membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = [
            personal_membership,
            empty_team_membership,
            shared_membership,
        ]

        # Stats for each workspace: (total_members, total_owners)
        stats = [
            (1, 1),  # Personal: 1 member, 1 owner
            (1, 1),  # Empty team: 1 member, 1 owner
            (5, 2),  # Shared team: 5 members, 2 owners
        ]

        async def mock_execute(query):
            # First call returns memberships
            if mock_db.execute.call_count == 1:
                return memberships_result
            # Subsequent calls return stats
            stat_idx = (mock_db.execute.call_count - 2) // 2
            is_owner_count = (mock_db.execute.call_count - 2) % 2 == 1

            result = MagicMock()
            if is_owner_count:
                result.scalar.return_value = stats[stat_idx][1]
            else:
                result.scalar.return_value = stats[stat_idx][0]
            return result

        mock_db.execute = AsyncMock(side_effect=mock_execute)

        # Execute
        result = await service.get_deletion_preview(mock_user.id, mock_db)

        # Assert
        assert result.can_delete is True
        assert len(result.blocking_workspaces) == 0
        assert len(result.workspaces_to_delete) == 2
        assert len(result.workspaces_to_leave) == 1

    @pytest.mark.asyncio
    async def test_preview_no_workspaces(self, mock_db, mock_user):
        """User with no workspaces should be able to delete."""
        # Setup
        service = AccountService()

        # Mock empty membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(return_value=memberships_result)

        # Execute
        result = await service.get_deletion_preview(mock_user.id, mock_db)

        # Assert
        assert result.can_delete is True
        assert len(result.blocking_workspaces) == 0
        assert len(result.workspaces_to_delete) == 0
        assert len(result.workspaces_to_leave) == 0
        assert result.message == "Your account can be deleted."


class TestDeleteAccount:
    """Tests for delete_account method."""

    @pytest.mark.asyncio
    async def test_delete_requires_correct_confirmation(
        self, mock_db, mock_user, mock_credential_auth_service
    ):
        """Deletion should fail with incorrect confirmation."""
        # Setup
        service = AccountService(credential_auth_service=mock_credential_auth_service)

        # Mock user query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=user_result)

        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            await service.delete_account(
                user_id=mock_user.id,
                confirmation="WRONG",
                password=None,
                db=mock_db,
            )

        assert "Please type 'DELETE'" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_delete_accepts_delete_confirmation(
        self, mock_db, mock_user, mock_personal_workspace
    ):
        """Deletion should work with 'DELETE' confirmation for OAuth user."""
        # Setup
        service = AccountService()

        # Create owner membership for personal workspace
        membership = MagicMock(spec=Membership)
        membership.id = str(uuid.uuid4())
        membership.workspace = mock_personal_workspace
        membership.role = Role.OWNER

        # Mock user query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user

        # Mock membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = [membership]

        # Mock stats (1 member, 1 owner)
        stats_result = MagicMock()
        stats_result.scalar.return_value = 1

        # Mock workspace query for deletion
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = mock_personal_workspace

        mock_db.execute = AsyncMock(
            side_effect=[
                user_result,  # Get user
                memberships_result,  # Get memberships (preview)
                stats_result,  # Member count
                stats_result,  # Owner count
                MagicMock(),  # Delete membership
                workspace_result,  # Get workspace for deletion
                MagicMock(),  # Delete refresh tokens
                MagicMock(),  # Delete email verifications
                MagicMock(),  # Delete emails
                MagicMock(),  # Delete chat sessions
                user_result,  # Get user again to clear last_visited_workspace_id
            ]
        )

        # Execute
        result = await service.delete_account(
            user_id=mock_user.id,
            confirmation="DELETE",
            password=None,
            db=mock_db,
        )

        # Assert
        assert result.success is True
        assert len(result.deleted_workspaces) == 1
        assert result.deleted_workspaces[0] == mock_personal_workspace.id

    @pytest.mark.asyncio
    async def test_delete_accepts_email_confirmation(
        self, mock_db, mock_user, mock_personal_workspace
    ):
        """Deletion should work with user's email as confirmation."""
        # Setup
        service = AccountService()

        # Create owner membership for personal workspace
        membership = MagicMock(spec=Membership)
        membership.id = str(uuid.uuid4())
        membership.workspace = mock_personal_workspace
        membership.role = Role.OWNER

        # Mock user query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user

        # Mock membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = [membership]

        # Mock stats
        stats_result = MagicMock()
        stats_result.scalar.return_value = 1

        # Mock workspace query
        workspace_result = MagicMock()
        workspace_result.scalar_one_or_none.return_value = mock_personal_workspace

        mock_db.execute = AsyncMock(
            side_effect=[
                user_result,
                memberships_result,
                stats_result,
                stats_result,
                MagicMock(),
                workspace_result,
                MagicMock(),
                MagicMock(),
                MagicMock(),
                MagicMock(),
                user_result,
            ]
        )

        # Execute (case-insensitive email check)
        result = await service.delete_account(
            user_id=mock_user.id,
            confirmation=mock_user.email.upper(),
            password=None,
            db=mock_db,
        )

        # Assert
        assert result.success is True

    @pytest.mark.asyncio
    async def test_delete_credential_user_requires_password(
        self, mock_db, mock_credential_user, mock_credential_auth_service
    ):
        """Credential-based user must provide password."""
        # Setup
        service = AccountService(credential_auth_service=mock_credential_auth_service)

        # Mock user query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_credential_user
        mock_db.execute = AsyncMock(return_value=user_result)

        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            await service.delete_account(
                user_id=mock_credential_user.id,
                confirmation="DELETE",
                password=None,  # Missing password
                db=mock_db,
            )

        assert "Password is required" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_delete_credential_user_wrong_password(
        self, mock_db, mock_credential_user, mock_credential_auth_service
    ):
        """Credential-based user with wrong password should fail."""
        # Setup
        mock_credential_auth_service.verify_password.return_value = False
        service = AccountService(credential_auth_service=mock_credential_auth_service)

        # Mock user query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_credential_user
        mock_db.execute = AsyncMock(return_value=user_result)

        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            await service.delete_account(
                user_id=mock_credential_user.id,
                confirmation="DELETE",
                password="wrong_password",
                db=mock_db,
            )

        assert "Invalid password" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_delete_oauth_user_rejects_password(
        self, mock_db, mock_user, mock_credential_auth_service
    ):
        """OAuth user should not provide password."""
        # Setup
        service = AccountService(credential_auth_service=mock_credential_auth_service)

        # Mock user query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute = AsyncMock(return_value=user_result)

        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            await service.delete_account(
                user_id=mock_user.id,
                confirmation="DELETE",
                password="some_password",  # Should not provide
                db=mock_db,
            )

        assert "Password not required for OAuth" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_delete_blocked_by_workspace_ownership(
        self, mock_db, mock_user, mock_team_workspace
    ):
        """Deletion should fail if user is sole owner with other members."""
        # Setup
        service = AccountService()

        # Create owner membership
        membership = MagicMock(spec=Membership)
        membership.id = str(uuid.uuid4())
        membership.workspace = mock_team_workspace
        membership.role = Role.OWNER

        # Mock user query
        user_result = MagicMock()
        user_result.scalar_one_or_none.return_value = mock_user

        # Mock membership query
        memberships_result = MagicMock()
        memberships_result.scalars.return_value.all.return_value = [membership]

        # Mock member count (3 members)
        member_count_result = MagicMock()
        member_count_result.scalar.return_value = 3

        # Mock owner count (1 owner - sole owner)
        owner_count_result = MagicMock()
        owner_count_result.scalar.return_value = 1

        mock_db.execute = AsyncMock(
            side_effect=[
                user_result,
                memberships_result,
                member_count_result,
                owner_count_result,
            ]
        )

        # Execute & Assert
        with pytest.raises(Exception) as exc_info:
            await service.delete_account(
                user_id=mock_user.id,
                confirmation="DELETE",
                password=None,
                db=mock_db,
            )

        assert "Cannot delete account" in str(exc_info.value.detail)


class TestHelperMethods:
    """Tests for helper methods."""

    @pytest.mark.asyncio
    async def test_get_workspace_member_stats(self, mock_db):
        """Test getting workspace member statistics."""
        # Setup
        service = AccountService()
        workspace_id = str(uuid.uuid4())

        # Mock member count query
        member_count_result = MagicMock()
        member_count_result.scalar.return_value = 5

        # Mock owner count query
        owner_count_result = MagicMock()
        owner_count_result.scalar.return_value = 2

        mock_db.execute = AsyncMock(
            side_effect=[member_count_result, owner_count_result]
        )

        # Execute
        stats = await service._get_workspace_member_stats(workspace_id, mock_db)

        # Assert
        assert stats["total_members"] == 5
        assert stats["total_owners"] == 2
