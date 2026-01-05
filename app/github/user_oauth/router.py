"""
GitHub User OAuth Router

Endpoints for per-user GitHub OAuth integration with 'repo' scope.
This allows individual developers to access repositories they have
permission to view without requiring org admin to install a GitHub App.
"""

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google.service import AuthService
from app.core.config import settings
from app.core.database import get_db
from app.core.oauth_state import oauth_state_manager

from .service import github_user_oauth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github-oauth", tags=["github-user-oauth"])
auth_service = AuthService()


@router.get("/authorize")
async def get_oauth_authorize_url(
    user=Depends(auth_service.get_current_user),
):
    """
    Get GitHub OAuth URL with 'repo' scope for repository access.

    This reuses the same OAuth app as sign-in, but requests 'repo' scope
    for private repository access. The token will be stored per-user
    and work across all workspaces.
    """
    # Generate state with user ID embedded for validation
    random_part = secrets.token_urlsafe(16)
    state = f"repo_access|{user.id}|{random_part}"
    oauth_state_manager.store_state(state, ttl_seconds=300)

    # Build redirect URI - callback is in frontend
    redirect_uri = f"{settings.WEB_APP_URL}/integrations/github-oauth/callback"

    auth_url = github_user_oauth_service.get_oauth_url_with_repo_scope(
        redirect_uri=redirect_uri,
        state=state,
    )

    return {"auth_url": auth_url, "state": state}


@router.post("/callback")
async def handle_oauth_callback(
    code: str = Query(..., description="Authorization code from GitHub"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange authorization code for token and store on user.

    This endpoint is called by the frontend after GitHub redirects back
    with the authorization code.
    """
    # Validate state
    if not oauth_state_manager.validate_and_consume_state(state):
        raise HTTPException(status_code=403, detail="Invalid or expired state")

    # Verify state contains correct user ID
    state_parts = state.split("|")
    if len(state_parts) < 2 or state_parts[1] != user.id:
        raise HTTPException(status_code=403, detail="State user mismatch")

    redirect_uri = f"{settings.WEB_APP_URL}/integrations/github-oauth/callback"

    oauth_record = await github_user_oauth_service.exchange_and_store_token(
        code=code,
        redirect_uri=redirect_uri,
        user=user,
        db=db,
    )

    return {
        "success": True,
        "message": "GitHub OAuth connected successfully",
        "username": oauth_record.github_username,
    }


@router.get("/status")
async def get_oauth_status(
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if user has valid OAuth token with 'repo' scope.

    Returns connection status and GitHub username if connected.
    """
    return await github_user_oauth_service.get_status(user=user, db=db)


@router.delete("/disconnect")
async def disconnect_oauth(
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove stored OAuth token.

    This disconnects the user's personal GitHub access.
    """
    await github_user_oauth_service.disconnect(user=user, db=db)
    return {"success": True, "message": "GitHub OAuth disconnected"}


@router.get("/repositories")
async def list_repositories(
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List repositories accessible via user's OAuth token.

    Returns all repositories the user has access to, including private ones.
    """
    return await github_user_oauth_service.list_repositories(user=user, db=db)
