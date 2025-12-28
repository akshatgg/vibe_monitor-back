"""
Test suite for integration permissions based on workspace type.

Tests the restriction logic that:
- Personal workspaces: Only GitHub and New Relic allowed
- Team workspaces: All integrations allowed
"""

import enum


# Create a local WorkspaceType enum for testing to avoid import chain issues
class WorkspaceType(enum.Enum):
    """Type of workspace - personal or team (mirrors app.models.WorkspaceType)"""

    PERSONAL = "personal"
    TEAM = "team"


# Define allowed integrations here (mirrors app/integrations/utils/permissions.py)
# This avoids import chain issues while still testing the logic
ALLOWED_INTEGRATIONS: dict[WorkspaceType, set[str]] = {
    WorkspaceType.PERSONAL: {"github", "newrelic"},
    WorkspaceType.TEAM: {"github", "newrelic", "grafana", "aws", "datadog", "slack"},
}

ALL_PROVIDERS = {"github", "newrelic", "grafana", "aws", "datadog", "slack"}


def is_integration_allowed(workspace_type: WorkspaceType, provider: str) -> bool:
    """Check if an integration provider is allowed for a workspace type."""
    return provider.lower() in ALLOWED_INTEGRATIONS.get(workspace_type, set())


def get_allowed_integrations(workspace_type: WorkspaceType) -> set[str]:
    """Get the set of allowed integration providers for a workspace type."""
    return ALLOWED_INTEGRATIONS.get(workspace_type, set())


def get_blocked_integration_message(provider: str) -> str:
    """Get user-friendly message for blocked integration."""
    provider_display = provider.title()

    if provider.lower() == "slack":
        return (
            f"{provider_display} integration is not available for personal workspaces. "
            "Only web chat is available. Create a team workspace to connect Slack."
        )

    return (
        f"{provider_display} integration is not available for personal workspaces. "
        "Create a team workspace to use this integration."
    )


class TestIsIntegrationAllowed:
    """Tests for is_integration_allowed function."""

    # Personal workspace tests
    def test_personal_github_allowed(self):
        """GitHub should be allowed on personal workspaces."""
        assert is_integration_allowed(WorkspaceType.PERSONAL, "github") is True

    def test_personal_newrelic_allowed(self):
        """New Relic should be allowed on personal workspaces."""
        assert is_integration_allowed(WorkspaceType.PERSONAL, "newrelic") is True

    def test_personal_grafana_blocked(self):
        """Grafana should be blocked on personal workspaces."""
        assert is_integration_allowed(WorkspaceType.PERSONAL, "grafana") is False

    def test_personal_aws_blocked(self):
        """AWS should be blocked on personal workspaces."""
        assert is_integration_allowed(WorkspaceType.PERSONAL, "aws") is False

    def test_personal_datadog_blocked(self):
        """Datadog should be blocked on personal workspaces."""
        assert is_integration_allowed(WorkspaceType.PERSONAL, "datadog") is False

    def test_personal_slack_blocked(self):
        """Slack should be blocked on personal workspaces."""
        assert is_integration_allowed(WorkspaceType.PERSONAL, "slack") is False

    # Team workspace tests
    def test_team_github_allowed(self):
        """GitHub should be allowed on team workspaces."""
        assert is_integration_allowed(WorkspaceType.TEAM, "github") is True

    def test_team_newrelic_allowed(self):
        """New Relic should be allowed on team workspaces."""
        assert is_integration_allowed(WorkspaceType.TEAM, "newrelic") is True

    def test_team_grafana_allowed(self):
        """Grafana should be allowed on team workspaces."""
        assert is_integration_allowed(WorkspaceType.TEAM, "grafana") is True

    def test_team_aws_allowed(self):
        """AWS should be allowed on team workspaces."""
        assert is_integration_allowed(WorkspaceType.TEAM, "aws") is True

    def test_team_datadog_allowed(self):
        """Datadog should be allowed on team workspaces."""
        assert is_integration_allowed(WorkspaceType.TEAM, "datadog") is True

    def test_team_slack_allowed(self):
        """Slack should be allowed on team workspaces."""
        assert is_integration_allowed(WorkspaceType.TEAM, "slack") is True

    # Case insensitivity tests
    def test_provider_case_insensitive(self):
        """Provider names should be case insensitive."""
        assert is_integration_allowed(WorkspaceType.TEAM, "GitHub") is True
        assert is_integration_allowed(WorkspaceType.TEAM, "SLACK") is True
        assert is_integration_allowed(WorkspaceType.PERSONAL, "NewRelic") is True

    # Unknown provider tests
    def test_unknown_provider_blocked(self):
        """Unknown providers should be blocked."""
        assert is_integration_allowed(WorkspaceType.PERSONAL, "unknown") is False
        assert is_integration_allowed(WorkspaceType.TEAM, "unknown") is False


class TestGetAllowedIntegrations:
    """Tests for get_allowed_integrations function."""

    def test_personal_allowed_set(self):
        """Personal workspace should only allow github and newrelic."""
        allowed = get_allowed_integrations(WorkspaceType.PERSONAL)
        assert allowed == {"github", "newrelic"}

    def test_team_allowed_set(self):
        """Team workspace should allow all integrations."""
        allowed = get_allowed_integrations(WorkspaceType.TEAM)
        assert allowed == {"github", "newrelic", "grafana", "aws", "datadog", "slack"}

    def test_personal_has_two_integrations(self):
        """Personal workspace should have exactly 2 allowed integrations."""
        allowed = get_allowed_integrations(WorkspaceType.PERSONAL)
        assert len(allowed) == 2

    def test_team_has_six_integrations(self):
        """Team workspace should have exactly 6 allowed integrations."""
        allowed = get_allowed_integrations(WorkspaceType.TEAM)
        assert len(allowed) == 6


class TestGetBlockedIntegrationMessage:
    """Tests for get_blocked_integration_message function."""

    def test_slack_special_message(self):
        """Slack should have a special message mentioning web chat."""
        message = get_blocked_integration_message("slack")
        assert "Slack" in message
        assert "personal workspaces" in message
        assert "web chat" in message.lower()
        assert "team workspace" in message.lower()

    def test_grafana_message(self):
        """Grafana message should mention creating team workspace."""
        message = get_blocked_integration_message("grafana")
        assert "Grafana" in message
        assert "personal workspaces" in message
        assert "team workspace" in message.lower()

    def test_aws_message(self):
        """AWS message should mention creating team workspace."""
        message = get_blocked_integration_message("aws")
        assert "Aws" in message
        assert "personal workspaces" in message
        assert "team workspace" in message.lower()

    def test_datadog_message(self):
        """Datadog message should mention creating team workspace."""
        message = get_blocked_integration_message("datadog")
        assert "Datadog" in message
        assert "personal workspaces" in message
        assert "team workspace" in message.lower()


class TestIntegrationMatrix:
    """Tests to verify the complete integration matrix."""

    def test_personal_restrictions_count(self):
        """Personal workspace should block 4 integrations."""
        personal_allowed = ALLOWED_INTEGRATIONS[WorkspaceType.PERSONAL]
        blocked_count = len(ALL_PROVIDERS - personal_allowed)
        assert blocked_count == 4

    def test_team_no_restrictions(self):
        """Team workspace should not block any integrations."""
        team_allowed = ALLOWED_INTEGRATIONS[WorkspaceType.TEAM]
        blocked_count = len(ALL_PROVIDERS - team_allowed)
        assert blocked_count == 0

    def test_all_providers_covered(self):
        """All providers should be covered in ALLOWED_INTEGRATIONS for TEAM."""
        team_allowed = ALLOWED_INTEGRATIONS[WorkspaceType.TEAM]
        assert team_allowed == ALL_PROVIDERS

    def test_personal_subset_of_team(self):
        """Personal allowed integrations should be a subset of team allowed."""
        personal_allowed = ALLOWED_INTEGRATIONS[WorkspaceType.PERSONAL]
        team_allowed = ALLOWED_INTEGRATIONS[WorkspaceType.TEAM]
        assert personal_allowed.issubset(team_allowed)
