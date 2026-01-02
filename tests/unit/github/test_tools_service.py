"""
Unit tests for GitHub tools service.
Focuses on pure functions and validation logic (no database operations).
"""

from unittest.mock import MagicMock


from app.github.tools.service import get_owner_or_default


class TestGetOwnerOrDefault:
    """Tests for the get_owner_or_default helper function."""

    def test_returns_provided_owner_when_not_empty(self):
        """Returns the provided owner when it's a non-empty string."""
        integration = MagicMock()
        integration.github_username = "default_user"

        result = get_owner_or_default("explicit_owner", integration)

        assert result == "explicit_owner"

    def test_returns_integration_username_when_owner_is_none(self):
        """Returns integration username when owner is None."""
        integration = MagicMock()
        integration.github_username = "integration_user"

        result = get_owner_or_default(None, integration)

        assert result == "integration_user"

    def test_returns_integration_username_when_owner_is_empty_string(self):
        """Returns integration username when owner is empty string."""
        integration = MagicMock()
        integration.github_username = "integration_user"

        result = get_owner_or_default("", integration)

        assert result == "integration_user"

    def test_handles_whitespace_owner_as_truthy(self):
        """Whitespace-only owner is treated as a valid owner (truthy string)."""
        integration = MagicMock()
        integration.github_username = "integration_user"

        # Note: whitespace string is truthy, so it will be returned
        result = get_owner_or_default("   ", integration)

        assert result == "   "

    def test_returns_owner_with_special_characters(self):
        """Handles owner names with special characters."""
        integration = MagicMock()
        integration.github_username = "default_user"

        result = get_owner_or_default("org-name_123", integration)

        assert result == "org-name_123"

    def test_returns_integration_username_with_special_characters(self):
        """Handles integration username with special characters."""
        integration = MagicMock()
        integration.github_username = "user-name_456"

        result = get_owner_or_default("", integration)

        assert result == "user-name_456"

    def test_handles_organization_name(self):
        """Works with organization names."""
        integration = MagicMock()
        integration.github_username = "my-org"

        result = get_owner_or_default("another-org", integration)

        assert result == "another-org"

    def test_integration_username_can_be_organization(self):
        """Integration username could be an organization."""
        integration = MagicMock()
        integration.github_username = "enterprise-org"

        result = get_owner_or_default(None, integration)

        assert result == "enterprise-org"

    def test_preserves_case_of_owner(self):
        """Preserves the case of the provided owner."""
        integration = MagicMock()
        integration.github_username = "lowercase"

        result = get_owner_or_default("MixedCase", integration)

        assert result == "MixedCase"

    def test_preserves_case_of_integration_username(self):
        """Preserves the case of the integration username."""
        integration = MagicMock()
        integration.github_username = "MixedCaseUser"

        result = get_owner_or_default("", integration)

        assert result == "MixedCaseUser"
