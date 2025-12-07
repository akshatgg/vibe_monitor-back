"""
Datadog Integration Service
Handles CRUD operations for Datadog integrations
"""
import uuid
import logging
import httpx
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.models import DatadogIntegration
from app.utils.token_processor import token_processor
from .schemas import (
    DatadogIntegrationCreate,
    DatadogIntegrationResponse,
    DatadogIntegrationStatusResponse,
)

logger = logging.getLogger(__name__)


# =============================================================================
# REGION MAPPING
# =============================================================================

def get_datadog_domain(region: str) -> str:
    """
    Map Datadog region code to full domain.

    Args:
        region: Region code (e.g., us1, us5, eu1)

    Returns:
        Full domain (e.g., datadoghq.com, us5.datadoghq.com)
    """
    region_map = {
        'us1': 'datadoghq.com',
        'us3': 'us3.datadoghq.com',
        'us5': 'us5.datadoghq.com',
        'eu1': 'datadoghq.eu',
        'ap1': 'ap1.datadoghq.com',
        'us1-fed': 'ddog-gov.com',
    }
    return region_map.get(region.lower(), 'datadoghq.com')


# =============================================================================
# STANDALONE UTILITY FUNCTIONS (Can be used by router and RCA bot)
# =============================================================================

async def verify_datadog_credentials(
    api_key: str, app_key: str, region: str
) -> Tuple[bool, str]:
    """
    Verify Datadog API key and Application key by making a test API call.
    This is a standalone function that can be used by router and RCA bot.

    Args:
        api_key: Datadog API Key (organization-level)
        app_key: Datadog Application Key (organization-level with permissions)
        region: Datadog region code (e.g., us1, us5, eu1)

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if credentials are valid, False otherwise
        - error_message: Empty string if valid, error description if invalid
    """
    domain = get_datadog_domain(region)
    url = f"https://api.{domain}/api/v1/validate"
    headers = {
        "DD-API-KEY": api_key,
        "DD-APPLICATION-KEY": app_key,
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
                timeout=10.0
            )

            if response.status_code == 403:
                return False, "Invalid API key or Application key"

            if response.status_code == 401:
                return False, "Authentication failed - check your credentials"

            if response.status_code != 200:
                return False, f"API request failed with status {response.status_code}"

            data = response.json()

            # Check if validation was successful
            if data.get("valid"):
                logger.info(f"Successfully verified Datadog credentials for region: {region}")
                return True, ""

            return False, "Credentials validation failed"

    except httpx.TimeoutException:
        logger.error("Datadog API request timeout")
        return False, "Request timeout - Datadog API did not respond"
    except Exception as e:
        logger.error(f"Datadog verification error: {str(e)}")
        return False, f"Verification error: {str(e)}"


async def get_datadog_integration(
    db: AsyncSession, workspace_id: str
) -> Optional[DatadogIntegrationResponse]:
    """
    Get Datadog integration for a workspace.
    Standalone function that can be used by router and RCA bot.

    Args:
        db: Database session
        workspace_id: Workspace ID

    Returns:
        DatadogIntegrationResponse or None if not found
    """
    result = await db.execute(
        select(DatadogIntegration).where(
            DatadogIntegration.workspace_id == workspace_id
        )
    )
    integration = result.scalar_one_or_none()

    if not integration:
        return None

    return DatadogIntegrationResponse(
        id=integration.id,
        workspace_id=integration.workspace_id,
        region=integration.region,
        last_verified_at=integration.last_verified_at,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


async def create_datadog_integration(
    db: AsyncSession,
    user_id: str,
    workspace_id: str,
    integration_data: DatadogIntegrationCreate,
) -> DatadogIntegrationResponse:
    """
    Create a new Datadog integration for a workspace.
    Standalone function that can be used by router and RCA bot.

    Args:
        db: Database session
        user_id: User ID
        workspace_id: Workspace ID
        integration_data: Datadog integration data (api_key, app_key, site)

    Returns:
        DatadogIntegrationResponse

    Raises:
        ValueError: If integration already exists or credentials are invalid
    """
    # Check if integration already exists for this workspace
    result = await db.execute(
        select(DatadogIntegration).where(
            DatadogIntegration.workspace_id == workspace_id
        )
    )
    existing_integration = result.scalar_one_or_none()

    if existing_integration:
        raise ValueError(
            "A Datadog integration already exists for this workspace"
        )

    # Verify Datadog credentials before storing
    is_valid, error_message = await verify_datadog_credentials(
        integration_data.api_key,
        integration_data.app_key,
        integration_data.region
    )

    if not is_valid:
        raise ValueError(f"Invalid Datadog credentials: {error_message}")

    # Encrypt API key and App key before storage
    encrypted_api_key = token_processor.encrypt(integration_data.api_key)
    encrypted_app_key = token_processor.encrypt(integration_data.app_key)

    # Create new integration
    integration = DatadogIntegration(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        api_key=encrypted_api_key,
        app_key=encrypted_app_key,
        region=integration_data.region,
        last_verified_at=datetime.now(timezone.utc),
    )

    db.add(integration)
    await db.commit()
    await db.refresh(integration)

    return DatadogIntegrationResponse(
        id=integration.id,
        workspace_id=integration.workspace_id,
        region=integration.region,
        last_verified_at=integration.last_verified_at,
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


async def get_datadog_integration_status(
    db: AsyncSession,
    workspace_id: str
) -> DatadogIntegrationStatusResponse:
    """
    Get Datadog integration status for a workspace.
    Standalone function that can be used by router and RCA bot.

    Args:
        db: Database session
        workspace_id: Workspace ID

    Returns:
        DatadogIntegrationStatusResponse
    """
    integration = await get_datadog_integration(db, workspace_id)

    return DatadogIntegrationStatusResponse(
        is_connected=integration is not None,
        integration=integration
    )


async def delete_datadog_integration(
    db: AsyncSession,
    user_id: str,
    workspace_id: str
) -> bool:
    """
    Delete (hard delete) a Datadog integration.
    Standalone function that can be used by router and RCA bot.

    Args:
        db: Database session
        user_id: User ID
        workspace_id: Workspace ID

    Returns:
        bool: True if deleted, False if not found
    """
    result = await db.execute(
        select(DatadogIntegration).where(
            DatadogIntegration.workspace_id == workspace_id
        )
    )
    integration = result.scalar_one_or_none()

    if not integration:
        return False

    await db.delete(integration)
    await db.commit()
    return True

