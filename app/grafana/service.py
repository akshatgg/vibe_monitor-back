"""
Grafana Cloud integration service.
Handles Loki API verification and Grafana integration CRUD operations.
"""

import uuid
import httpx
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.models import GrafanaIntegration, Workspace
from app.utils.token_processor import token_processor

logger = logging.getLogger(__name__)


class GrafanaService:
    """Service for managing Grafana Cloud integrations"""

    async def verify_loki_token(self, grafana_url: str, api_token: str) -> bool:
        """
        Verify Grafana Cloud token by testing connection to Loki.

        For Grafana Cloud, the token format should be: <instance_id>:<access_token>
        This uses Basic Auth where username=instance_id, password=access_token

        Args:
            grafana_url: Loki URL (e.g., https://logs-prod-us-central1.grafana.net)
            api_token: Format "<instance_id>:<token>" or just the token

        Returns:
            bool: True if connection successful

        Raises:
            HTTPException: If verification fails
        """
        grafana_url = grafana_url.rstrip("/")
        loki_url = f"{grafana_url}/loki/api/v1/labels"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                # Check if token contains instance_id:token format
                if ":" in api_token:
                    # Split into username:password for Basic Auth
                    parts = api_token.split(":", 1)
                    username, password = parts[0], parts[1]
                    response = await client.get(loki_url, auth=(username, password))
                else:
                    # Try as Bearer token
                    headers = {
                        "Authorization": f"Bearer {api_token}",
                        "X-Scope-OrgID": "1"
                    }
                    response = await client.get(loki_url, headers=headers)

                if response.status_code == 200:
                    logger.info(f"Loki connection verified for {grafana_url}")
                    return True
                elif response.status_code == 401:
                    raise HTTPException(
                        status_code=401,
                        detail="Invalid credentials. Use format: '<instance_id>:<token>' or check your Loki URL."
                    )
                elif response.status_code == 403:
                    raise HTTPException(
                        status_code=403,
                        detail="Token lacks permissions. Ensure it has logs:read scope."
                    )
                elif response.status_code == 404:
                    raise HTTPException(
                        status_code=404,
                        detail="Loki endpoint not found. For Grafana Cloud, use the Loki URL (e.g., https://logs-prod-<region>.grafana.net), not the Grafana dashboard URL."
                    )
                elif response.status_code in (302, 307):
                    raise HTTPException(
                        status_code=401,
                        detail="Authentication failed. Check your Loki URL and credentials."
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Connection failed (HTTP {response.status_code}). Verify Loki URL and token format."
                    )

        except HTTPException:
            raise
        except httpx.RequestError as e:
            logger.error(f"Network error: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Cannot connect to {grafana_url}. Verify the Loki URL."
            )

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
            grafana_url: Grafana Cloud stack URL
            api_token: Grafana Access Policy token (will be encrypted)
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

    def get_decrypted_token(self, integration: GrafanaIntegration) -> str:
        """
        Decrypt the stored API token.

        Args:
            integration: GrafanaIntegration object with encrypted token

        Returns:
            str: Decrypted API token
        """
        return token_processor.decrypt(integration.api_token)
