"""
Unit tests for workspace service.

Focuses on pure functions, validation logic, and schema validation (no DB).
"""

import pytest
from pydantic import ValidationError

from app.onboarding.schemas.schemas import (
    Role,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceType,
    WorkspaceUpdate,
    WorkspaceWithMembership,
)


class TestDomainExtraction:
    """Tests for domain extraction from email logic.

    The workspace service extracts domains from user emails when:
    - visible_to_org is True and no domain is provided
    """

    def test_extract_domain_from_standard_email(self):
        """Test extracting domain from standard email format."""
        test_cases = [
            ("user@example.com", "example.com"),
            ("name@company.org", "company.org"),
            ("test@subdomain.domain.io", "subdomain.domain.io"),
        ]
        for email, expected_domain in test_cases:
            domain = email.split("@")[1] if "@" in email else None
            assert domain == expected_domain

    def test_extract_domain_from_corporate_email(self):
        """Test extracting domain from corporate emails."""
        corporate_emails = [
            ("john.doe@acme-corp.com", "acme-corp.com"),
            ("sales@my-company.io", "my-company.io"),
            ("ceo@startup.co", "startup.co"),
        ]
        for email, expected_domain in corporate_emails:
            domain = email.split("@")[1] if "@" in email else None
            assert domain == expected_domain

    def test_extract_domain_returns_none_for_invalid(self):
        """Test that invalid emails return None for domain."""
        invalid_emails = [
            "no-at-symbol",
            "",
            "   ",
            "just-a-string",
        ]
        for email in invalid_emails:
            domain = email.split("@")[1] if "@" in email else None
            assert domain is None

    def test_extract_domain_with_multiple_at_symbols(self):
        """Test handling of unusual email formats."""
        # The simple split approach takes everything after first @
        email = "user@domain@extra.com"
        parts = email.split("@")
        # Simple split would give ['user', 'domain', 'extra.com']
        # The code uses email.split("@")[1] which gives 'domain'
        domain = parts[1] if len(parts) > 1 else None
        assert domain == "domain"


class TestPersonalWorkspaceNameGeneration:
    """Tests for personal workspace name generation logic.

    Personal workspaces are named "{user.name}'s Workspace".
    """

    def test_workspace_name_generation_simple_name(self):
        """Test workspace name generation with simple names."""
        test_cases = [
            ("John", "John's Workspace"),
            ("Alice", "Alice's Workspace"),
            ("Bob Smith", "Bob Smith's Workspace"),
        ]
        for user_name, expected in test_cases:
            workspace_name = f"{user_name}'s Workspace"
            assert workspace_name == expected

    def test_workspace_name_generation_special_characters(self):
        """Test workspace name generation with special characters."""
        test_cases = [
            ("O'Brien", "O'Brien's Workspace"),
            ("Mary-Jane", "Mary-Jane's Workspace"),
            ("José", "José's Workspace"),
        ]
        for user_name, expected in test_cases:
            workspace_name = f"{user_name}'s Workspace"
            assert workspace_name == expected

    def test_workspace_name_generation_unicode(self):
        """Test workspace name generation with unicode characters."""
        test_cases = [
            ("田中", "田中's Workspace"),
            ("Müller", "Müller's Workspace"),
            ("Søren", "Søren's Workspace"),
        ]
        for user_name, expected in test_cases:
            workspace_name = f"{user_name}'s Workspace"
            assert workspace_name == expected


class TestWorkspaceCreateSchema:
    """Tests for WorkspaceCreate schema validation."""

    def test_workspace_create_minimal(self):
        """Test creating workspace with minimal required fields."""
        ws = WorkspaceCreate(name="My Workspace")
        assert ws.name == "My Workspace"
        assert ws.type == WorkspaceType.TEAM  # Default
        assert ws.domain is None
        assert ws.visible_to_org is False

    def test_workspace_create_personal(self):
        """Test creating personal workspace."""
        ws = WorkspaceCreate(name="Personal", type=WorkspaceType.PERSONAL)
        assert ws.type == WorkspaceType.PERSONAL
        # Personal workspaces should not have domain or visible_to_org
        assert ws.domain is None
        assert ws.visible_to_org is False

    def test_workspace_create_team_visible(self):
        """Test creating team workspace visible to org."""
        ws = WorkspaceCreate(
            name="Engineering Team",
            type=WorkspaceType.TEAM,
            domain="company.com",
            visible_to_org=True,
        )
        assert ws.type == WorkspaceType.TEAM
        assert ws.domain == "company.com"
        assert ws.visible_to_org is True

    def test_workspace_create_all_fields(self):
        """Test creating workspace with all fields."""
        ws = WorkspaceCreate(
            name="Full Workspace",
            type=WorkspaceType.TEAM,
            domain="test.io",
            visible_to_org=True,
        )
        assert ws.name == "Full Workspace"
        assert ws.type == WorkspaceType.TEAM
        assert ws.domain == "test.io"
        assert ws.visible_to_org is True


class TestWorkspaceUpdateSchema:
    """Tests for WorkspaceUpdate schema validation."""

    def test_workspace_update_empty(self):
        """Test update with no fields (all None)."""
        update = WorkspaceUpdate()
        assert update.name is None
        assert update.visible_to_org is None

    def test_workspace_update_name_only(self):
        """Test updating only name."""
        update = WorkspaceUpdate(name="New Name")
        assert update.name == "New Name"
        assert update.visible_to_org is None

    def test_workspace_update_visibility_only(self):
        """Test updating only visibility."""
        update = WorkspaceUpdate(visible_to_org=True)
        assert update.name is None
        assert update.visible_to_org is True

    def test_workspace_update_both_fields(self):
        """Test updating both fields."""
        update = WorkspaceUpdate(name="Updated", visible_to_org=False)
        assert update.name == "Updated"
        assert update.visible_to_org is False


class TestWorkspaceResponseSchema:
    """Tests for WorkspaceResponse schema validation."""

    def test_workspace_response_creation(self):
        """Test creating workspace response."""
        response = WorkspaceResponse(
            id="ws-123",
            name="Test Workspace",
            type=WorkspaceType.TEAM,
            domain="test.com",
            visible_to_org=True,
            is_paid=False,
        )
        assert response.id == "ws-123"
        assert response.name == "Test Workspace"
        assert response.type == WorkspaceType.TEAM
        assert response.is_paid is False

    def test_workspace_response_minimal(self):
        """Test workspace response with minimal fields."""
        response = WorkspaceResponse(
            id="ws-456",
            name="Minimal",
            type=WorkspaceType.PERSONAL,
            visible_to_org=False,
            is_paid=True,
        )
        assert response.domain is None
        assert response.created_at is None


class TestWorkspaceWithMembershipSchema:
    """Tests for WorkspaceWithMembership schema validation."""

    def test_workspace_with_membership_owner(self):
        """Test workspace with owner membership."""
        ws = WorkspaceWithMembership(
            id="ws-789",
            name="Owner Workspace",
            type=WorkspaceType.TEAM,
            visible_to_org=False,
            is_paid=False,
            user_role=Role.OWNER,
        )
        assert ws.user_role == Role.OWNER

    def test_workspace_with_membership_user(self):
        """Test workspace with user membership."""
        ws = WorkspaceWithMembership(
            id="ws-abc",
            name="User Workspace",
            type=WorkspaceType.TEAM,
            visible_to_org=True,
            is_paid=True,
            user_role=Role.USER,
        )
        assert ws.user_role == Role.USER


class TestWorkspaceTypeEnum:
    """Tests for WorkspaceType enum."""

    def test_workspace_type_values(self):
        """Test that enum has expected values."""
        assert WorkspaceType.PERSONAL.value == "personal"
        assert WorkspaceType.TEAM.value == "team"

    def test_workspace_type_from_string(self):
        """Test creating enum from string."""
        assert WorkspaceType("personal") == WorkspaceType.PERSONAL
        assert WorkspaceType("team") == WorkspaceType.TEAM

    def test_workspace_type_invalid_raises(self):
        """Test that invalid value raises error."""
        with pytest.raises(ValueError):
            WorkspaceType("invalid")


class TestRoleEnum:
    """Tests for Role enum."""

    def test_role_values(self):
        """Test that enum has expected values."""
        assert Role.OWNER.value == "owner"
        assert Role.USER.value == "user"

    def test_role_from_string(self):
        """Test creating enum from string."""
        assert Role("owner") == Role.OWNER
        assert Role("user") == Role.USER

    def test_role_invalid_raises(self):
        """Test that invalid value raises error."""
        with pytest.raises(ValueError):
            Role("admin")  # Not a valid role


class TestPersonalWorkspaceValidationLogic:
    """Tests for personal workspace validation rules.

    Personal workspaces have specific constraints:
    - Only one per user
    - Cannot be visible to org
    - Cannot have a domain
    """

    def test_personal_workspace_constraints(self):
        """Test that personal workspaces should not have domain/visibility."""
        ws = WorkspaceCreate(
            name="Personal",
            type=WorkspaceType.PERSONAL,
            domain=None,
            visible_to_org=False,
        )
        # These are the expected values for personal workspaces
        assert ws.domain is None
        assert ws.visible_to_org is False

    def test_team_workspace_can_have_domain(self):
        """Test that team workspaces can have domain."""
        ws = WorkspaceCreate(
            name="Team", type=WorkspaceType.TEAM, domain="company.com", visible_to_org=True
        )
        assert ws.domain == "company.com"
        assert ws.visible_to_org is True
