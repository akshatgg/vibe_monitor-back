from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
import os
import json
from typing import Dict, Optional
import uuid
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext

from ..models.models import User, RefreshToken
from ..schemas.schemas import UserCreate, UserResponse
from ...core.database import get_db
from ...core.config import settings

security = HTTPBearer()

class AuthService:
    def __init__(self):
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        # JWT Configuration from settings
        self.SECRET_KEY = settings.JWT_SECRET_KEY
        self.ALGORITHM = settings.JWT_ALGORITHM
        self.ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
        self.REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS
        
    async def exchange_google_code(self, code: str) -> dict:
        """Exchange authorization code for access token"""
        token_url = "https://oauth2.googleapis.com/token"
        
        client_id = settings.GOOGLE_CLIENT_ID
        client_secret = settings.GOOGLE_CLIENT_SECRET
        redirect_uri = settings.GOOGLE_REDIRECT_URI or "http://localhost:8000/api/v1/auth/google/callback"
        
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
    
    async def create_or_get_user(self, google_id: str, name: str, email: str, db: AsyncSession) -> UserResponse:
        """Create new user or return existing user"""
        # Check if user exists by email
        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            return UserResponse.model_validate(existing_user)
        
        # Create new user
        user_id = str(uuid.uuid4())
        new_user = User(
            id=user_id,
            name=name,
            email=email
        )
        
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        
        # Create personal workspace for new user
        from .workspace_service import WorkspaceService
        workspace_service = WorkspaceService()
        await workspace_service.create_personal_workspace(
            user=new_user,
            db=db
        )
        
        return UserResponse.model_validate(new_user)
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """Create JWT access token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
        return encoded_jwt
    
    async def create_refresh_token(self, data: dict, db: AsyncSession):
        """Create JWT refresh token"""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "type": "refresh"})
        
        refresh_token = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
        
        # Store refresh token in database
        user_id = data.get("sub")
        if user_id:
            refresh_token_obj = RefreshToken(
                token=refresh_token,
                user_id=user_id,
                expires_at=expire
            )
            db.add(refresh_token_obj)
            await db.commit()
        
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
    
    async def get_current_user(self, credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)) -> User:
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
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        return user
    
    async def refresh_access_token(self, refresh_token_str: str, db: AsyncSession):
        """Generate new access token using refresh token"""
        # Verify refresh token
        payload = self.verify_token(refresh_token_str, "refresh")
        user_id = payload.get("sub")
        
        # Check if refresh token exists and is valid in database
        result = await db.execute(select(RefreshToken).where(RefreshToken.token == refresh_token_str))
        stored_token = result.scalar_one_or_none()
        
        if not stored_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        
        if stored_token.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token user mismatch",
            )
        
        # Check if token has expired
        if stored_token.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has expired",
            )
        
        # Get user from database
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        new_access_token = self.create_access_token(
            data={"sub": user_id, "email": user.email}
        )
        
        return {
            "access_token": new_access_token,
            "token_type": "bearer"
        }