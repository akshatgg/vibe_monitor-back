"""
Grafana integration service.
Handles Grafana integration CRUD operations.
"""

import uuid
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
import httpx

from app.models import GrafanaIntegration, Workspace
from app.utils.token_processor import token_processor

logger = logging.getLogger(__name__)


class GrafanaService:
    """Service for managing Grafana integrations"""

    async def validate_credentials(
        self,
        grafana_url: str,
        api_token: str
    ) -> bool:
        """
        Validate Grafana URL and API token by testing authentication.

        Tests the /api/user endpoint which requires a valid API token.

        Args:
            grafana_url: Grafana instance URL
            api_token: Grafana API token

        Returns:
            bool: True if credentials are valid, False otherwise
        """
        try:
            # Test authenticated endpoint - /api/user returns current user info
            # This endpoint requires valid authentication and exists in all Grafana installations
            url = f"{grafana_url.rstrip('/')}/api/user"
            headers = {
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json"
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)

                # 200 = valid credentials, 401 = invalid token, 403 = insufficient permissions
                if response.status_code == 200:
                    logger.info(f"Grafana credentials validated successfully for {grafana_url}")
                    return True
                elif response.status_code == 401:
                    logger.warning(f"Grafana authentication failed: Invalid API token")
                    return False
                elif response.status_code == 403:
                    logger.warning(f"Grafana token has insufficient permissions")
                    return False
                else:
                    logger.warning(f"Grafana credentials validation failed: {response.status_code}")
                    return False

        except httpx.TimeoutException:
            logger.error(f"Timeout connecting to Grafana at {grafana_url}")
            return False
        except httpx.RequestError as e:
            logger.error(f"Error connecting to Grafana: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error validating Grafana credentials: {e}")
            return False

    async def create_integration(
        self,
        workspace_id: str,
        grafana_url: str,
        api_token: str,
        db: AsyncSession,
    ) -> GrafanaIntegration:
        """
        Create a new Grafana integration for a workspace.

        Args:
            workspace_id: VibeMonitor workspace ID
            grafana_url: Grafana instance URL
            api_token: Grafana API token (will be encrypted)
            db: Database session

        Returns:
            GrafanaIntegration: Created integration object

        Raises:
            HTTPException: If workspace not found or integration already exists
        """
        # Verify workspace exists
        workspace = await db.get(Workspace, workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Check if integration already exists
        result = await db.execute(
            select(GrafanaIntegration).where(
                GrafanaIntegration.vm_workspace_id == workspace_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=400,
                detail="Grafana integration already exists for this workspace. Please disconnect first.",
            )

        # Encrypt the token
        encrypted_token = token_processor.encrypt(api_token)

        # Create integration
        integration = GrafanaIntegration(
            id=str(uuid.uuid4()),
            vm_workspace_id=workspace_id,
            grafana_url=grafana_url.rstrip("/"),
            api_token=encrypted_token,
        )

        db.add(integration)
        await db.commit()
        await db.refresh(integration)

        logger.info(f"Created Grafana integration for workspace {workspace_id}")
        return integration

    async def get_integration(
        self, workspace_id: str, db: AsyncSession
    ) -> Optional[GrafanaIntegration]:
        """
        Get Grafana integration for a workspace.

        Args:
            workspace_id: VibeMonitor workspace ID
            db: Database session

        Returns:
            Optional[GrafanaIntegration]: Integration object if exists, None otherwise
        """
        result = await db.execute(
            select(GrafanaIntegration).where(
                GrafanaIntegration.vm_workspace_id == workspace_id
            )
        )
        return result.scalar_one_or_none()

    async def delete_integration(
        self, workspace_id: str, db: AsyncSession
    ) -> bool:
        """
        Delete Grafana integration for a workspace.

        Args:
            workspace_id: VibeMonitor workspace ID
            db: Database session

        Returns:
            bool: True if deleted, False if not found
        """
        integration = await self.get_integration(workspace_id, db)

        if not integration:
            return False

        await db.delete(integration)
        await db.commit()

        logger.info(f"Deleted Grafana integration for workspace {workspace_id}")
        return True

