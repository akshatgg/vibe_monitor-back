"""
GitHub User OAuth Service

Handles OAuth with 'repo' scope for personal repository access.
Token is stored per-user and works across all workspaces.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import GitHubUserOAuth, User
from app.utils.retry_decorator import retry_external_api
from app.utils.token_processor import token_processor

logger = logging.getLogger(__name__)


class GitHubUserOAuthService:
    """Service for user-level GitHub OAuth integration."""

    def __init__(self):
        self.GITHUB_CLIENT_ID = settings.GITHUB_OAUTH_CLIENT_ID
        self.GITHUB_CLIENT_SECRET = settings.GITHUB_OAUTH_CLIENT_SECRET
        self.GITHUB_AUTH_URL = settings.GITHUB_OAUTH_AUTH_URL
        self.GITHUB_TOKEN_URL = settings.GITHUB_OAUTH_TOKEN_URL
        self.GITHUB_USER_URL = settings.GITHUB_OAUTH_USER_URL
        self.GITHUB_API_BASE = settings.GITHUB_API_BASE_URL
        # Repo scope for private repository access
        self.GITHUB_REPO_SCOPE = "repo read:user user:email"

    def get_oauth_url_with_repo_scope(
        self,
        redirect_uri: str,
        state: str,
    ) -> str:
        """Generate GitHub OAuth URL with 'repo' scope."""
        if not self.GITHUB_CLIENT_ID:
            raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

        params = {
            "client_id": self.GITHUB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": self.GITHUB_REPO_SCOPE,
            "state": state,
            "allow_signup": "false",  # User already has account
        }

        return f"{self.GITHUB_AUTH_URL}?{urlencode(params)}"

    async def exchange_and_store_token(
        self,
        code: str,
        redirect_uri: str,
        user: User,
        db: AsyncSession,
    ) -> GitHubUserOAuth:
        """Exchange code for token and store on user."""
        # Exchange code for token
        token_data = await self._exchange_code_for_token(code, redirect_uri)
        access_token = token_data.get("access_token")

        if not access_token:
            error = token_data.get(
                "error_description", token_data.get("error", "Unknown error")
            )
            logger.error(f"Failed to get GitHub access token: {error}")
            raise HTTPException(
                status_code=400, detail=f"Failed to get access token: {error}"
            )

        # Get GitHub user info
        github_user = await self._get_github_user(access_token)

        # Check if user already has a GitHub OAuth record
        stmt = select(GitHubUserOAuth).where(GitHubUserOAuth.user_id == user.id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing record
            existing.github_user_id = str(github_user.get("id"))
            existing.github_username = github_user.get("login")
            existing.access_token = token_processor.encrypt(access_token)
            existing.scopes = token_data.get("scope", self.GITHUB_REPO_SCOPE)
            existing.updated_at = datetime.now(timezone.utc)
            oauth_record = existing
        else:
            # Create new record
            oauth_record = GitHubUserOAuth(
                id=str(uuid.uuid4()),
                user_id=user.id,
                github_user_id=str(github_user.get("id")),
                github_username=github_user.get("login"),
                access_token=token_processor.encrypt(access_token),
                scopes=token_data.get("scope", self.GITHUB_REPO_SCOPE),
            )
            db.add(oauth_record)

        await db.commit()
        await db.refresh(oauth_record)

        logger.info(
            f"GitHub OAuth connected for user {user.id} as @{github_user.get('login')}"
        )
        return oauth_record

    async def _exchange_code_for_token(
        self,
        code: str,
        redirect_uri: str,
    ) -> Dict:
        """Exchange authorization code for access token."""
        data = {
            "client_id": self.GITHUB_CLIENT_ID,
            "client_secret": self.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        headers = {"Accept": "application/json"}

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.post(
                        self.GITHUB_TOKEN_URL, data=data, headers=headers
                    )
                    response.raise_for_status()
                    return response.json()

    async def _get_github_user(self, access_token: str) -> Dict:
        """Get GitHub user info using access token."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.get(self.GITHUB_USER_URL, headers=headers)
                    response.raise_for_status()
                    return response.json()

    async def get_status(self, user: User, db: AsyncSession) -> Dict:
        """Check if user has valid OAuth token."""
        stmt = select(GitHubUserOAuth).where(GitHubUserOAuth.user_id == user.id)
        result = await db.execute(stmt)
        oauth_record = result.scalar_one_or_none()

        if not oauth_record:
            return {
                "connected": False,
                "method": None,
            }

        # Verify token is still valid by making a test API call
        try:
            access_token = token_processor.decrypt(oauth_record.access_token)
            await self._get_github_user(access_token)  # Validates token

            return {
                "connected": True,
                "method": "oauth",
                "username": oauth_record.github_username,
                "github_user_id": oauth_record.github_user_id,
                "scopes": oauth_record.scopes,
                "connected_at": oauth_record.created_at.isoformat()
                if oauth_record.created_at
                else None,
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.warning(f"GitHub OAuth token revoked for user {user.id}")
                return {
                    "connected": False,
                    "method": None,
                    "error": "Token revoked or expired",
                }
            raise
        except Exception as e:
            logger.warning(f"GitHub OAuth token invalid for user {user.id}: {e}")
            return {
                "connected": False,
                "method": None,
                "error": "Token invalid",
            }

    async def disconnect(self, user: User, db: AsyncSession) -> None:
        """Remove OAuth token from user and revoke on GitHub."""
        stmt = select(GitHubUserOAuth).where(GitHubUserOAuth.user_id == user.id)
        result = await db.execute(stmt)
        oauth_record = result.scalar_one_or_none()

        if oauth_record:
            # Revoke grant on GitHub first
            try:
                access_token = token_processor.decrypt(oauth_record.access_token)
                await self._revoke_token_on_github(access_token)
            except Exception as e:
                # Log but don't fail - we still want to remove our record
                logger.warning(f"Failed to revoke GitHub token: {e}")

            await db.delete(oauth_record)
            await db.commit()
            logger.info(f"GitHub OAuth disconnected for user {user.id}")

    async def _revoke_token_on_github(self, access_token: str) -> None:
        """Revoke OAuth grant on GitHub's side (forces re-authorization)."""
        # Use grant revocation (not token revocation) to force re-consent
        # https://docs.github.com/en/rest/apps/oauth-applications#delete-an-app-authorization
        url = f"https://api.github.com/applications/{self.GITHUB_CLIENT_ID}/grant"

        async with httpx.AsyncClient() as client:
            # httpx.delete() doesn't support json param, use request() instead
            response = await client.request(
                method="DELETE",
                url=url,
                auth=(self.GITHUB_CLIENT_ID, self.GITHUB_CLIENT_SECRET),
                content=json.dumps({"access_token": access_token}),
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json",
                },
            )

            # 204 = success, 404 = already revoked
            if response.status_code not in (204, 404):
                logger.warning(
                    f"GitHub grant revocation failed: {response.status_code} - {response.text}"
                )

    async def list_repositories(self, user: User, db: AsyncSession) -> Dict:
        """List repositories accessible via OAuth token."""
        stmt = select(GitHubUserOAuth).where(GitHubUserOAuth.user_id == user.id)
        result = await db.execute(stmt)
        oauth_record = result.scalar_one_or_none()

        if not oauth_record:
            raise HTTPException(status_code=404, detail="No GitHub OAuth connection")

        try:
            access_token = token_processor.decrypt(oauth_record.access_token)
        except Exception:
            raise HTTPException(status_code=401, detail="Failed to decrypt token")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        # Fetch user's repositories (including private)
        url = f"{self.GITHUB_API_BASE}/user/repos"
        params = {
            "visibility": "all",
            "sort": "updated",
            "per_page": 100,
        }

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.get(url, headers=headers, params=params)
                    response.raise_for_status()
                    repos = response.json()

                    return {
                        "total_count": len(repos),
                        "repositories": [
                            {
                                "id": repo["id"],
                                "name": repo["name"],
                                "full_name": repo["full_name"],
                                "private": repo["private"],
                                "description": repo.get("description"),
                                "default_branch": repo.get("default_branch"),
                                "html_url": repo["html_url"],
                            }
                            for repo in repos
                        ],
                    }


# Global instance
github_user_oauth_service = GitHubUserOAuthService()
