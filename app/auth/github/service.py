import base64
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import urlencode

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.otel_metrics import AUTH_METRICS
from app.email_service.service import email_service
from app.models import RefreshToken, User
from app.utils.retry_decorator import retry_external_api

from .schemas import UserResponse

logger = logging.getLogger(__name__)

security = HTTPBearer()


class GitHubAuthService:
    def __init__(self):
        # JWT Configuration
        self.SECRET_KEY = settings.JWT_SECRET_KEY
        self.ALGORITHM = settings.JWT_ALGORITHM
        self.ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
        self.REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

        # GitHub OAuth Configuration
        self.GITHUB_CLIENT_ID = settings.GITHUB_OAUTH_CLIENT_ID
        self.GITHUB_CLIENT_SECRET = settings.GITHUB_OAUTH_CLIENT_SECRET
        self.GITHUB_AUTH_URL = settings.GITHUB_OAUTH_AUTH_URL
        self.GITHUB_TOKEN_URL = settings.GITHUB_OAUTH_TOKEN_URL
        self.GITHUB_USER_URL = settings.GITHUB_OAUTH_USER_URL
        self.GITHUB_USER_EMAIL_URL = settings.GITHUB_OAUTH_USER_EMAIL_URL
        self.GITHUB_SCOPE = "read:user user:email"

    def generate_pkce_pair(self) -> tuple[str, str]:
        """Generate PKCE code_verifier and code_challenge for secure OAuth flow"""
        code_verifier = (
            base64.urlsafe_b64encode(secrets.token_bytes(32))
            .decode("utf-8")
            .rstrip("=")
        )
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            )
            .decode("utf-8")
            .rstrip("=")
        )
        return code_verifier, code_challenge

    def get_github_auth_url(
        self,
        redirect_uri: str,
        state: str = None,
        code_challenge: str = None,
        code_challenge_method: str = "S256",
    ) -> str:
        """Generate GitHub OAuth authorization URL with optional PKCE support"""
        if not self.GITHUB_CLIENT_ID:
            raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

        if not state:
            state = secrets.token_urlsafe(32)

        params = {
            "client_id": self.GITHUB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": self.GITHUB_SCOPE,
            "state": state,
            "allow_signup": "true",
        }

        # Add PKCE parameters if provided
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method

        return f"{self.GITHUB_AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(
        self, code: str, redirect_uri: str, code_verifier: str = None
    ) -> Dict[str, str]:
        """Exchange authorization code for tokens with optional PKCE support"""
        if not self.GITHUB_CLIENT_ID or not self.GITHUB_CLIENT_SECRET:
            raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

        data = {
            "client_id": self.GITHUB_CLIENT_ID,
            "client_secret": self.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        # Add PKCE code_verifier if provided
        if code_verifier:
            data["code_verifier"] = code_verifier

        headers = {
            "Accept": "application/json",
        }

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.post(
                        self.GITHUB_TOKEN_URL, data=data, headers=headers
                    )

                    # If error, log details for debugging
                    if response.status_code != 200:
                        error_detail = response.text
                        logger.error(f"GitHub token exchange failed: {error_detail}")
                        logger.error(
                            f"Request data: redirect_uri={data['redirect_uri']}"
                        )

                    response.raise_for_status()
                    token_data = response.json()

                    # Check for error in response
                    if "error" in token_data:
                        raise HTTPException(
                            status_code=400,
                            detail=f"GitHub OAuth error: {token_data.get('error_description', token_data['error'])}",
                        )

                    return token_data

    async def get_user_info_from_github(self, access_token: str) -> Dict[str, str]:
        """Get user information from GitHub using access token"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        async with httpx.AsyncClient() as client:
            # Get user profile
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    user_response = await client.get(
                        self.GITHUB_USER_URL, headers=headers
                    )
                    user_response.raise_for_status()
                    user_data = user_response.json()

            # Get user emails
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    email_response = await client.get(
                        self.GITHUB_USER_EMAIL_URL, headers=headers
                    )
                    email_response.raise_for_status()
                    emails_data = email_response.json()

            # Find primary verified email
            primary_email = None
            for email_obj in emails_data:
                if email_obj.get("primary") and email_obj.get("verified"):
                    primary_email = email_obj.get("email")
                    break

            # If no primary verified email, try to find any verified email
            if not primary_email:
                for email_obj in emails_data:
                    if email_obj.get("verified"):
                        primary_email = email_obj.get("email")
                        break

            # If still no email, check if public email is available
            if not primary_email and user_data.get("email"):
                primary_email = user_data.get("email")

            if not primary_email:
                raise HTTPException(
                    status_code=400,
                    detail="No verified email found in GitHub account. Please add and verify an email address.",
                )

            # Validate required fields
            if not user_data.get("id"):
                raise HTTPException(
                    status_code=400,
                    detail="Missing required user information from GitHub",
                )

            # Return user data with email
            return {
                "id": str(user_data.get("id")),
                "email": primary_email,
                "name": user_data.get("name") or user_data.get("login"),
                "login": user_data.get("login"),
            }

    async def create_or_get_user(
        self, github_user_info: Dict[str, str], db: AsyncSession
    ) -> UserResponse:
        """Create new user or return existing user, handling account linking"""
        email = github_user_info.get("email")
        name = github_user_info.get("name", "")

        # Check if user exists by email
        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            # ACCOUNT LINKING: User already exists (possibly from credential signup or Google OAuth)
            # Set is_verified=True since GitHub has verified email ownership
            # This allows unverified credential users to verify via GitHub OAuth
            if not existing_user.is_verified:
                existing_user.is_verified = True
                await db.commit()
                await db.refresh(existing_user)
                logger.info(
                    f"Existing unverified user now verified via GitHub OAuth: {email}"
                )
            else:
                logger.info(
                    f"Existing verified user logging in via GitHub OAuth: {email}"
                )
            return UserResponse.model_validate(existing_user)

        # Create new user via GitHub OAuth
        user_id = str(uuid.uuid4())
        new_user = User(
            id=user_id,
            name=name,
            email=email,
            password_hash=None,  # No password for GitHub OAuth users
            is_verified=True,  # GitHub OAuth users are auto-verified
        )

        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)

        # Send welcome email to new user
        try:
            await email_service.send_welcome_email(user_id=user_id, db=db)
            logger.info(f"Welcome email queued for user {user_id} ({email})")
        except Exception as e:
            # Log the error but don't fail user creation
            logger.error(f"Failed to send welcome email to user {user_id}: {str(e)}")

        return UserResponse.model_validate(new_user)

    def create_access_token(
        self, data: Dict[str, str], expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create JWT access token"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES
            )

        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
        return encoded_jwt

    async def create_refresh_token(self, data: Dict[str, str], db: AsyncSession) -> str:
        """Create JWT refresh token and store in database"""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + timedelta(
            days=self.REFRESH_TOKEN_EXPIRE_DAYS
        )
        to_encode.update({"exp": expire, "type": "refresh"})

        refresh_token = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)

        # Store refresh token in database
        user_id = data.get("sub")
        if user_id:
            refresh_token_obj = RefreshToken(
                token=refresh_token, user_id=user_id, expires_at=expire
            )
            db.add(refresh_token_obj)
            await db.commit()

        return refresh_token

    def verify_token(self, token: str, token_type: str = "access") -> Dict[str, str]:
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

        except JWTError as e:
            error_str = str(e).lower()
            if "expired" in error_str:
                AUTH_METRICS["jwt_tokens_expired_total"].add(
                    1,
                    {
                        "token_type": token_type,
                    },
                )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def get_current_user(
        self,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: AsyncSession = Depends(get_db),
    ) -> User:
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

    async def refresh_access_token(
        self, refresh_token_str: str, db: AsyncSession
    ) -> Dict[str, str]:
        """Generate new access token using refresh token"""
        # Verify refresh token
        payload = self.verify_token(refresh_token_str, "refresh")
        user_id = payload.get("sub")

        # Check if refresh token exists and is valid in database
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token == refresh_token_str)
        )
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
            AUTH_METRICS["jwt_tokens_expired_total"].add(
                1,
                {
                    "token_type": "refresh",
                },
            )

            # Remove expired token
            await db.delete(stored_token)
            await db.commit()
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

        # Calculate expiration time
        expire_time = datetime.now(timezone.utc) + timedelta(
            minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES
        )

        return {
            "access_token": new_access_token,
            "token_type": "bearer",
            "expires_at": expire_time.isoformat(),
            "expires_in": self.ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # seconds
        }
