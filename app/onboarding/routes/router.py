from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
import os
from urllib.parse import urlencode
import uuid

from ..schemas.schemas import UserResponse, GoogleOAuthToken
from ..services.auth_service import AuthService
from ...core.config import settings

router = APIRouter(prefix="/auth", tags=["authentication"])
auth_service = AuthService()


@router.get("/google")
async def google_auth():
    """Initiate Google OAuth flow"""
    google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    
    # Use settings instead of os.getenv
    client_id = settings.GOOGLE_CLIENT_ID
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    
    if not client_id:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")
    
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
async def google_callback(code: str, state: str = None):
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
            email=user_info.get("email", "")
        )
        
        # Generate our own JWT tokens
        access_token = auth_service.create_access_token(data={"sub": user.id, "email": user.email})
        refresh_token = auth_service.create_refresh_token(data={"sub": user.id, "email": user.email})
        
        return {
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {str(e)}")


@router.get("/me", response_model=UserResponse)
async def get_current_user(user: dict = Depends(auth_service.get_current_user)):
    """Get current authenticated user"""
    return user


@router.post("/refresh")
async def refresh_token(refresh_token: str):
    """Refresh access token using refresh token"""
    try:
        return await auth_service.refresh_access_token(refresh_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token refresh failed: {str(e)}")