"""
Integration permission utilities.

All integrations are available for all workspaces.
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Workspace

# All supported integration providers
ALL_PROVIDERS = {"github", "newrelic", "grafana", "aws", "datadog", "slack"}


def is_integration_allowed(provider: str) -> bool:
    """
    Check if an integration provider is supported.

    Args:
        provider: The integration provider name (e.g., 'grafana', 'slack')

    Returns:
        True if the integration is supported, False otherwise
    """
    return provider.lower() in ALL_PROVIDERS


def get_allowed_integrations() -> set[str]:
    """
    Get the set of all supported integration providers.

    Returns:
        Set of all provider names
    """
    return ALL_PROVIDERS


async def check_integration_permission(
    workspace_id: str,
    provider: str,
    db: AsyncSession,
) -> Workspace:
    """
    Verify workspace exists and return it.

    Args:
        workspace_id: The workspace ID
        provider: The integration provider name (currently unused, kept for API compatibility)
        db: Database session

    Returns:
        The Workspace object

    Raises:
        HTTPException: 404 if workspace not found
    """
    # Fetch the workspace
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return workspace
