from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from ..schemas.google_auth_schemas import RefreshTokenRequest, UserResponse
from ..services.google_auth_service import AuthService
from app.core.config import settings
from app.core.database import get_db

router = APIRouter(prefix="/auth", tags=["authentication"])
auth_service = AuthService()


@router.get("/login")
async def login(
    redirect_uri: str = Query(
        ..., description="The URI to redirect to after authentication"
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
    OAuth 2.0 Authorization Code Flow - Login Endpoint

    Redirects user directly to Google's /authorize endpoint with params:
    - client_id
    - response_type=code
    - redirect_uri
    - scope (openid email profile offline_access)
    - state (for CSRF protection)
    - code_challenge (for PKCE, if provided)
    - code_challenge_method (S256 for PKCE)
    """
    try:
        # Generate auth URL and redirect directly
        auth_url = auth_service.get_google_auth_url(
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
        )

        return RedirectResponse(url=auth_url, status_code=302)

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to initiate OAuth flow: {str(e)}"
        )


@router.post("/callback")
async def callback(
    code: str,
    redirect_uri: str,
    state: Optional[str] = None,
    code_verifier: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth callback endpoint

    Receives code from the frontend and exchanges it at Google's /token endpoint with:
    - client_id, client_secret (backend only)
    - code
    - redirect_uri
    - grant_type=authorization_code
    - code_verifier (if PKCE was used)

    Gets back access_token, id_token, and possibly refresh_token
    Validates id_token (JWT signature, audience, expiry)

    Returns tokens directly to frontend (for SPAs/mobile)
    """
    try:
        # Exchange code for tokens
        token_data = await auth_service.exchange_code_for_tokens(
            code=code, redirect_uri=redirect_uri, code_verifier=code_verifier
        )

        # Get user info from Google using access token
        user_info = await auth_service.get_user_info_from_google(
            token_data["access_token"]
        )

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

        # Return tokens directly to frontend (for SPAs/mobile)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": user,
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback

        print(f"OAuth callback error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
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
