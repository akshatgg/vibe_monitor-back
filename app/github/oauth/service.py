from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
from jose import jwt
import time
from typing import Dict
import uuid
from datetime import datetime, timezone, timedelta
from dateutil import parser as date_parser

from ...models import GitHubIntegration
from ...core.config import settings
from ...utils.token_processor import token_processor


class GitHubAppService:
    def __init__(self):
        self.GITHUB_APP_ID = settings.GITHUB_APP_ID
        self.GITHUB_PRIVATE_KEY = settings.GITHUB_PRIVATE_KEY_PEM
        self.GITHUB_API_BASE = "https://api.github.com"

    def generate_jwt(self) -> str:
        """Generate JWT for GitHub App authentication"""
        if not self.GITHUB_APP_ID or not self.GITHUB_PRIVATE_KEY:
            raise HTTPException(
                status_code=500,
                detail="GitHub App not configured properly"
            )

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": self.GITHUB_APP_ID
        }

        try:
            private_key = self.GITHUB_PRIVATE_KEY.strip()
            if not private_key.startswith("-----BEGIN"):
                import textwrap
                key_body = textwrap.fill(private_key.replace('"', ''), 64)
                private_key = f"-----BEGIN RSA PRIVATE KEY-----\n{key_body}\n-----END RSA PRIVATE KEY-----"

            token = jwt.encode(payload, private_key, algorithm="RS256")
            return token
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate JWT: {str(e)}"
            )

    async def get_installation_info_by_id(self, installation_id: str) -> Dict:
        """Get GitHub App installation info by ID"""
        jwt_token = self.generate_jwt()

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        url = f"{self.GITHUB_API_BASE}/app/installations/{installation_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get installation info: {response.text}"
                )

            return response.json()

    async def create_or_update_app_integration_with_installation(
        self,
        workspace_id: str,
        installation_id: str,
        installation_info: Dict,
        db: AsyncSession
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
                detail="workspace_id is required for GitHub App installation"
            )

        # Check if installation already exists for this specific workspace
        result = await db.execute(
            select(GitHubIntegration).where(
                GitHubIntegration.installation_id == installation_id,
                GitHubIntegration.workspace_id == workspace_id
            )
        )
        existing_integration = result.scalar_one_or_none()

        if existing_integration:
            # Update existing integration
            existing_integration.workspace_id = workspace_id
            existing_integration.last_synced_at = datetime.now(timezone.utc)
            existing_integration.github_username = installation_info.get("account", {}).get("login", "")
            existing_integration.github_user_id = str(installation_info.get("account", {}).get("id", ""))

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

        # Create new integration
        integration_id = str(uuid.uuid4())
        new_integration = GitHubIntegration(
            id=integration_id,
            workspace_id=workspace_id,
            github_user_id=str(installation_info.get("account", {}).get("id", "")),
            github_username=installation_info.get("account", {}).get("login", ""),
            installation_id=installation_id,
            scopes="app_permissions",
            last_synced_at=datetime.now(timezone.utc)
        )

        db.add(new_integration)
        await db.commit()
        await db.refresh(new_integration)

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
            "X-GitHub-Api-Version": "2022-11-28"
        }

        url = f"{self.GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens"

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers)

            if response.status_code != 201:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get access token: {response.text}"
                )

            data = response.json()
            return {
                "token": data["token"],
                "expires_at": data["expires_at"]  # ISO 8601 format: "2025-10-03T13:00:00Z"
            }

    async def get_valid_access_token(
        self,
        workspace_id: str,
        db: AsyncSession
    ) -> str:
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
                detail=f"No GitHub integration found for workspace {workspace_id}"
            )

        # Check if we have a valid token
        now = datetime.now(timezone.utc)
        token_is_valid = (
            integration.access_token is not None
            and integration.token_expires_at is not None
            and integration.token_expires_at > now + timedelta(minutes=5)  # Refresh 5 min before expiry
        )

        if token_is_valid:
            # Return existing token (decrypted)
            return token_processor.decrypt(integration.access_token)

        # Token expired or missing - get a new one
        token_data = await self.get_installation_access_token(integration.installation_id)

        # Parse expiry time and save to database
        expires_at = date_parser.isoparse(token_data["expires_at"])
        integration.access_token = token_processor.encrypt(token_data["token"])
        integration.token_expires_at = expires_at

        await db.commit()
        await db.refresh(integration)

        return token_data["token"]

    async def list_repositories(
        self,
        workspace_id: str,
        db: AsyncSession
    ) -> Dict:
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
            "X-GitHub-Api-Version": "2022-11-28"
        }

        url = f"{self.GITHUB_API_BASE}/installation/repositories"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to list repositories: {response.text}"
                )

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
            "X-GitHub-Api-Version": "2022-11-28"
        }

        url = f"{self.GITHUB_API_BASE}/app/installations/{installation_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(url, headers=headers)

            if response.status_code == 204:
                return True
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to uninstall GitHub App: {response.text}"
                )
