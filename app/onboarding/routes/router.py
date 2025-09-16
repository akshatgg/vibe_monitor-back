from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import os
from urllib.parse import urlencode
import uuid

from ..schemas.schemas import UserResponse, GoogleOAuthToken, RefreshTokenRequest
from ..services.auth_service import AuthService
from ...core.config import settings
from ...core.database import get_db

router = APIRouter(prefix="/auth", tags=["authentication"])
auth_service = AuthService()


@router.get("/google")
async def google_auth():
    """Initiate Google OAuth flow"""
    google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    
    # Use settings instead of os.getenv
    client_id = settings.GOOGLE_CLIENT_ID
    redirect_uri = settings.GOOGLE_REDIRECT_URI or "http://localhost:8000/api/v1/auth/google/callback"
    
    if not client_id:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    
    if not redirect_uri:
        raise HTTPException(status_code=500, detail="Google OAuth redirect URI not configured")
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "response_type": "code",
        "access_type": "offline",
        "state": str(uuid.uuid4())  # For CSRF protection
    }
    
    auth_url = f"{google_auth_url}?{urlencode(params)}"
    return {"auth_url": auth_url}


@router.get("/google/callback")
async def google_callback(code: str, state: str = None, db: AsyncSession = Depends(get_db)):
    """Handle Google OAuth callback"""
    try:
        # Exchange code for token
        token_data = await auth_service.exchange_google_code(code)
        
        # Get user info from Google
        user_info = await auth_service.get_google_user_info(token_data["access_token"])
        
        # Extract user ID (Google uses 'sub' field for unique user ID)
        google_id = user_info.get("sub") or user_info.get("id")
        if not google_id:
            raise HTTPException(status_code=400, detail="Could not get user ID from Google")
        
        # Create or get user
        user = await auth_service.create_or_get_user(
            google_id=google_id,
            name=user_info.get("name", ""),
            email=user_info.get("email", ""),
            db=db
        )
        
        # Generate our own JWT tokens
        access_token = auth_service.create_access_token(data={"sub": user.id, "email": user.email})
        refresh_token = await auth_service.create_refresh_token(data={"sub": user.id, "email": user.email}, db=db)
        
        return {
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
        
    except HTTPException as he:
        # Re-raise HTTP exceptions as-is
        raise he
    except Exception as e:
        # Log the full error for debugging
        import traceback
        print(f"OAuth callback error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {str(e)}")


@router.get("/me", response_model=UserResponse)
async def get_current_user_endpoint(user = Depends(auth_service.get_current_user)):
    """Get current authenticated user"""
    return UserResponse.model_validate(user)


@router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """Refresh access token using refresh token"""
    try:
        return await auth_service.refresh_access_token(request.refresh_token, db)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token refresh failed: {str(e)}")