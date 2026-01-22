"""
Integration tests for credential authentication endpoints.

These tests use a real test database to verify:
- Complete HTTP request/response cycles
- Database state changes
- Authentication flows
- Error handling

Endpoints tested:
- POST /api/v1/auth/signup
- POST /api/v1/auth/login
- POST /api/v1/auth/verify-email
- POST /api/v1/auth/resend-verification
- POST /api/v1/auth/forgot-password
- POST /api/v1/auth/reset-password
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base, EmailVerification, User
from app.utils.token_processor import token_processor


# =============================================================================
# Test Database Setup (Async SQLAlchemy)
# =============================================================================

SQLALCHEMY_TEST_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_db():
    """Create a fresh async in-memory database for each test."""
    engine = create_async_engine(
        SQLALCHEMY_TEST_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db):
    """Create async test client with database override."""

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# =============================================================================
# Test Data Factories (Async)
# =============================================================================


async def create_test_user(
    test_db: AsyncSession,
    email: str = "test@example.com",
    name: str = "Test User",
    password_hash: str = None,
    is_verified: bool = True,
) -> User:
    """Create a user in the test database."""
    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name=name,
        password_hash=password_hash,
        is_verified=is_verified,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


async def create_verification_token(
    test_db: AsyncSession,
    user_id: str,
    token_type: str = "email_verification",
    token: str = None,
    expires_in_hours: int = 1,
) -> str:
    """Create a verification token in the test database."""
    if token is None:
        token = f"test-token-{uuid.uuid4().hex[:8]}"

    encrypted_token = token_processor.encrypt(token)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    verification = EmailVerification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token=encrypted_token,
        token_hash=token_hash,
        token_type=token_type,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
    )
    test_db.add(verification)
    await test_db.commit()
    return token


# =============================================================================
# Tests: POST /api/v1/auth/signup
# =============================================================================


class TestSignup:
    """Integration tests for POST /api/v1/auth/signup endpoint."""

    @pytest.mark.asyncio
    @patch("app.auth.credential.service.email_service")
    async def test_signup_with_valid_data_returns_201(
        self, mock_email, client, test_db
    ):
        """New user signup creates account and returns 201."""
        mock_email.send_verification_email = AsyncMock()

        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "newuser@example.com",
                "password": "SecurePass123",
                "name": "New User",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["is_verified"] is False
        assert "message" in data

    @pytest.mark.asyncio
    @patch("app.auth.credential.service.email_service")
    async def test_signup_creates_user_in_database(self, mock_email, client, test_db):
        """Signup persists user to database with correct attributes."""
        mock_email.send_verification_email = AsyncMock()

        await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "dbuser@example.com",
                "password": "SecurePass123",
                "name": "DB User",
            },
        )

        result = await test_db.execute(
            select(User).filter_by(email="dbuser@example.com")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.name == "DB User"
        assert user.is_verified is False
        assert user.password_hash is not None
        assert user.password_hash != "SecurePass123"  # Should be hashed

    @pytest.mark.asyncio
    @patch("app.auth.credential.service.email_service")
    async def test_signup_creates_verification_token(self, mock_email, client, test_db):
        """Signup creates email verification token in database."""
        mock_email.send_verification_email = AsyncMock()

        await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "tokenuser@example.com",
                "password": "SecurePass123",
                "name": "Token User",
            },
        )

        result = await test_db.execute(
            select(User).filter_by(email="tokenuser@example.com")
        )
        user = result.scalar_one_or_none()

        result = await test_db.execute(
            select(EmailVerification).filter_by(
                user_id=user.id, token_type="email_verification"
            )
        )
        verification = result.scalar_one_or_none()

        assert verification is not None
        assert verification.verified_at is None

    @pytest.mark.asyncio
    async def test_signup_with_existing_email_returns_400(self, client, test_db):
        """Signup with existing email returns error."""
        from app.auth.credential.service import pwd_context

        await create_test_user(
            test_db,
            email="existing@example.com",
            password_hash=pwd_context.hash("ExistingPass123"),
        )

        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "existing@example.com",
                "password": "NewPass123",
                "name": "Duplicate User",
            },
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_signup_with_weak_password_returns_422(self, client, test_db):
        """Signup with weak password returns validation error."""
        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "weakpass@example.com",
                "password": "weak",  # Too short, no uppercase, no digit
                "name": "Weak Pass User",
            },
        )

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_signup_with_invalid_email_returns_422(self, client, test_db):
        """Signup with invalid email format returns validation error."""
        response = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "not-an-email",
                "password": "SecurePass123",
                "name": "Invalid Email User",
            },
        )

        assert response.status_code == 422


# =============================================================================
# Tests: POST /api/v1/auth/login
# =============================================================================


class TestLogin:
    """Integration tests for POST /api/v1/auth/login endpoint."""

    @pytest.mark.asyncio
    async def test_login_with_valid_credentials_returns_tokens(self, client, test_db):
        """Login with valid credentials returns JWT tokens."""
        from app.auth.credential.service import pwd_context

        await create_test_user(
            test_db,
            email="login@example.com",
            password_hash=pwd_context.hash("SecurePass123"),
            is_verified=True,
        )

        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "login@example.com",
                "password": "SecurePass123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["is_verified"] is True
        assert data["user"]["email"] == "login@example.com"

    @pytest.mark.asyncio
    async def test_login_with_wrong_password_returns_401(self, client, test_db):
        """Login with wrong password returns unauthorized."""
        from app.auth.credential.service import pwd_context

        await create_test_user(
            test_db,
            email="wrongpass@example.com",
            password_hash=pwd_context.hash("CorrectPass123"),
            is_verified=True,
        )

        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "wrongpass@example.com",
                "password": "WrongPass123",
            },
        )

        assert response.status_code == 401
        assert "Incorrect email or password" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_with_nonexistent_user_returns_401(self, client, test_db):
        """Login with nonexistent email returns unauthorized."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "AnyPass123",
            },
        )

        assert response.status_code == 401
        assert "Incorrect email or password" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("app.auth.credential.service.email_service")
    async def test_login_unverified_user_returns_403(self, mock_email, client, test_db):
        """Login with unverified email returns forbidden and resends verification."""
        mock_email.send_verification_email = AsyncMock()

        from app.auth.credential.service import pwd_context

        await create_test_user(
            test_db,
            email="unverified@example.com",
            password_hash=pwd_context.hash("SecurePass123"),
            is_verified=False,
        )

        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "unverified@example.com",
                "password": "SecurePass123",
            },
        )

        assert response.status_code == 403
        assert "not verified" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_oauth_user_without_password_returns_401(self, client, test_db):
        """Login for OAuth user without password returns appropriate error."""
        await create_test_user(
            test_db,
            email="oauth@example.com",
            password_hash=None,  # OAuth user has no password
            is_verified=True,
        )

        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "oauth@example.com",
                "password": "AnyPass123",
            },
        )

        assert response.status_code == 401
        assert "Google OAuth" in response.json()["detail"]


# =============================================================================
# Tests: POST /api/v1/auth/verify-email
# =============================================================================


class TestVerifyEmail:
    """Integration tests for POST /api/v1/auth/verify-email endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Email service mocking needs proper setup - template loading fails"
    )
    @patch("app.auth.credential.service.email_service")
    async def test_verify_email_with_valid_token_returns_success(
        self, mock_email, client, test_db
    ):
        """Verify email with valid token marks user as verified."""
        mock_email.send_welcome_email = AsyncMock()

        user = await create_test_user(test_db, is_verified=False)
        token = await create_verification_token(test_db, user.id)

        response = await client.post("/api/v1/auth/verify-email", json={"token": token})

        assert response.status_code == 200
        assert "verified successfully" in response.json()["message"]

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Email service mocking needs proper setup - template loading fails"
    )
    @patch("app.auth.credential.service.email_service")
    async def test_verify_email_updates_user_in_database(
        self, mock_email, client, test_db
    ):
        """Verify email updates is_verified flag in database."""
        mock_email.send_welcome_email = AsyncMock()

        user = await create_test_user(
            test_db, email="verify@example.com", is_verified=False
        )
        token = await create_verification_token(test_db, user.id)

        await client.post("/api/v1/auth/verify-email", json={"token": token})

        await test_db.refresh(user)
        assert user.is_verified is True

    @pytest.mark.asyncio
    async def test_verify_email_with_invalid_token_returns_400(self, client, test_db):
        """Verify email with invalid token returns error."""
        response = await client.post(
            "/api/v1/auth/verify-email", json={"token": "invalid-token-12345"}
        )

        assert response.status_code == 400
        assert "Invalid or expired" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_verify_email_with_expired_token_returns_400(self, client, test_db):
        """Verify email with expired token returns error."""
        user = await create_test_user(test_db, is_verified=False)
        token = await create_verification_token(
            test_db,
            user.id,
            expires_in_hours=-1,  # Already expired
        )

        response = await client.post("/api/v1/auth/verify-email", json={"token": token})

        assert response.status_code == 400


# =============================================================================
# Tests: POST /api/v1/auth/resend-verification
# =============================================================================


class TestResendVerification:
    """Integration tests for POST /api/v1/auth/resend-verification endpoint."""

    @pytest.mark.asyncio
    @patch("app.auth.credential.service.email_service")
    async def test_resend_verification_returns_success(
        self, mock_email, client, test_db
    ):
        """Resend verification email returns success message."""
        mock_email.send_verification_email = AsyncMock()

        await create_test_user(test_db, email="resend@example.com", is_verified=False)

        response = await client.post(
            "/api/v1/auth/resend-verification", json={"email": "resend@example.com"}
        )

        assert response.status_code == 200
        assert "sent" in response.json()["message"].lower()

    @pytest.mark.asyncio
    @patch("app.auth.credential.service.email_service")
    async def test_resend_verification_creates_new_token(
        self, mock_email, client, test_db
    ):
        """Resend verification creates new token in database."""
        mock_email.send_verification_email = AsyncMock()

        user = await create_test_user(
            test_db, email="newtoken@example.com", is_verified=False
        )

        await client.post(
            "/api/v1/auth/resend-verification", json={"email": "newtoken@example.com"}
        )

        result = await test_db.execute(
            select(EmailVerification).filter_by(
                user_id=user.id, token_type="email_verification"
            )
        )
        tokens = result.scalars().all()

        assert len(tokens) >= 1

    @pytest.mark.asyncio
    async def test_resend_verification_already_verified_returns_400(
        self, client, test_db
    ):
        """Resend verification for already verified user returns error."""
        await create_test_user(test_db, email="verified@example.com", is_verified=True)

        response = await client.post(
            "/api/v1/auth/resend-verification", json={"email": "verified@example.com"}
        )

        assert response.status_code == 400
        assert "already verified" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_resend_verification_nonexistent_user_returns_200(
        self, client, test_db
    ):
        """Resend verification for nonexistent email returns 200 (no info leak)."""
        response = await client.post(
            "/api/v1/auth/resend-verification",
            json={"email": "nonexistent@example.com"},
        )

        # Should return 200 to not reveal if email exists
        assert response.status_code == 200


# =============================================================================
# Tests: POST /api/v1/auth/forgot-password
# =============================================================================


class TestForgotPassword:
    """Integration tests for POST /api/v1/auth/forgot-password endpoint."""

    @pytest.mark.asyncio
    @patch("app.auth.credential.service.email_service")
    async def test_forgot_password_returns_success(self, mock_email, client, test_db):
        """Forgot password returns success message."""
        mock_email.send_password_reset_email = AsyncMock()

        await create_test_user(test_db, email="forgot@example.com")

        response = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "forgot@example.com"}
        )

        assert response.status_code == 200
        assert "reset link sent" in response.json()["message"].lower()

    @pytest.mark.asyncio
    @patch("app.auth.credential.service.email_service")
    async def test_forgot_password_creates_reset_token(
        self, mock_email, client, test_db
    ):
        """Forgot password creates reset token in database."""
        mock_email.send_password_reset_email = AsyncMock()

        user = await create_test_user(test_db, email="resettoken@example.com")

        await client.post(
            "/api/v1/auth/forgot-password", json={"email": "resettoken@example.com"}
        )

        result = await test_db.execute(
            select(EmailVerification).filter_by(
                user_id=user.id, token_type="password_reset"
            )
        )
        token = result.scalar_one_or_none()

        assert token is not None

    @pytest.mark.asyncio
    async def test_forgot_password_nonexistent_user_returns_200(self, client, test_db):
        """Forgot password for nonexistent email returns 200 (no info leak)."""
        response = await client.post(
            "/api/v1/auth/forgot-password", json={"email": "nonexistent@example.com"}
        )

        # Should return 200 to not reveal if email exists
        assert response.status_code == 200


# =============================================================================
# Tests: POST /api/v1/auth/reset-password
# =============================================================================


class TestResetPassword:
    """Integration tests for POST /api/v1/auth/reset-password endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Email service mocking needs proper setup - template loading fails"
    )
    async def test_reset_password_with_valid_token_returns_success(
        self, client, test_db
    ):
        """Reset password with valid token updates password."""
        from app.auth.credential.service import pwd_context

        user = await create_test_user(
            test_db,
            email="reset@example.com",
            password_hash=pwd_context.hash("OldPass123"),
        )
        token = await create_verification_token(
            test_db, user.id, token_type="password_reset"
        )

        response = await client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": token,
                "new_password": "NewSecurePass123",
            },
        )

        assert response.status_code == 200
        assert "reset successfully" in response.json()["message"]

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Email service mocking needs proper setup - template loading fails"
    )
    async def test_reset_password_updates_hash_in_database(self, client, test_db):
        """Reset password updates password hash in database."""
        from app.auth.credential.service import pwd_context

        user = await create_test_user(
            test_db,
            email="hashupdate@example.com",
            password_hash=pwd_context.hash("OldPass123"),
        )
        old_hash = user.password_hash
        token = await create_verification_token(
            test_db, user.id, token_type="password_reset"
        )

        await client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": token,
                "new_password": "NewSecurePass123",
            },
        )

        await test_db.refresh(user)
        assert user.password_hash != old_hash
        assert pwd_context.verify("NewSecurePass123", user.password_hash)

    @pytest.mark.asyncio
    async def test_reset_password_with_invalid_token_returns_400(self, client, test_db):
        """Reset password with invalid token returns error."""
        response = await client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": "invalid-token",
                "new_password": "NewSecurePass123",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_password_with_weak_password_returns_422(self, client, test_db):
        """Reset password with weak password returns validation error."""
        user = await create_test_user(test_db)
        token = await create_verification_token(
            test_db, user.id, token_type="password_reset"
        )

        response = await client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": token,
                "new_password": "weak",  # Too short
            },
        )

        assert response.status_code == 422
