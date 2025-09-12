from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import os
import json
from typing import Dict, Optional
import uuid

from ..models.models import User
from ..schemas.schemas import UserCreate, UserResponse

security = HTTPBearer()

class AuthService:
    def __init__(self):
        self.users_db = {}  # In-memory storage - replace with actual database
        
    async def exchange_google_code(self, code: str) -> dict:
        """Exchange authorization code for access token"""
        token_url = "https://oauth2.googleapis.com/token"
        
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
        
        if not client_id or not client_secret:
            raise HTTPException(status_code=500, detail="Google OAuth not configured")
        
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to exchange code for token")
            
            return response.json()
    
    async def get_google_user_info(self, access_token: str) -> dict:
        """Get user information from Google using access token"""
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(userinfo_url, headers=headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to get user info from Google")
            
            return response.json()
    
    async def create_or_get_user(self, google_id: str, name: str, email: str) -> UserResponse:
        """Create new user or return existing user"""
        # Check if user exists by email
        existing_user = None
        for user_id, user_data in self.users_db.items():
            if user_data["email"] == email:
                existing_user = user_data
                break
        
        if existing_user:
            return UserResponse(**existing_user)
        
        # Create new user
        user_id = str(uuid.uuid4())
        new_user = {
            "id": user_id,
            "name": name,
            "email": email
        }
        
        self.users_db[user_id] = new_user
        return UserResponse(**new_user)
    
    async def get_current_user(self, credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
        """Get current user from token - placeholder implementation"""
        # This is a basic implementation
        # In production, you'd verify the JWT token and extract user info
        token = credentials.credentials
        
        # For now, we'll just return a mock user
        # You should implement proper JWT verification here
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Mock user - replace with actual token verification
        return {
            "id": "mock-user-id",
            "name": "Mock User",
            "email": "mock@example.com"
        }