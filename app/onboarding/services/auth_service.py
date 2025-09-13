from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import os
import json
from typing import Dict, Optional
import uuid
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

from ..models.models import User
from ..schemas.schemas import UserCreate, UserResponse

security = HTTPBearer()

class AuthService:
    def __init__(self):
        self.users_db = {}  # In-memory storage - replace with actual database
        self.refresh_tokens_db = {}  # Store refresh tokens
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        # JWT Configuration - use environment variables in production
        self.SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
        self.ALGORITHM = "HS256"
        self.ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
        self.REFRESH_TOKEN_EXPIRE_DAYS = 30    # 30 days
        
    async def exchange_google_code(self, code: str) -> dict:
        """Exchange authorization code for access token"""
        token_url = "https://oauth2.googleapis.com/token"
        
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
        
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
        # Use the OpenID Connect userinfo endpoint which includes 'sub'
        userinfo_url = "https://openidconnect.googleapis.com/v1/userinfo"
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(userinfo_url, headers=headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to get user info from Google")
            
            user_data = response.json()
            
            # Ensure required fields exist
            if 'sub' not in user_data:
                raise HTTPException(status_code=400, detail="Google user info missing 'sub' field")
            
            return user_data
    
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
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """Create JWT access token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
        return encoded_jwt
    
    def create_refresh_token(self, data: dict):
        """Create JWT refresh token"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "type": "refresh"})
        
        refresh_token = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
        
        # Store refresh token (in production, use database with expiry)
        user_id = data.get("sub")
        if user_id:
            self.refresh_tokens_db[refresh_token] = {
                "user_id": user_id,
                "expires_at": expire
            }
        
        return refresh_token
    
    def verify_token(self, token: str, token_type: str = "access") -> dict:
        """Verify JWT token and return payload"""
        try:
            payload = jwt.decode(token, self.SECRET_KEY, algorithms=[self.ALGORITHM])
            
            # Check token type
            if payload.get("type") != token_type:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token type. Expected {token_type}",
                )
            
            return payload
            
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    async def get_current_user(self, credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
        """Get current user from JWT token"""
        token = credentials.credentials
        
        # Verify the access token
        payload = self.verify_token(token, "access")
        user_id = payload.get("sub")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        
        # Get user from database
        user_data = self.users_db.get(user_id)
        if user_data is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        return user_data
    
    async def refresh_access_token(self, refresh_token: str):
        """Generate new access token using refresh token"""
        # Verify refresh token
        payload = self.verify_token(refresh_token, "refresh")
        user_id = payload.get("sub")
        
        # Check if refresh token exists and is valid
        if refresh_token not in self.refresh_tokens_db:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        
        stored_token = self.refresh_tokens_db[refresh_token]
        if stored_token["user_id"] != user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token user mismatch",
            )
        
        # Generate new access token
        user_data = self.users_db.get(user_id)
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        new_access_token = self.create_access_token(
            data={"sub": user_id, "email": user_data["email"]}
        )
        
        return {
            "access_token": new_access_token,
            "token_type": "bearer"
        }