import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth_state import oauth_state_manager

from .schemas import UserResponse
from .service import GitHubAuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/github", tags=["github-authentication"])
github_auth_service = GitHubAuthService()


@router.get("/login")
async def login(
    redirect_uri: str = Query(
        ...,
        description="The URI to redirect to after authentication (frontend callback URL)",
    ),
    state: Optional[str] = Query(None, description="CSRF state parameter"),
    code_challenge: Optional[str] = Query(
        None, description="PKCE code challenge for SPA/mobile"
    ),
    code_challenge_method: Optional[str] = Query(
        "S256", description="PKCE code challenge method"
    ),
):
    """
    OAuth 2.0 Authorization Code Flow with PKCE - Login Endpoint

    Returns the GitHub OAuth URL as JSON (instead of redirecting).
    This avoids CORS issues in Swagger and allows backend testing.

    **How to use:**

    **In Frontend:**
    1. Call this endpoint with your parameters
    2. Get the `auth_url` from response
    3. Redirect: `window.location.href = response.auth_url`

    **In Swagger (Backend Testing):**
    1. Call this endpoint
    2. Copy the `auth_url` from response
    3. Paste in browser and complete OAuth
    4. Use the code from callback with POST /callback

    **Parameters:**
    - redirect_uri: Frontend callback URL (e.g., http://localhost:3000/auth/github/callback)
    - state: CSRF state parameter (optional but recommended)
    - code_challenge: PKCE code challenge (optional, for SPA/mobile apps)
    - code_challenge_method: PKCE method (S256 or plain, default S256)

    **Returns:**
    - auth_url: Complete GitHub OAuth URL to redirect to
    - state: The state parameter (if provided)
    """
    try:
        # Store state in backend for validation during callback (CSRF protection)
        if state:
            oauth_state_manager.store_state(
                state, ttl_seconds=300
            )  # 5 minutes expiration

        # Generate auth URL with frontend callback URL and PKCE
        auth_url = github_auth_service.get_github_auth_url(
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

        # Return URL as JSON (frontend will redirect manually)
        return {"auth_url": auth_url, "state": state}

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate OAuth URL: {str(e)}"
        )


@router.post("/callback")
async def exchange_code(
    code: str = Query(..., description="Authorization code from GitHub"),
    redirect_uri: str = Query(
        ...,
        description="Frontend callback URI that matches the one used in authorization",
    ),
    state: Optional[str] = Query(
        None, description="State parameter for CSRF validation"
    ),
    code_verifier: Optional[str] = Query(
        None, description="PKCE code verifier (if PKCE was used)"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange authorization code for tokens with PKCE (POST) - Frontend calls this

    This endpoint is called by the frontend after receiving the authorization code.
    It exchanges the code for tokens and returns them as JSON.
    (Same pattern as Google OAuth)

    Parameters:
    - code: Authorization code from GitHub
    - redirect_uri: Must match the URI used in the authorization request
    - state: State parameter for CSRF validation (optional but recommended)
    - code_verifier: PKCE code verifier (optional, required if code_challenge was used)

    Returns:
    - access_token, refresh_token, and user information as JSON
    """
    try:
        # Validate state parameter (CSRF protection)
        if state:
            is_valid = oauth_state_manager.validate_and_consume_state(state)
            if not is_valid:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid or expired state parameter. Possible CSRF attack.",
                )
        # Exchange code for GitHub tokens with PKCE support
        token_data = await github_auth_service.exchange_code_for_tokens(
            code=code, redirect_uri=redirect_uri, code_verifier=code_verifier
        )

        # Get user info from GitHub using access token
        user_info = await github_auth_service.get_user_info_from_github(
            token_data["access_token"]
        )

        # Create or get user
        user = await github_auth_service.create_or_get_user(
            github_user_info=user_info, db=db
        )

        # Generate our own JWT tokens
        access_token = github_auth_service.create_access_token(
            data={"sub": user.id, "email": user.email}
        )
        refresh_token = await github_auth_service.create_refresh_token(
            data={"sub": user.id, "email": user.email}, db=db
        )

        # Return tokens as JSON (same as Google OAuth)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "last_visited_workspace_id": user.last_visited_workspace_id,
            "user": user,
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error("OAuth token exchange failed", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {str(e)}")


@router.get("/me", response_model=UserResponse)
async def get_current_user_endpoint(user=Depends(github_auth_service.get_current_user)):
    """Get current authenticated user"""
    return UserResponse.model_validate(user)


@router.post("/logout")
async def logout(
    user=Depends(github_auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Logout user and revoke refresh tokens
    """
    try:
        # Revoke all refresh tokens for this user
        from sqlalchemy import delete

        from app.models import RefreshToken

        await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
        await db.commit()

        return {"message": "Successfully logged out"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Logout failed: {str(e)}")
