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
from app.onboarding.services.workspace_service import WorkspaceService
from app.utils.retry_decorator import retry_external_api

from .schemas import UserResponse

logger = logging.getLogger(__name__)

security = HTTPBearer()


class AuthService:
    def __init__(self):
        # JWT Configuration
        self.SECRET_KEY = settings.JWT_SECRET_KEY
        self.ALGORITHM = settings.JWT_ALGORITHM
        self.ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
        self.REFRESH_TOKEN_EXPIRE_DAYS = settings.REFRESH_TOKEN_EXPIRE_DAYS

        # Google OAuth Configuration
        self.GOOGLE_CLIENT_ID = settings.GOOGLE_CLIENT_ID
        self.GOOGLE_CLIENT_SECRET = settings.GOOGLE_CLIENT_SECRET
        self.GOOGLE_AUTH_URL = settings.GOOGLE_AUTH_URL
        self.GOOGLE_TOKEN_URL = settings.GOOGLE_TOKEN_URL
        self.GOOGLE_USERINFO_URL = settings.GOOGLE_USERINFO_URL
        self.GOOGLE_SCOPE = "openid email profile"

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

    def get_google_auth_url(
        self,
        redirect_uri: str,
        state: str = None,
        code_challenge: str = None,
        code_challenge_method: str = "S256",
    ) -> str:
        """Generate Google OAuth authorization URL (Microsoft-style)"""
        if not self.GOOGLE_CLIENT_ID:
            raise HTTPException(status_code=500, detail="Google OAuth not configured")

        if not state:
            state = secrets.token_urlsafe(32)

        params = {
            "client_id": self.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": self.GOOGLE_SCOPE,
            "response_type": "code",
            "state": state,
            "access_type": "offline",
        }

        # Add PKCE parameters if provided
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = code_challenge_method

        return f"{self.GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code_for_tokens(
        self, code: str, redirect_uri: str, code_verifier: str = None
    ) -> Dict[str, str]:
        """Exchange authorization code for tokens"""
        if not self.GOOGLE_CLIENT_ID or not self.GOOGLE_CLIENT_SECRET:
            raise HTTPException(status_code=500, detail="Google OAuth not configured")

        data = {
            "client_id": self.GOOGLE_CLIENT_ID,
            "client_secret": self.GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

        # Add PKCE code_verifier if provided
        if code_verifier:
            data["code_verifier"] = code_verifier

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("Google"):
                with attempt:
                    response = await client.post(self.GOOGLE_TOKEN_URL, data=data)

                    # If error, log details for debugging
                    if response.status_code != 200:
                        error_detail = response.text
                        logger.error(f"Google token exchange failed: {error_detail}")
                        logger.error(
                            f"Request data: redirect_uri={data['redirect_uri']}"
                        )

                    response.raise_for_status()
                    return response.json()

    async def get_user_info_from_google(self, access_token: str) -> Dict[str, str]:
        """Get user information from Google using access token"""
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("Google"):
                with attempt:
                    response = await client.get(
                        self.GOOGLE_USERINFO_URL, headers=headers
                    )
                    response.raise_for_status()

                    user_data = response.json()

                    # Validate required fields
                    if not user_data.get("sub") or not user_data.get("email"):
                        raise HTTPException(
                            status_code=400,
                            detail="Missing required user information from Google",
                        )

                    return user_data

    async def validate_id_token(self, id_token: str) -> Dict[str, str]:
        """Validate Google ID token with signature verification using Google's public keys"""
        try:
            # Fetch Google's public keys for signature verification
            async with httpx.AsyncClient() as client:
                async for attempt in retry_external_api("Google"):
                    with attempt:
                        response = await client.get(
                            "https://www.googleapis.com/oauth2/v3/certs"
                        )
                        response.raise_for_status()
                        jwks = response.json()

            # Verify the token signature and decode payload
            # This validates signature, audience, issuer, and expiration automatically
            # Note: We skip at_hash validation since we verify user info via access token separately
            payload = jwt.decode(
                id_token,
                jwks,
                algorithms=["RS256"],
                audience=self.GOOGLE_CLIENT_ID,
                issuer=["https://accounts.google.com", "accounts.google.com"],
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iat": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_at_hash": False,  # Skip at_hash validation (we verify access token separately)
                },
            )

            return payload

        except JWTError as e:
            AUTH_METRICS["auth_failures_total"].add(1)
            raise HTTPException(status_code=400, detail=f"Invalid ID token: {str(e)}")

    async def create_or_get_user(
        self, google_user_info: Dict[str, str], db: AsyncSession
    ) -> UserResponse:
        """Create new user or return existing user, handling account linking"""
        email = google_user_info.get("email")
        name = google_user_info.get("name", "")

        # Check if user exists by email
        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            # ACCOUNT LINKING: User already exists (possibly from credential signup)
            # Set is_verified=True since Google has verified email ownership
            # This allows unverified credential users to verify via Google OAuth
            if not existing_user.is_verified:
                existing_user.is_verified = True
                await db.commit()
                await db.refresh(existing_user)
                logger.info(
                    f"Existing unverified user {existing_user.id} now verified via Google OAuth"
                )

                # Create default workspace if user doesn't have one
                try:
                    workspace_service = WorkspaceService()
                    await workspace_service.ensure_user_has_default_workspace(
                        user_id=existing_user.id,
                        user_name=existing_user.name,
                        db=db
                    )
                    await db.refresh(existing_user)
                except Exception as e:
                    logger.error(f"Failed to create default workspace for user {existing_user.id}: {str(e)}")
                    # Don't fail login if workspace creation fails
            else:
                logger.info(
                    f"Existing verified user {existing_user.id} logging in via Google OAuth"
                )
            return UserResponse.model_validate(existing_user)

        # Create new user via Google OAuth
        user_id = str(uuid.uuid4())
        new_user = User(
            id=user_id,
            name=name,
            email=email,
            password_hash=None,  # No password for Google OAuth users
            is_verified=True,  # Google OAuth users are auto-verified
        )

        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)

        # Create default workspace for new user
        try:
            workspace_service = WorkspaceService()
            await workspace_service.ensure_user_has_default_workspace(
                user_id=user_id,
                user_name=name,
                db=db
            )
            await db.refresh(new_user)
        except Exception as e:
            logger.error(f"Failed to create default workspace for user {user_id}: {str(e)}")
            # Don't fail user creation if workspace creation fails

        # Send welcome email to new user
        try:
            await email_service.send_welcome_email(user_id=user_id, db=db)
            logger.info(f"Welcome email queued for user {user_id}")
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
