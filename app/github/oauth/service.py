from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
from jose import jwt
import time
import logging
from typing import Dict
import uuid
from datetime import datetime, timezone, timedelta
from dateutil import parser as date_parser

from ...models import GitHubIntegration, Integration
from ...core.config import settings
from ...utils.token_processor import token_processor
from ...utils.retry_decorator import retry_external_api
from ...integrations.health_checks import check_github_health

logger = logging.getLogger(__name__)


class GitHubAppService:
    def __init__(self):
        self.GITHUB_APP_ID = settings.GITHUB_APP_ID
        self.GITHUB_PRIVATE_KEY = settings.GITHUB_PRIVATE_KEY_PEM
        self.GITHUB_API_BASE = settings.GITHUB_API_BASE_URL

    def generate_jwt(self) -> str:
        """Generate JWT for GitHub App authentication"""
        if not self.GITHUB_APP_ID or not self.GITHUB_PRIVATE_KEY:
            raise HTTPException(
                status_code=500, detail="GitHub App not configured properly"
            )

        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + (10 * 60), "iss": self.GITHUB_APP_ID}

        try:
            private_key = self.GITHUB_PRIVATE_KEY.strip()
            if not private_key.startswith("-----BEGIN"):
                import textwrap

                key_body = textwrap.fill(private_key.replace('"', ""), 64)
                private_key = f"-----BEGIN RSA PRIVATE KEY-----\n{key_body}\n-----END RSA PRIVATE KEY-----"

            token = jwt.encode(payload, private_key, algorithm="RS256")
            return token
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to generate JWT: {str(e)}"
            )

    async def get_installation_info_by_id(self, installation_id: str) -> Dict:
        """Get GitHub App installation info by ID"""
        jwt_token = self.generate_jwt()

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": settings.GITHUB_API_VERSION,
        }

        url = f"{self.GITHUB_API_BASE}/app/installations/{installation_id}"

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    return response.json()

    async def create_or_update_app_integration_with_installation(
        self,
        workspace_id: str,
        installation_id: str,
        installation_info: Dict,
        db: AsyncSession,
    ) -> GitHubIntegration:
        """Create or update GitHub App integration

        Args:
            workspace_id: Workspace where integration will be linked (required)
            installation_id: GitHub App installation ID
            installation_info: GitHub installation metadata
            db: Database session

        Returns:
            GitHubIntegration: Created or updated integration
        """
        if not workspace_id:
            raise HTTPException(
                status_code=400,
                detail="workspace_id is required for GitHub App installation",
            )

        # Check if installation already exists for this specific workspace
        result = await db.execute(
            select(GitHubIntegration).where(
                GitHubIntegration.installation_id == installation_id,
                GitHubIntegration.workspace_id == workspace_id,
            )
        )
        existing_integration = result.scalar_one_or_none()

        if existing_integration:
            # Update existing integration
            existing_integration.workspace_id = workspace_id
            existing_integration.last_synced_at = datetime.now(timezone.utc)
            existing_integration.github_username = installation_info.get(
                "account", {}
            ).get("login", "")
            existing_integration.github_user_id = str(
                installation_info.get("account", {}).get("id", "")
            )

            await db.commit()
            await db.refresh(existing_integration)
            return existing_integration

        # Check if there's any other integration for this workspace (different installation_id)
        # This handles the case where user changes their GitHub account
        workspace_result = await db.execute(
            select(GitHubIntegration).where(
                GitHubIntegration.workspace_id == workspace_id
            )
        )
        old_workspace_integration = workspace_result.scalar_one_or_none()

        if old_workspace_integration:
            # Delete old integration (user is switching GitHub accounts)
            await db.delete(old_workspace_integration)
            await db.commit()

        # Check if an Integration control plane record already exists for this workspace + provider
        existing_control_plane_result = await db.execute(
            select(Integration).where(
                Integration.workspace_id == workspace_id,
                Integration.provider == "github",
            )
        )
        existing_control_plane = existing_control_plane_result.scalar_one_or_none()

        if existing_control_plane:
            # Reuse existing control plane integration
            control_plane_id = existing_control_plane.id
            control_plane_integration = existing_control_plane
            control_plane_integration.status = "active"
            control_plane_integration.updated_at = datetime.now(timezone.utc)
            logger.info(
                f"Reusing existing GitHub integration {control_plane_id} for workspace {workspace_id}"
            )
        else:
            # Create new Integration control plane record
            control_plane_id = str(uuid.uuid4())
            control_plane_integration = Integration(
                id=control_plane_id,
                workspace_id=workspace_id,
                provider="github",
                status="active",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(control_plane_integration)
            await db.flush()  # Get ID without committing
            logger.info(
                f"Created new GitHub integration {control_plane_id} for workspace {workspace_id}"
            )

        # Create provider-specific integration linked to control plane
        provider_integration_id = str(uuid.uuid4())
        new_integration = GitHubIntegration(
            id=provider_integration_id,
            workspace_id=workspace_id,
            integration_id=control_plane_id,  # Link to control plane
            github_user_id=str(installation_info.get("account", {}).get("id", "")),
            github_username=installation_info.get("account", {}).get("login", ""),
            installation_id=installation_id,
            scopes="app_permissions",
            is_active=True,
            last_synced_at=datetime.now(timezone.utc),
        )

        db.add(new_integration)
        await db.commit()
        await db.refresh(new_integration)

        # Run initial health check to populate health_status
        try:
            health_status, error_message = await check_github_health(new_integration)
            control_plane_integration.health_status = health_status
            control_plane_integration.last_verified_at = datetime.now(timezone.utc)
            control_plane_integration.last_error = error_message
            if health_status == "healthy":
                control_plane_integration.status = "active"
            elif health_status == "failed":
                control_plane_integration.status = "error"
            await db.commit()
            logger.info(
                f"GitHub integration created with health_status={health_status}: "
                f"workspace_id={workspace_id}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to run initial health check for GitHub integration: {e}. "
                f"Health status remains unset."
            )

        return new_integration

    async def get_installation_access_token(self, installation_id: str) -> Dict:
        """Get installation access token to access user's repositories

        This token:
        - Expires in 1 hour
        - Has permissions granted by the user
        - Is used for ALL repository operations (read code, create PRs, etc.)

        Args:
            installation_id: GitHub App installation ID

        Returns:
            Dict with 'token' and 'expires_at' keys
        """
        jwt_token = self.generate_jwt()

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": settings.GITHUB_API_VERSION,
        }

        url = (
            f"{self.GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"
        )

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.post(url, headers=headers)
                    response.raise_for_status()

                    data = response.json()
                    return {
                        "token": data["token"],
                        "expires_at": data[
                            "expires_at"
                        ],  # ISO 8601 format: "2025-10-03T13:00:00Z"
                    }

    async def get_valid_access_token(self, workspace_id: str, db: AsyncSession) -> str:
        """Get a valid access token for the workspace, refreshing if expired

        This function:
        1. Fetches the integration from database
        2. Checks if token exists and is still valid
        3. If expired or missing, generates a new token and saves it
        4. Returns valid token ready to use

        Args:
            workspace_id: Workspace ID to get token for
            db: Database session

        Returns:
            str: Valid access token

        Raises:
            HTTPException: If no integration found or failed to get token
        """
        # Fetch integration from database
        result = await db.execute(
            select(GitHubIntegration).where(
                GitHubIntegration.workspace_id == workspace_id
            )
        )
        integration = result.scalar_one_or_none()

        if not integration:
            raise HTTPException(
                status_code=404,
                detail=f"No GitHub integration found for workspace {workspace_id}",
            )

        # Check if integration is active (not suspended)
        if not integration.is_active:
            raise HTTPException(
                status_code=403,
                detail="GitHub integration is suspended. Please check your GitHub App installation status.",
            )

        # Check if we have a valid token
        now = datetime.now(timezone.utc)
        token_is_valid = (
            integration.access_token is not None
            and integration.token_expires_at is not None
            and integration.token_expires_at
            > now
            + timedelta(
                minutes=settings.GITHUB_TOKEN_REFRESH_THRESHOLD_MINUTES
            )  # Refresh before expiry
        )

        if token_is_valid:
            # Return existing token (decrypted)
            try:
                return token_processor.decrypt(integration.access_token)
            except Exception as e:
                logger.error(f"Failed to decrypt GitHub access token: {e}")
                raise Exception("Failed to decrypt GitHub credentials")

        # Token expired or missing - get a new one
        token_data = await self.get_installation_access_token(
            integration.installation_id
        )

        # Parse expiry time and save to database
        expires_at = date_parser.isoparse(token_data["expires_at"])
        integration.access_token = token_processor.encrypt(token_data["token"])
        integration.token_expires_at = expires_at

        await db.commit()
        await db.refresh(integration)

        return token_data["token"]

    async def list_repositories(self, workspace_id: str, db: AsyncSession) -> Dict:
        """List all repositories accessible by this GitHub integration

        Example function demonstrating how to use the stored access token.

        Args:
            workspace_id: Workspace ID
            db: Database session

        Returns:
            Dict with repositories list
        """
        # Get valid token (auto-refreshes if expired)
        access_token = await self.get_valid_access_token(workspace_id, db)

        headers = {
            "Authorization": f"token {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        url = f"{self.GITHUB_API_BASE}/installation/repositories"

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    return response.json()

    async def uninstall_github_app(self, installation_id: str) -> bool:
        """Uninstall GitHub App from user's account via API

        Args:
            installation_id: GitHub App installation ID

        Returns:
            bool: True if uninstalled successfully
        """
        jwt_token = self.generate_jwt()

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": settings.GITHUB_API_VERSION,
        }

        url = f"{self.GITHUB_API_BASE}/app/installations/{installation_id}"

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.delete(url, headers=headers)
                    response.raise_for_status()
                    return True
