"""
GitHub Tools Service

This service provides helper functions for GitHub-related operations
used across multiple endpoints in the GitHub tools router.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

import httpx
from dateutil import parser as date_parser
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import time
from app.core.otel_metrics import GITHUB_METRICS

from ...core.config import settings
from ...models import GitHubIntegration, Membership
from ...utils.retry_decorator import retry_external_api
from ...utils.token_processor import token_processor
from ..oauth.service import GitHubAppService

logger = logging.getLogger(__name__)


github_app_service = GitHubAppService()


async def refresh_token_if_needed(integration, db: AsyncSession) -> None:
    """
    Refresh GitHub access token if expired or missing.

    This helper function checks if the GitHub access token is missing or expired
    and refreshes it automatically if needed. The integration object
    is updated in-place.

    Refreshes token if:
    - Token doesn't exist (access_token is None)
    - Token is expired (token_expires_at <= now)

    Args:
        integration: GitHubIntegration object with token information
        db: Database session for committing changes

    Returns:
        None. Updates the integration object in-place.
    """
    if not integration.access_token or (
        integration.token_expires_at
        and integration.token_expires_at <= datetime.now(timezone.utc)
    ):
        token_data = await github_app_service.get_installation_access_token(
            integration.installation_id
        )

        integration.access_token = token_processor.encrypt(token_data["token"])
        integration.token_expires_at = date_parser.isoparse(token_data["expires_at"])

        await db.commit()
        await db.refresh(integration)


async def get_github_integration_with_token(
    workspace_id: str, db: AsyncSession
) -> tuple:
    """
    Get GitHub integration, refresh token if needed, and return decrypted access token.

    This is a convenience function that combines three common operations:
    1. Fetch integration from database
    2. Refresh token if expired
    3. Decrypt and return access token

    Args:
        workspace_id: Workspace ID
        db: Database session

    Returns:
        Tuple of (integration, access_token)

    Raises:
        HTTPException: If integration not found
    """
    # Get GitHub integration for workspace
    result = await db.execute(
        select(GitHubIntegration).where(GitHubIntegration.workspace_id == workspace_id)
    )
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(
            status_code=404, detail="No GitHub integration found for this workspace"
        )

    # Check if integration is active (not suspended)
    if not integration.is_active:
        raise HTTPException(
            status_code=403,
            detail="GitHub integration is suspended. Please check your GitHub App installation status.",
        )

    # Refresh token if needed
    await refresh_token_if_needed(integration, db)

    # Decrypt and return access token
    access_token = None
    if integration.access_token:
        try:
            access_token = token_processor.decrypt(integration.access_token)
        except Exception as e:
            logger.error(f"Failed to decrypt GitHub access token: {e}")
            raise Exception("Failed to decrypt GitHub credentials")

    return integration, access_token


async def execute_github_graphql(
    query: str, variables: Dict[str, Any], access_token: str
) -> Dict[str, Any]:
    """
    Execute a GitHub GraphQL query.

    This helper function handles the HTTP request to GitHub's GraphQL API,
    error checking, and response parsing.

    Args:
        query: GraphQL query string
        variables: Query variables dictionary
        access_token: GitHub access token

    Returns:
        Parsed JSON response data

    Raises:
        HTTPException: If request fails or GraphQL returns errors
    """
    start_time = time.time()

    async with httpx.AsyncClient() as client:
        async for attempt in retry_external_api("GitHub"):
            with attempt:
                response = await client.post(
                    settings.GITHUB_GRAPHQL_URL,
                    json={"query": query, "variables": variables},
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                    timeout=settings.HTTP_REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()

                duration = time.time() - start_time

                if GITHUB_METRICS:
                    GITHUB_METRICS["github_api_calls_total"].add(1, {
                        "api_type": "graphql",
                        "status": str(response.status_code)
                    })

                    GITHUB_METRICS["github_api_duration_seconds"].record(duration, {
                        "api_type": "graphql"
                    })

                    rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
                    if rate_limit_remaining:
                        GITHUB_METRICS["github_api_rate_limit_remaining"].add(
                            int(rate_limit_remaining),
                            {"api_type": "graphql"}
                        )

                data = response.json()

                if "errors" in data:
                    raise HTTPException(
                        status_code=500, detail=f"GraphQL errors: {data['errors']}"
                    )

                return data


async def execute_github_rest_api(
    endpoint: str, access_token: str, method: str = "GET", params: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Execute a GitHub REST API request.

    This helper function handles the HTTP request to GitHub's REST API,
    error checking, and response parsing.

    Args:
        endpoint: API endpoint (e.g., "/search/code")
        access_token: GitHub access token
        method: HTTP method (default: GET)
        params: Query parameters dictionary

    Returns:
        Parsed JSON response data

    Raises:
        HTTPException: If request fails
    """
    
    start_time = time.time()
    url = f"{settings.GITHUB_API_BASE_URL}{endpoint}"

    async with httpx.AsyncClient() as client:
        async for attempt in retry_external_api("GitHub"):
            with attempt:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github.v3.text-match+json",
                    },
                    timeout=settings.HTTP_REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()

                # Calculate duration
                duration = time.time() - start_time

                if GITHUB_METRICS:
                    GITHUB_METRICS["github_api_calls_total"].add(1, {
                        "api_type": "rest",
                        "status": str(response.status_code)
                    })

                    GITHUB_METRICS["github_api_duration_seconds"].record(duration, {
                        "api_type": "rest",
                    })

                    # Extract rate limit from headers
                    rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
                    if rate_limit_remaining:
                        GITHUB_METRICS["github_api_rate_limit_remaining"].add(
                            int(rate_limit_remaining),
                            {"api_type": "rest"}
                        )

                return response.json()


def get_owner_or_default(owner: str, integration) -> str:
    """
    Return provided owner or default to integration username.

    Args:
        owner: Optional owner string
        integration: GitHubIntegration object

    Returns:
        Owner string (provided or default)
    """
    return owner if owner else integration.github_username


async def verify_workspace_access(
    user_id: str, workspace_id: str, db: AsyncSession
) -> None:
    """
    Verify user has access to the specified workspace.

    System users (e.g., 'rca-agent') are automatically granted access to all workspaces.

    Args:
        user_id: User ID
        workspace_id: Workspace ID
        db: Database session

    Raises:
        HTTPException: If user does not have access to the workspace
    """
    # System users (like RCA agent) have access to all workspaces
    SYSTEM_USERS = ["rca-agent"]
    if user_id in SYSTEM_USERS:
        return

    result = await db.execute(
        select(Membership).where(
            Membership.user_id == user_id, Membership.workspace_id == workspace_id
        )
    )
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(
            status_code=403, detail="User does not have access to this workspace"
        )

    return membership


# Cache for default branches: {(workspace_id, owner, repo): branch_name}
_default_branch_cache: Dict[tuple, str] = {}


async def get_default_branch(
    workspace_id: str, repo_name: str, owner: str, db: AsyncSession
) -> str:
    """
    Get the default branch name for a repository dynamically.

    This function queries GitHub's GraphQL API to fetch the repository's
    default branch (e.g., "main", "master", "develop") and caches the result
    to avoid repeated API calls.

    Args:
        workspace_id: Workspace ID
        repo_name: Repository name
        owner: Repository owner
        db: Database session

    Returns:
        str: Default branch name (e.g., "main", "master")

    Raises:
        HTTPException: If repository not found or no default branch
    """
    # Check cache first
    cache_key = (workspace_id, owner, repo_name)
    if cache_key in _default_branch_cache:
        return _default_branch_cache[cache_key]

    # Get integration and access token
    integration, access_token = await get_github_integration_with_token(
        workspace_id, db
    )

    # GraphQL query to get default branch
    query = """
    query GetDefaultBranch($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        defaultBranchRef {
          name
        }
      }
    }
    """

    variables = {"owner": owner, "name": repo_name}

    # Execute GraphQL query
    data = await execute_github_graphql(query, variables, access_token)

    repository_data = data.get("data", {}).get("repository", {})
    default_branch_ref = repository_data.get("defaultBranchRef")

    if not default_branch_ref:
        raise HTTPException(
            status_code=404,
            detail=f"No default branch found for repository {owner}/{repo_name}",
        )

    branch_name = default_branch_ref.get("name")

    # Cache the result
    _default_branch_cache[cache_key] = branch_name

    return branch_name
