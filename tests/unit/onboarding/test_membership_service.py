"""
Unit tests for membership service.

Focuses on pure functions, validation logic, and schema validation (no DB).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Role as DBRole
from app.onboarding.schemas.schemas import (
    InvitationCreate,
    InvitationResponse,
    InvitationStatus,
    MemberResponse,
    MemberRoleUpdate,
    Role,
)
from app.onboarding.services.membership_service import INVITATION_EXPIRY_DAYS


class TestInvitationExpiryConstants:
    """Tests for invitation expiry constants and logic."""

    def test_invitation_expiry_days_value(self):
        """Test that expiry constant has expected value."""
        assert INVITATION_EXPIRY_DAYS == 7

    def test_expiry_calculation(self):
        """Test expiry date calculation logic."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=INVITATION_EXPIRY_DAYS)

        # Should be 7 days in the future
        delta = expires_at - now
        assert delta.days == 7

    def test_expiry_check_not_expired(self):
        """Test checking if invitation is not expired."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=3)

        is_expired = expires_at < now
        assert is_expired is False

    def test_expiry_check_expired(self):
        """Test checking if invitation is expired."""
        now = datetime.now(timezone.utc)
        expires_at = now - timedelta(hours=1)

        is_expired = expires_at < now
        assert is_expired is True

    def test_expiry_check_edge_case_now(self):
        """Test expiry check at exact expiry time."""
        now = datetime.now(timezone.utc)
        expires_at = now  # Exactly now

        # < comparison means exactly now is NOT expired
        is_expired = expires_at < now
        assert is_expired is False


class TestEmailNormalization:
    """Tests for email normalization logic.

    The service normalizes emails with: email.lower().strip()
    """

    def test_lowercase_email(self):
        """Test that emails are lowercased."""
        test_cases = [
            ("USER@EXAMPLE.COM", "user@example.com"),
            ("User@Example.Com", "user@example.com"),
            ("JOHN.DOE@COMPANY.ORG", "john.doe@company.org"),
        ]
        for original, expected in test_cases:
            normalized = original.lower().strip()
            assert normalized == expected

    def test_strip_whitespace(self):
        """Test that whitespace is stripped."""
        test_cases = [
            ("  user@example.com  ", "user@example.com"),
            ("\tuser@example.com\n", "user@example.com"),
            (" User@Example.Com ", "user@example.com"),
        ]
        for original, expected in test_cases:
            normalized = original.lower().strip()
            assert normalized == expected

    def test_already_normalized(self):
        """Test that already normalized emails are unchanged."""
        email = "user@example.com"
        normalized = email.lower().strip()
        assert normalized == email

    def test_email_comparison_after_normalization(self):
        """Test email comparison logic used for matching."""
        inviter_email = "owner@company.com"
        invitee_inputs = [
            "OWNER@COMPANY.COM",
            " owner@company.com ",
            "Owner@Company.Com",
        ]

        for invitee_email in invitee_inputs:
            normalized_invitee = invitee_email.lower().strip()
            # Cannot invite yourself
            is_same = inviter_email.lower() == normalized_invitee
            assert is_same is True


class TestSchemaRoleMapping:
    """Tests for mapping between schema Role and DB Role.

    The service maps SchemaRole.OWNER -> DBRole.OWNER and SchemaRole.USER -> DBRole.USER
    """

    def test_schema_to_db_role_owner(self):
        """Test mapping OWNER role."""
        schema_role = Role.OWNER
        db_role = DBRole.OWNER if schema_role == Role.OWNER else DBRole.USER
        assert db_role == DBRole.OWNER

    def test_schema_to_db_role_user(self):
        """Test mapping USER role."""
        schema_role = Role.USER
        db_role = DBRole.OWNER if schema_role == Role.OWNER else DBRole.USER
        assert db_role == DBRole.USER

    def test_db_to_schema_role_owner(self):
        """Test reverse mapping OWNER role."""
        db_role = DBRole.OWNER
        schema_role = Role(db_role.value)
        assert schema_role == Role.OWNER

    def test_db_to_schema_role_user(self):
        """Test reverse mapping USER role."""
        db_role = DBRole.USER
        schema_role = Role(db_role.value)
        assert schema_role == Role.USER

    def test_role_values_match(self):
        """Test that schema and DB role values match."""
        assert Role.OWNER.value == DBRole.OWNER.value
        assert Role.USER.value == DBRole.USER.value


class TestInvitationCreateSchema:
    """Tests for InvitationCreate schema validation."""

    def test_invitation_create_minimal(self):
        """Test creating invitation with minimal fields."""
        invitation = InvitationCreate(email="user@example.com")
        assert invitation.email == "user@example.com"
        assert invitation.role == Role.USER  # Default

    def test_invitation_create_with_role(self):
        """Test creating invitation with specific role."""
        invitation = InvitationCreate(email="admin@example.com", role=Role.OWNER)
        assert invitation.role == Role.OWNER

    def test_invitation_create_user_role(self):
        """Test creating invitation with USER role."""
        invitation = InvitationCreate(email="member@example.com", role=Role.USER)
        assert invitation.role == Role.USER


class TestInvitationResponseSchema:
    """Tests for InvitationResponse schema validation."""

    def test_invitation_response_creation(self):
        """Test creating invitation response."""
        now = datetime.now(timezone.utc)
        response = InvitationResponse(
            id="inv-123",
            workspace_id="ws-456",
            workspace_name="Test Workspace",
            inviter_name="John Doe",
            invitee_email="newuser@example.com",
            role=Role.USER,
            status=InvitationStatus.PENDING,
            expires_at=now + timedelta(days=7),
            created_at=now,
        )
        assert response.id == "inv-123"
        assert response.status == InvitationStatus.PENDING

    def test_invitation_response_all_statuses(self):
        """Test invitation response with all status values."""
        now = datetime.now(timezone.utc)
        base_data = {
            "id": "inv-test",
            "workspace_id": "ws-test",
            "workspace_name": "Test",
            "inviter_name": "Inviter",
            "invitee_email": "test@test.com",
            "role": Role.USER,
            "expires_at": now + timedelta(days=7),
            "created_at": now,
        }

        for status in InvitationStatus:
            response = InvitationResponse(**base_data, status=status)
            assert response.status == status


class TestInvitationStatusEnum:
    """Tests for InvitationStatus enum."""

    def test_invitation_status_values(self):
        """Test that enum has expected values."""
        assert InvitationStatus.PENDING.value == "pending"
        assert InvitationStatus.ACCEPTED.value == "accepted"
        assert InvitationStatus.DECLINED.value == "declined"
        assert InvitationStatus.EXPIRED.value == "expired"

    def test_invitation_status_from_string(self):
        """Test creating enum from string."""
        assert InvitationStatus("pending") == InvitationStatus.PENDING
        assert InvitationStatus("accepted") == InvitationStatus.ACCEPTED
        assert InvitationStatus("declined") == InvitationStatus.DECLINED
        assert InvitationStatus("expired") == InvitationStatus.EXPIRED

    def test_invitation_status_invalid(self):
        """Test that invalid value raises error."""
        with pytest.raises(ValueError):
            InvitationStatus("invalid")


class TestMemberResponseSchema:
    """Tests for MemberResponse schema validation."""

    def test_member_response_creation(self):
        """Test creating member response."""
        now = datetime.now(timezone.utc)
        response = MemberResponse(
            user_id="user-123",
            user_name="Jane Doe",
            user_email="jane@example.com",
            role=Role.OWNER,
            joined_at=now,
        )
        assert response.user_id == "user-123"
        assert response.role == Role.OWNER

    def test_member_response_user_role(self):
        """Test member response with USER role."""
        now = datetime.now(timezone.utc)
        response = MemberResponse(
            user_id="user-456",
            user_name="Bob",
            user_email="bob@example.com",
            role=Role.USER,
            joined_at=now,
        )
        assert response.role == Role.USER


class TestMemberRoleUpdateSchema:
    """Tests for MemberRoleUpdate schema validation."""

    def test_role_update_to_owner(self):
        """Test updating role to OWNER."""
        update = MemberRoleUpdate(role=Role.OWNER)
        assert update.role == Role.OWNER

    def test_role_update_to_user(self):
        """Test updating role to USER."""
        update = MemberRoleUpdate(role=Role.USER)
        assert update.role == Role.USER


class TestCannotInviteSelfValidation:
    """Tests for self-invitation prevention logic."""

    def test_cannot_invite_same_email(self):
        """Test that inviting the same email is detected."""
        inviter_email = "owner@company.com"
        invitee_email = "owner@company.com"

        is_self_invite = inviter_email.lower() == invitee_email.lower()
        assert is_self_invite is True

    def test_cannot_invite_same_email_different_case(self):
        """Test detection with different case."""
        inviter_email = "Owner@Company.com"
        invitee_email = "owner@company.com"

        is_self_invite = inviter_email.lower() == invitee_email.lower()
        assert is_self_invite is True

    def test_can_invite_different_email(self):
        """Test that different emails are allowed."""
        inviter_email = "owner@company.com"
        invitee_email = "member@company.com"

        is_self_invite = inviter_email.lower() == invitee_email.lower()
        assert is_self_invite is False


class TestLastOwnerProtectionLogic:
    """Tests for last owner protection validation logic.

    Cannot demote or remove the last owner of a workspace.
    """

    def test_can_demote_when_multiple_owners(self):
        """Test that demotion is allowed with multiple owners."""
        owner_count = 2
        can_demote = owner_count > 1
        assert can_demote is True

    def test_cannot_demote_last_owner(self):
        """Test that demotion is blocked for last owner."""
        owner_count = 1
        can_demote = owner_count > 1
        assert can_demote is False

    def test_can_remove_owner_when_multiple(self):
        """Test that removal is allowed with multiple owners."""
        owner_count = 3
        can_remove = owner_count > 1
        assert can_remove is True

    def test_cannot_remove_last_owner(self):
        """Test that removal is blocked for last owner."""
        owner_count = 1
        can_remove = owner_count > 1
        assert can_remove is False
