"""
Integration permission utilities for workspace type restrictions.

Defines which integrations are allowed for each workspace type:
- Personal spaces: Only GitHub and New Relic allowed
- Team spaces: All integrations allowed
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Workspace, WorkspaceType

# Define allowed integrations per workspace type
ALLOWED_INTEGRATIONS: dict[WorkspaceType, set[str]] = {
    WorkspaceType.PERSONAL: {"github", "newrelic"},
    WorkspaceType.TEAM: {"github", "newrelic", "grafana", "aws", "datadog", "slack"},
}

# All supported integration providers
ALL_PROVIDERS = {"github", "newrelic", "grafana", "aws", "datadog", "slack"}


def is_integration_allowed(workspace_type: WorkspaceType, provider: str) -> bool:
    """
    Check if an integration provider is allowed for a workspace type.

    Args:
        workspace_type: The type of workspace (PERSONAL or TEAM)
        provider: The integration provider name (e.g., 'grafana', 'slack')

    Returns:
        True if the integration is allowed, False otherwise
    """
    return provider.lower() in ALLOWED_INTEGRATIONS.get(workspace_type, set())


def get_allowed_integrations(workspace_type: WorkspaceType) -> set[str]:
    """
    Get the set of allowed integration providers for a workspace type.

    Args:
        workspace_type: The type of workspace (PERSONAL or TEAM)

    Returns:
        Set of allowed provider names
    """
    return ALLOWED_INTEGRATIONS.get(workspace_type, set())


def get_blocked_integration_message(provider: str) -> str:
    """
    Get user-friendly message for blocked integration.

    Args:
        provider: The integration provider name

    Returns:
        Human-readable error message
    """
    provider_display = provider.title()

    # Special message for Slack
    if provider.lower() == "slack":
        return (
            f"{provider_display} integration is not available for personal workspaces. "
            "Only web chat is available. Create a team workspace to connect Slack."
        )

    return (
        f"{provider_display} integration is not available for personal workspaces. "
        "Create a team workspace to use this integration."
    )


async def check_integration_permission(
    workspace_id: str,
    provider: str,
    db: AsyncSession,
) -> Workspace:
    """
    Check if an integration is allowed for a workspace and return the workspace.

    This is a convenience function that:
    1. Fetches the workspace from the database
    2. Checks if the integration provider is allowed for the workspace type
    3. Raises HTTPException if not allowed
    4. Returns the workspace if allowed

    Args:
        workspace_id: The workspace ID
        provider: The integration provider name
        db: Database session

    Returns:
        The Workspace object if the integration is allowed

    Raises:
        HTTPException: 404 if workspace not found, 400 if integration not allowed
    """
    # Fetch the workspace
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check if integration is allowed for this workspace type
    if not is_integration_allowed(workspace.type, provider):
        raise HTTPException(
            status_code=400,
            detail=get_blocked_integration_message(provider),
        )

    return workspace
