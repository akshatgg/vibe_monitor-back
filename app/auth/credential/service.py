import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from fastapi import HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.otel_metrics import AUTH_METRICS
from app.email_service.service import email_service
from app.models import EmailVerification, RefreshToken, User
from app.workspace.services.workspace_service import WorkspaceService
from app.utils.token_processor import token_processor

logger = logging.getLogger(__name__)

# Password hashing configuration using Argon2id (recommended over bcrypt)
# Falls back to bcrypt if Argon2 is not available
try:
    pwd_context = CryptContext(
        schemes=["argon2"],
        deprecated="auto",
    )
except Exception:
    logger.warning("Argon2 not available, falling back to bcrypt")
    pwd_context = CryptContext(
        schemes=["bcrypt"],
        deprecated="auto",
        bcrypt__rounds=12,
    )


class CredentialAuthService:
    """Service for credential-based authentication (email + password)"""

    # Token expiry configurations
    EMAIL_VERIFICATION_EXPIRY_HOURS = 1
    PASSWORD_RESET_EXPIRY_HOURS = 1

    def __init__(self, jwt_service):
        """
        Initialize with JWT service for token generation.

        Args:
            jwt_service: Instance of AuthService for JWT operations
        """
        self.jwt_service = jwt_service

    # ============== PASSWORD OPERATIONS ==============

    def hash_password(self, password: str) -> str:
        """Hash a password using Argon2id or bcrypt"""
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return pwd_context.verify(plain_password, hashed_password)

    # ============== TOKEN OPERATIONS ==============

    async def create_verification_token(
        self, user_id: str, token_type: str, db: AsyncSession
    ) -> str:
        """
        Create a secure verification token for email verification or password reset.

        Args:
            user_id: User ID to create token for
            token_type: 'email_verification' or 'password_reset'
            db: Database session

        Returns:
            Secure token string (plain text - to be sent in email)
        """
        # Generate cryptographically secure token
        token = secrets.token_urlsafe(32)

        # Determine expiry based on token type
        if token_type == "email_verification":
            expiry_hours = self.EMAIL_VERIFICATION_EXPIRY_HOURS
        else:  # password_reset
            expiry_hours = self.PASSWORD_RESET_EXPIRY_HOURS

        expires_at = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)

        # Encrypt token before storing in database (security best practice)
        encrypted_token = token_processor.encrypt(token)

        # Calculate SHA-256 hash for O(1) lookup performance
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Store ENCRYPTED token AND hash in database
        verification = EmailVerification(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token=encrypted_token,  # Encrypted for security
            token_hash=token_hash,  # Hash for fast lookup
            token_type=token_type,
            expires_at=expires_at,
        )

        db.add(verification)
        await db.commit()

        # Return plain token to be sent in email
        return token

    async def verify_token(
        self, token: str, token_type: str, db: AsyncSession
    ) -> Optional[str]:
        """
        Verify a token and return user_id if valid.

        Uses SHA-256 hash for O(1) lookup performance (optimized from O(n)).

        Args:
            token: Token string to verify (plain text from email)
            token_type: Expected token type
            db: Database session

        Returns:
            User ID if token is valid, None otherwise
        """
        # Calculate hash of provided token for fast lookup
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Direct database lookup by hash (O(1) instead of O(n))
        result = await db.execute(
            select(EmailVerification).where(
                EmailVerification.token_hash == token_hash,  # Fast indexed lookup
                EmailVerification.token_type == token_type,
                EmailVerification.verified_at.is_(None),  # Not already used
                EmailVerification.expires_at
                > datetime.now(timezone.utc),  # Not expired
            )
        )
        verification = result.scalar_one_or_none()

        # Verify by decrypting (only 1 token, not thousands)
        if verification:
            if verification.expires_at <= datetime.now(timezone.utc):
                AUTH_METRICS["jwt_tokens_expired_total"].add(
                    1, {"token_type": token_type}
                )
                raise HTTPException(status_code=400, detail="Token has expired")

            try:
                decrypted_token = token_processor.decrypt(verification.token)
                if decrypted_token == token:
                    return verification.user_id
            except Exception:
                # If decryption fails, token is invalid
                pass

        return None

    async def mark_token_verified(self, token: str, db: AsyncSession) -> None:
        """
        Mark a token as verified (used).

        Uses SHA-256 hash for O(1) lookup performance (optimized from O(n)).

        Args:
            token: Plain text token to mark as verified
            db: Database session
        """
        # Calculate hash of provided token for fast lookup
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Direct database lookup by hash (O(1) instead of O(n))
        result = await db.execute(
            select(EmailVerification).where(
                EmailVerification.token_hash == token_hash,
                EmailVerification.verified_at.is_(None),
            )
        )
        verification = result.scalar_one_or_none()

        # Mark as verified if found
        if verification:
            try:
                # Verify the decrypted token matches (extra security check)
                decrypted_token = token_processor.decrypt(verification.token)
                if decrypted_token == token:
                    verification.verified_at = datetime.now(timezone.utc)
                    await db.commit()
            except Exception:
                # If decryption fails, don't mark as verified
                pass

    async def invalidate_user_tokens(
        self, user_id: str, token_type: str, db: AsyncSession
    ) -> None:
        """Delete all unused tokens of a specific type for a user"""
        await db.execute(
            delete(EmailVerification).where(
                EmailVerification.user_id == user_id,
                EmailVerification.token_type == token_type,
                EmailVerification.verified_at.is_(None),
            )
        )
        await db.commit()

    # ============== USER OPERATIONS ==============

    async def check_email(self, email: str, db: AsyncSession) -> Dict[str, any]:
        """
        Check if email exists and determine available auth methods.

        Args:
            email: Email address to check
            db: Database session

        Returns:
            Dict with:
            - exists: bool - whether user exists
            - auth_methods: List[str] - available auth methods
            - has_password: bool - whether user has password set
            - name: Optional[str] - user's name if exists
        """
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            return {
                "exists": False,
                "auth_methods": [],
                "has_password": False,
                "name": None,
            }

        # Determine auth methods
        auth_methods = []
        has_password = user.password_hash is not None

        if has_password:
            auth_methods.append("password")

        # If user has no password, they must have signed up via OAuth
        # We can't distinguish Google vs GitHub from password_hash alone
        # For now, assume OAuth users without password used Google (most common)
        if not has_password:
            auth_methods.append("google")

        return {
            "exists": True,
            "auth_methods": auth_methods,
            "has_password": has_password,
            "name": user.name,
        }

    async def signup(
        self, email: str, password: str, name: str, db: AsyncSession
    ) -> Tuple[Dict[str, any], User]:
        """
        Create a new user with email and password.

        Args:
            email: User email
            password: Plain text password
            name: User name
            db: Database session

        Returns:
            Tuple of (JWT tokens dict, User object)
        """
        # Check if user already exists
        result = await db.execute(select(User).where(User.email == email))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            # If user exists but has no password (Google OAuth user)
            if existing_user.password_hash is None:
                AUTH_METRICS["auth_failures_total"].add(1)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This email is already registered via Google OAuth. To add password login, use 'Forgot Password' to set a password, or continue logging in with Google.",
                )
            else:
                # User already has a password-based account
                AUTH_METRICS["auth_failures_total"].add(1)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User with this email already exists. Please login instead.",
                )

        # Validate password strength (basic check)
        if len(password) < 8:
            AUTH_METRICS["auth_failures_total"].add(1)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long and contain: one lowercase letter, one uppercase letter, and one digit",
            )

        # Create user
        user_id = str(uuid.uuid4())
        hashed_password = self.hash_password(password)

        new_user = User(
            id=user_id,
            email=email,
            name=name,
            password_hash=hashed_password,
            is_verified=False,
        )

        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)

        # Generate verification token and send email
        try:
            verification_token = await self.create_verification_token(
                user_id=user_id, token_type="email_verification", db=db
            )

            # Send verification email
            verification_url = (
                f"{settings.WEB_APP_URL}/auth/verify-email?token={verification_token}"
            )
            await email_service.send_verification_email(
                user_id=user_id, verification_url=verification_url, db=db
            )
            logger.info(f"Verification email sent to user {user_id}")
        except Exception as e:
            logger.error(
                f"Failed to send verification email to user {user_id}: {str(e)}"
            )
            # Don't fail signup if email fails

        # Don't generate tokens for unverified users
        # User must verify email before they can log in
        # This ensures consistent behavior between signup and login
        return {
            "message": "Account created successfully. Please check your email to verify your account before logging in.",
            "email": email,
            "is_verified": False,
        }, new_user

    async def login(
        self, email: str, password: str, db: AsyncSession
    ) -> Dict[str, any]:
        """
        Authenticate user with email and password.

        Args:
            email: User email
            password: Plain text password
            db: Database session

        Returns:
            JWT tokens and user info
        """
        # Find user by email
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            AUTH_METRICS["auth_failures_total"].add(1)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )

        # Check if user has password (credential-based auth)
        if not user.password_hash:
            AUTH_METRICS["auth_failures_total"].add(1)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Please use Google OAuth to login",
            )

        # Verify password
        if not self.verify_password(password, user.password_hash):
            AUTH_METRICS["auth_failures_total"].add(1)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )

        # Enforce email verification for credential-based auth
        # (Google OAuth users are automatically verified by Google)
        if not user.is_verified:
            # Automatically resend verification email for better UX
            try:
                # Invalidate old tokens
                await self.invalidate_user_tokens(user.id, "email_verification", db)

                # Generate new verification token
                verification_token = await self.create_verification_token(
                    user_id=user.id, token_type="email_verification", db=db
                )

                # Send verification email
                verification_url = f"{settings.WEB_APP_URL}/auth/verify-email?token={verification_token}"
                await email_service.send_verification_email(
                    user_id=user.id, verification_url=verification_url, db=db
                )

                logger.info(
                    f"Verification email automatically resent to user {user.id} during login attempt"
                )

                AUTH_METRICS["auth_failures_total"].add(1)

                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your email is not verified. We've sent you a new verification email. Please check your inbox and verify your account before logging in.",
                )
            except HTTPException:
                # Re-raise our custom HTTP exception
                raise
            except Exception as e:
                # If email sending fails, still inform user about verification requirement
                logger.error(
                    f"Failed to resend verification email during login: {str(e)}"
                )

                AUTH_METRICS["auth_failures_total"].add(1)

                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Please verify your email address before logging in. If you didn't receive a verification email, please use the 'Resend Verification' option.",
                )

        # Generate JWT tokens
        access_token = self.jwt_service.create_access_token(
            data={"sub": user.id, "email": user.email}
        )
        refresh_token = await self.jwt_service.create_refresh_token(
            data={"sub": user.id, "email": user.email}, db=db
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "is_verified": user.is_verified,
            "last_visited_workspace_id": user.last_visited_workspace_id,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "is_verified": user.is_verified,
            },
        }

    async def verify_email(self, token: str, db: AsyncSession) -> Dict[str, str]:
        """
        Verify user email with token.

        Args:
            token: Verification token
            db: Database session

        Returns:
            Success message
        """
        user_id = await self.verify_token(token, "email_verification", db)

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token",
            )

        # Update user
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        user.is_verified = True
        await self.mark_token_verified(token, db)
        await db.commit()

        logger.info(f"Email verified for user {user_id}")

        # Create default workspace for newly verified user if they don't have one
        try:
            workspace_service = WorkspaceService()
            await workspace_service.ensure_user_has_default_workspace(
                user_id=user_id,
                user_name=user.name,
                db=db
            )
        except Exception as e:
            logger.error(f"Failed to create default workspace for user {user_id}: {str(e)}")
            # Don't fail verification if workspace creation fails

        # Send welcome email after successful verification
        try:
            await email_service.send_welcome_email(user_id=user_id, db=db)
            logger.info(f"Welcome email sent to user {user_id} ({user.email})")
        except Exception as e:
            # Log the error but don't fail verification
            logger.error(f"Failed to send welcome email to user {user_id}: {str(e)}")

        return {"message": "Email verified successfully", "email": user.email}

    async def resend_verification_email(
        self, email: str, db: AsyncSession
    ) -> Dict[str, str]:
        """
        Resend verification email to user.

        Args:
            email: User email
            db: Database session

        Returns:
            Success message
        """
        # Find user
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            # Don't reveal if user exists
            return {
                "message": "If this email is registered, a verification email will be sent"
            }

        if user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already verified",
            )

        # Invalidate old tokens
        await self.invalidate_user_tokens(user.id, "email_verification", db)

        # Generate new token
        verification_token = await self.create_verification_token(
            user_id=user.id, token_type="email_verification", db=db
        )

        # Send email
        verification_url = (
            f"{settings.WEB_APP_URL}/auth/verify-email?token={verification_token}"
        )
        await email_service.send_verification_email(
            user_id=user.id, verification_url=verification_url, db=db
        )

        logger.info(f"Verification email resent to user {user.id}")

        return {"message": "Verification email sent"}

    async def forgot_password(self, email: str, db: AsyncSession) -> Dict[str, str]:
        """
        Send password reset email to user.

        This works for both credential users (to reset password) and
        Google OAuth users (to set their first password).

        Args:
            email: User email
            db: Database session

        Returns:
            Success message
        """
        # Find user
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        # Don't reveal if user exists (security best practice)
        if not user:
            return {
                "message": "If this email is registered, a password reset link will be sent"
            }

        # Invalidate old tokens
        await self.invalidate_user_tokens(user.id, "password_reset", db)

        # Generate reset token
        reset_token = await self.create_verification_token(
            user_id=user.id, token_type="password_reset", db=db
        )

        # Send email
        reset_url = f"{settings.WEB_APP_URL}/auth/reset-password?token={reset_token}"
        await email_service.send_password_reset_email(
            user_id=user.id, reset_url=reset_url, db=db
        )

        logger.info(f"Password reset email sent to user {user.id}")

        return {"message": "Password reset link sent to your email"}

    async def reset_password(
        self, token: str, new_password: str, db: AsyncSession
    ) -> Dict[str, str]:
        """
        Reset user password with token.

        Args:
            token: Reset token
            new_password: New password
            db: Database session

        Returns:
            Success message
        """
        user_id = await self.verify_token(token, "password_reset", db)

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            )

        # Validate new password
        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long and contain: one lowercase letter, one uppercase letter, and one digit",
            )

        # Update user password
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        user.password_hash = self.hash_password(new_password)
        await self.mark_token_verified(token, db)

        # Invalidate all refresh tokens for security
        await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))

        await db.commit()

        logger.info(f"Password reset for user {user_id}")

        return {"message": "Password reset successfully"}
