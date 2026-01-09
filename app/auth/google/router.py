import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth_state import oauth_state_manager
from app.core.otel_metrics import AUTH_METRICS

from .schemas import RefreshTokenRequest, UserResponse
from .service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])
auth_service = AuthService()


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

    Returns the Google OAuth URL as JSON (instead of redirecting).
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
    - redirect_uri: Frontend callback URL (e.g., http://localhost:3000/auth/callback)
    - state: CSRF state parameter (optional but recommended)
    - code_challenge: PKCE code challenge (optional, for SPA/mobile apps)
    - code_challenge_method: PKCE method (S256 or plain, default S256)

    **Returns:**
    - auth_url: Complete Google OAuth URL to redirect to
    - state: The state parameter (if provided)
    """
    try:
        # Store state in backend for validation during callback (CSRF protection)
        if state:
            oauth_state_manager.store_state(
                state, ttl_seconds=300
            )  # 5 minutes expiration

        # Generate auth URL with frontend callback URL and PKCE
        auth_url = auth_service.get_google_auth_url(
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
async def callback(
    code: str = Query(..., description="Authorization code from Google"),
    redirect_uri: str = Query(
        ...,
        description="Frontend callback URI that matches the one used in authorization",
    ),
    state: Optional[str] = Query(None, description="CSRF state parameter"),
    code_verifier: Optional[str] = Query(
        None, description="PKCE code verifier (if PKCE was used)"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange authorization code for tokens with PKCE (POST) - Frontend calls this

    This endpoint is called by the frontend after receiving the authorization code.
    It exchanges the code for tokens and returns them as JSON.

    Parameters:
    - code: Authorization code from Google
    - redirect_uri: Must match the URI used in the authorization request
    - state: CSRF state parameter (optional but recommended)
    - code_verifier: PKCE code verifier (optional, required if code_challenge was used)

    Returns:
    - access_token, refresh_token, and user information as JSON
    """
    try:
        # Validate state parameter (CSRF protection)
        if state:
            is_valid = oauth_state_manager.validate_and_consume_state(state)
            if not is_valid:
                AUTH_METRICS["auth_failures_total"].add(1)
                raise HTTPException(
                    status_code=403,
                    detail="Invalid or expired state parameter. Possible CSRF attack.",
                )
        # Exchange code for Google tokens with PKCE support
        token_data = await auth_service.exchange_code_for_tokens(
            code=code, redirect_uri=redirect_uri, code_verifier=code_verifier
        )

        # Get user info from Google using access token
        user_info = await auth_service.get_user_info_from_google(
            token_data["access_token"]
        )

        # Check if we got required user info
        if not user_info or not user_info.get("email"):
            AUTH_METRICS["auth_failures_total"].add(1)

        # Validate ID token if present
        if "id_token" in token_data:
            await auth_service.validate_id_token(token_data["id_token"])

        # Create or get user
        user = await auth_service.create_or_get_user(google_user_info=user_info, db=db)

        # Generate our own JWT tokens
        access_token = auth_service.create_access_token(
            data={"sub": user.id, "email": user.email}
        )
        refresh_token = await auth_service.create_refresh_token(
            data={"sub": user.id, "email": user.email}, db=db
        )

        # Return tokens as JSON
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
        AUTH_METRICS["auth_failures_total"].add(1)
        logger.error("OAuth callback failed", exc_info=True)
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {str(e)}")


@router.post("/refresh")
async def refresh_token(
    request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token endpoint

    Exchanges refresh token for a new access token
    """
    try:
        return await auth_service.refresh_access_token(request.refresh_token, db)
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token refresh failed: {str(e)}")


@router.get("/me", response_model=UserResponse)
async def get_current_user_endpoint(user=Depends(auth_service.get_current_user)):
    """Get current authenticated user"""
    return UserResponse.model_validate(user)


@router.post("/logout")
async def logout(
    user=Depends(auth_service.get_current_user), db: AsyncSession = Depends(get_db)
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


@router.post("/one-tap")
async def one_tap_signin(
    credential: str = Query(..., description="Google ID token from One Tap"),
    db: AsyncSession = Depends(get_db),
):
    """
    Google One Tap Sign-In endpoint

    Accepts a Google ID token (credential) from Google One Tap/Sign In With Google
    and exchanges it for our JWT access and refresh tokens.

    Parameters:
    - credential: The ID token returned by Google One Tap

    Returns:
    - access_token, refresh_token, and user information as JSON
    """
    try:
        # Validate the Google ID token
        id_token_payload = await auth_service.validate_id_token(credential)

        # Extract user info from the validated ID token
        email = id_token_payload.get("email")
        name = id_token_payload.get("name", "")

        if not email:
            raise HTTPException(
                status_code=400,
                detail="Email not found in ID token",
            )

        # Build user info dict matching the format from get_user_info_from_google
        google_user_info = {
            "sub": id_token_payload.get("sub"),
            "email": email,
            "name": name,
            "picture": id_token_payload.get("picture"),
        }

        # Create or get user
        user = await auth_service.create_or_get_user(
            google_user_info=google_user_info, db=db
        )

        # Generate our own JWT tokens
        access_token = auth_service.create_access_token(
            data={"sub": user.id, "email": user.email}
        )
        refresh_token = await auth_service.create_refresh_token(
            data={"sub": user.id, "email": user.email}, db=db
        )

        # Return tokens as JSON
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
        logger.error("One Tap sign-in failed", exc_info=True)
        raise HTTPException(status_code=400, detail=f"One Tap sign-in failed: {str(e)}")
