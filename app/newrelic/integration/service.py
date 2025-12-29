"""
New Relic Integration Service
Handles CRUD operations for New Relic integrations
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.health_checks import check_newrelic_health
from app.models import Integration, NewRelicIntegration
from app.utils.token_processor import token_processor

from .schemas import (
    NewRelicIntegrationCreate,
    NewRelicIntegrationResponse,
    NewRelicIntegrationStatusResponse,
)

logger = logging.getLogger(__name__)


# =============================================================================
# STANDALONE UTILITY FUNCTIONS (Can be used by router and RCA bot)
# =============================================================================


async def verify_newrelic_credentials(
    account_id: str, api_key: str
) -> Tuple[bool, str]:
    """
    Verify New Relic account ID and API key by making a test API call.
    This is a standalone function that can be used by router and RCA bot.

    Args:
        account_id: New Relic Account ID
        api_key: New Relic User API Key (must start with NRAK)

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if credentials are valid, False otherwise
        - error_message: Empty string if valid, error description if invalid
    """
    url = "https://api.newrelic.com/graphql"
    headers = {"Content-Type": "application/json", "API-Key": api_key}

    # Query to verify both account access and credentials
    query = f"""
    {{
      actor {{
        account(id: {account_id}) {{
          id
          name
        }}
      }}
    }}
    """

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json={"query": query}, headers=headers, timeout=10.0
            )

            if response.status_code == 401:
                return False, "Invalid API key"

            if response.status_code == 403:
                return False, "API key does not have access to this account"

            if response.status_code != 200:
                return False, f"API request failed with status {response.status_code}"

            data = response.json()

            # Check for GraphQL errors
            if "errors" in data:
                error_msg = data["errors"][0].get("message", "Unknown error")
                return False, f"Verification failed: {error_msg}"

            # Successful verification
            if data.get("data", {}).get("actor", {}).get("account"):
                account_name = data["data"]["actor"]["account"].get("name", "")
                logger.info(
                    f"Successfully verified New Relic account: {account_name} (ID: {account_id})"
                )
                return True, ""

            return False, "Could not access account with provided credentials"

    except httpx.TimeoutException:
        logger.error("New Relic API request timeout")
        return False, "Request timeout - New Relic API did not respond"
    except Exception as e:
        logger.error(f"New Relic verification error: {str(e)}")
        return False, f"Verification error: {str(e)}"


async def get_newrelic_integration(
    db: AsyncSession, workspace_id: str
) -> Optional[NewRelicIntegrationResponse]:
    """
    Get New Relic integration for a workspace.
    Standalone function that can be used by router and RCA bot.

    Args:
        db: Database session
        workspace_id: Workspace ID

    Returns:
        NewRelicIntegrationResponse or None if not found
    """
    result = await db.execute(
        select(NewRelicIntegration).where(
            NewRelicIntegration.workspace_id == workspace_id
        )
    )
    integration = result.scalar_one_or_none()

    if not integration:
        return None

    return NewRelicIntegrationResponse(
        id=integration.id,
        workspace_id=integration.workspace_id,
        account_id=integration.account_id,
        last_verified_at=integration.last_verified_at,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


async def create_newrelic_integration(
    db: AsyncSession,
    user_id: str,
    workspace_id: str,
    integration_data: NewRelicIntegrationCreate,
) -> NewRelicIntegrationResponse:
    """
    Create a new New Relic integration for a workspace.
    Standalone function that can be used by router and RCA bot.

    Args:
        db: Database session
        user_id: User ID
        workspace_id: Workspace ID
        integration_data: New Relic integration data (account_id, api_key)

    Returns:
        NewRelicIntegrationResponse

    Raises:
        ValueError: If integration already exists or API key is invalid
    """
    # Check if integration already exists for this workspace
    result = await db.execute(
        select(NewRelicIntegration).where(
            NewRelicIntegration.workspace_id == workspace_id
        )
    )
    existing_integration = result.scalar_one_or_none()

    if existing_integration:
        raise ValueError("A New Relic integration already exists for this workspace")

    # Verify New Relic credentials before storing
    is_valid, error_message = await verify_newrelic_credentials(
        integration_data.account_id, integration_data.api_key
    )

    if not is_valid:
        raise ValueError(f"Invalid New Relic credentials: {error_message}")

    # Encrypt API key before storage
    encrypted_api_key = token_processor.encrypt(integration_data.api_key)

    # Create Integration control plane record first
    control_plane_id = str(uuid.uuid4())
    control_plane_integration = Integration(
        id=control_plane_id,
        workspace_id=workspace_id,
        provider="newrelic",
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(control_plane_integration)
    await db.flush()  # Get ID without committing

    # Create provider-specific integration linked to control plane
    integration = NewRelicIntegration(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        integration_id=control_plane_id,  # Link to control plane
        account_id=integration_data.account_id,
        api_key=encrypted_api_key,
        last_verified_at=datetime.now(timezone.utc),
    )

    db.add(integration)
    await db.commit()
    await db.refresh(integration)

    # Run initial health check to populate health_status
    try:
        health_status, error_message = await check_newrelic_health(integration)
        control_plane_integration.health_status = health_status
        control_plane_integration.last_verified_at = datetime.now(timezone.utc)
        control_plane_integration.last_error = error_message
        if health_status == "healthy":
            control_plane_integration.status = "active"
        elif health_status == "failed":
            control_plane_integration.status = "error"
        await db.commit()
        logger.info(
            f"NewRelic integration created with health_status={health_status}: "
            f"workspace_id={workspace_id}"
        )
    except Exception as e:
        logger.warning(
            f"Failed to run initial health check for NewRelic integration: {e}. "
            f"Health status remains unset."
        )

    return NewRelicIntegrationResponse(
        id=integration.id,
        workspace_id=integration.workspace_id,
        account_id=integration.account_id,
        last_verified_at=integration.last_verified_at,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


async def get_newrelic_integration_status(
    db: AsyncSession, workspace_id: str
) -> NewRelicIntegrationStatusResponse:
    """
    Get New Relic integration status for a workspace.
    Standalone function that can be used by router and RCA bot.

    Args:
        db: Database session
        workspace_id: Workspace ID

    Returns:
        NewRelicIntegrationStatusResponse
    """
    integration = await get_newrelic_integration(db, workspace_id)

    return NewRelicIntegrationStatusResponse(
        is_connected=integration is not None, integration=integration
    )


async def delete_newrelic_integration(
    db: AsyncSession, user_id: str, workspace_id: str
) -> bool:
    """
    Delete (hard delete) a New Relic integration.
    Standalone function that can be used by router and RCA bot.

    Args:
        db: Database session
        user_id: User ID
        workspace_id: Workspace ID

    Returns:
        bool: True if deleted, False if not found
    """
    result = await db.execute(
        select(NewRelicIntegration).where(
            NewRelicIntegration.workspace_id == workspace_id
        )
    )
    integration = result.scalar_one_or_none()

    if not integration:
        return False

    await db.delete(integration)
    await db.commit()
    return True
