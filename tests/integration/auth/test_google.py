"""
Integration tests for Google OAuth authentication endpoints.

These tests use a real test database to verify:
- Google OAuth login URL generation
- OAuth callback token exchange
- Token refresh
- Current user retrieval
- Logout functionality

Endpoints tested:
- GET /api/v1/auth/login
- POST /api/v1/auth/callback
- POST /api/v1/auth/refresh
- GET /api/v1/auth/me
- POST /api/v1/auth/logout
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.auth.google.service import AuthService
from app.models import RefreshToken, User

# Use shared fixtures from conftest.py
# API prefix for all routes
API_PREFIX = "/api/v1"


# =============================================================================
# Test Data Factories
# =============================================================================


async def create_test_user(
    test_db,
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


async def create_refresh_token(
    test_db,
    user_id: str,
    email: str = "test@example.com",
    expires_in_days: int = 7,
) -> str:
    """Create a refresh token in the test database."""
    from jose import jwt

    auth_service = AuthService()
    expire = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    # Generate JWT refresh token
    token = jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "exp": expire,
            "type": "refresh",
        },
        auth_service.SECRET_KEY,
        algorithm=auth_service.ALGORITHM,
    )

    # Store in database
    refresh_token = RefreshToken(
        token=token,
        user_id=user_id,
        expires_at=expire,
    )
    test_db.add(refresh_token)
    await test_db.flush()  # Make visible in current transaction without commit
    return token


def get_auth_headers(user: User) -> dict:
    """Generate auth headers for a user."""
    auth_service = AuthService()
    access_token = auth_service.create_access_token(
        data={"sub": user.id, "email": user.email}
    )
    return {"Authorization": f"Bearer {access_token}"}


# =============================================================================
# Tests: GET /api/v1/auth/login
# =============================================================================


class TestGoogleLogin:
    """Integration tests for GET /api/v1/auth/login endpoint."""

    @pytest.mark.asyncio
    async def test_login_returns_auth_url(self, client, test_db):
        """Login endpoint returns Google OAuth URL."""
        response = await client.get(
            f"{API_PREFIX}/auth/login",
            params={"redirect_uri": "http://localhost:3000/auth/callback"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "accounts.google.com" in data["auth_url"]
        assert "client_id" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_includes_redirect_uri_in_url(self, client, test_db):
        """Login URL includes the provided redirect_uri."""
        redirect_uri = "http://localhost:3000/auth/callback"
        response = await client.get(
            f"{API_PREFIX}/auth/login",
            params={"redirect_uri": redirect_uri},
        )

        assert response.status_code == 200
        data = response.json()
        assert "redirect_uri" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_with_state_parameter(self, client, test_db):
        """Login with state parameter includes it in response."""
        response = await client.get(
            f"{API_PREFIX}/auth/login",
            params={
                "redirect_uri": "http://localhost:3000/callback",
                "state": "test-csrf-state",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "test-csrf-state"
        assert "state=test-csrf-state" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_with_pkce_parameters(self, client, test_db):
        """Login with PKCE parameters includes code_challenge."""
        response = await client.get(
            f"{API_PREFIX}/auth/login",
            params={
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": "pkce-challenge-xyz",
                "code_challenge_method": "S256",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "code_challenge" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_includes_openid_scope(self, client, test_db):
        """Login URL includes openid scope for ID token."""
        response = await client.get(
            f"{API_PREFIX}/auth/login",
            params={"redirect_uri": "http://localhost:3000/callback"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "scope" in data["auth_url"]
        assert "openid" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_without_redirect_uri_returns_422(self, client, test_db):
        """Login without redirect_uri returns validation error."""
        response = await client.get(f"{API_PREFIX}/auth/login")

        assert response.status_code == 422


# =============================================================================
# Tests: POST /api/v1/auth/callback
# =============================================================================


class TestGoogleCallback:
    """Integration tests for POST /api/v1/auth/callback endpoint."""

    @pytest.mark.asyncio
    @patch("app.auth.google.service.AuthService.exchange_code_for_tokens")
    @patch("app.auth.google.service.AuthService.get_user_info_from_google")
    @patch("app.auth.google.service.AuthService.validate_id_token")
    @patch("app.email_service.service.email_service.send_welcome_email")
    async def test_callback_creates_new_user(
        self,
        mock_welcome,
        mock_validate,
        mock_user_info,
        mock_exchange,
        client,
        test_db,
    ):
        """Callback with valid code creates new user."""
        mock_exchange.return_value = {
            "access_token": "google-access-token",
            "id_token": "google-id-token",
        }
        mock_user_info.return_value = {
            "sub": "google-12345",
            "email": "newgoogle@example.com",
            "name": "New Google User",
        }
        mock_validate.return_value = {"sub": "google-12345"}
        mock_welcome.return_value = None

        response = await client.post(
            f"{API_PREFIX}/auth/callback",
            params={
                "code": "valid-auth-code",
                "redirect_uri": "http://localhost:3000/callback",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data

    @pytest.mark.asyncio
    @patch("app.auth.google.service.AuthService.exchange_code_for_tokens")
    @patch("app.auth.google.service.AuthService.get_user_info_from_google")
    async def test_callback_returns_existing_user(
        self, mock_user_info, mock_exchange, client, test_db
    ):
        """Callback for existing user returns their data."""
        existing_user = await create_test_user(
            test_db, email="existinggoogle@example.com", name="Existing User"
        )

        mock_exchange.return_value = {"access_token": "google-access-token"}
        mock_user_info.return_value = {
            "sub": "google-existing",
            "email": "existinggoogle@example.com",
            "name": "Existing User",
        }

        response = await client.post(
            f"{API_PREFIX}/auth/callback",
            params={
                "code": "valid-auth-code",
                "redirect_uri": "http://localhost:3000/callback",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user"]["id"] == existing_user.id
        assert data["user"]["email"] == "existinggoogle@example.com"

    @pytest.mark.asyncio
    @patch("app.auth.google.service.AuthService.exchange_code_for_tokens")
    @patch("app.auth.google.service.AuthService.get_user_info_from_google")
    async def test_callback_verifies_unverified_user(
        self, mock_user_info, mock_exchange, client, test_db
    ):
        """Callback verifies previously unverified user."""
        # Create unverified user (from credential signup)
        unverified_user = await create_test_user(
            test_db,
            email="unverified@example.com",
            is_verified=False,
        )

        mock_exchange.return_value = {"access_token": "google-access-token"}
        mock_user_info.return_value = {
            "sub": "google-unverified",
            "email": "unverified@example.com",
            "name": "Now Verified User",
        }

        response = await client.post(
            f"{API_PREFIX}/auth/callback",
            params={
                "code": "valid-auth-code",
                "redirect_uri": "http://localhost:3000/callback",
            },
        )

        assert response.status_code == 200

        # Verify user is now verified in database
        await test_db.refresh(unverified_user)
        assert unverified_user.is_verified is True

    @pytest.mark.asyncio
    @patch("app.auth.google.service.AuthService.exchange_code_for_tokens")
    @patch("app.auth.google.service.AuthService.get_user_info_from_google")
    @patch("app.email_service.service.email_service.send_welcome_email")
    async def test_callback_stores_refresh_token_in_database(
        self, mock_welcome, mock_user_info, mock_exchange, client, test_db
    ):
        """Callback stores refresh token in database."""
        mock_exchange.return_value = {"access_token": "google-access-token"}
        mock_user_info.return_value = {
            "sub": "google-refresh",
            "email": "refreshstore@example.com",
            "name": "Refresh Store User",
        }
        mock_welcome.return_value = None

        response = await client.post(
            f"{API_PREFIX}/auth/callback",
            params={
                "code": "valid-auth-code",
                "redirect_uri": "http://localhost:3000/callback",
            },
        )

        assert response.status_code == 200
        refresh_token = response.json()["refresh_token"]

        # Verify refresh token is in database
        result = await test_db.execute(
            select(RefreshToken).where(RefreshToken.token == refresh_token)
        )
        stored_token = result.scalar_one_or_none()
        assert stored_token is not None

    @pytest.mark.asyncio
    @patch("app.core.oauth_state.oauth_state_manager.validate_and_consume_state")
    async def test_callback_with_invalid_state_returns_403(
        self, mock_validate, client, test_db
    ):
        """Callback with invalid state returns CSRF error."""
        mock_validate.return_value = False

        response = await client.post(
            f"{API_PREFIX}/auth/callback",
            params={
                "code": "valid-auth-code",
                "redirect_uri": "http://localhost:3000/callback",
                "state": "invalid-state",
            },
        )

        assert response.status_code == 403
        assert "CSRF" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("app.auth.google.service.AuthService.exchange_code_for_tokens")
    async def test_callback_with_invalid_code_returns_400(
        self, mock_exchange, client, test_db
    ):
        """Callback with invalid code returns error."""
        mock_exchange.side_effect = Exception("Invalid authorization code")

        response = await client.post(
            f"{API_PREFIX}/auth/callback",
            params={
                "code": "invalid-code",
                "redirect_uri": "http://localhost:3000/callback",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_without_code_returns_422(self, client, test_db):
        """Callback without code returns validation error."""
        response = await client.post(
            f"{API_PREFIX}/auth/callback",
            params={"redirect_uri": "http://localhost:3000/callback"},
        )

        assert response.status_code == 422


# =============================================================================
# Tests: POST /api/v1/auth/refresh
# =============================================================================


class TestGoogleRefresh:
    """Integration tests for POST /api/v1/auth/refresh endpoint."""

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason="Async session isolation issue with SQLite - token not visible across sessions"
    )
    async def test_refresh_returns_new_access_token(self, client, test_db):
        """Valid refresh token returns new access token."""
        user = await create_test_user(test_db, email="refresh@example.com")
        refresh_token = await create_refresh_token(
            test_db, user.id, email="refresh@example.com"
        )

        response = await client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "expires_in" in data

    @pytest.mark.asyncio
    async def test_refresh_with_invalid_token_returns_401(self, client, test_db):
        """Invalid refresh token returns unauthorized."""
        response = await client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": "invalid-refresh-token"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_expired_token_returns_401(self, client, test_db):
        """Expired refresh token returns unauthorized."""
        user = await create_test_user(test_db, email="expiredrefresh@example.com")

        # Create expired refresh token
        auth_service = AuthService()
        expired_token = RefreshToken(
            token="expired-token-123",
            user_id=user.id,
            expires_at=datetime.now(timezone.utc)
            - timedelta(days=1),  # Already expired
        )
        test_db.add(expired_token)
        await test_db.commit()

        # Generate a proper JWT but use the expired DB token
        from jose import jwt

        expired_jwt = jwt.encode(
            {
                "sub": user.id,
                "email": user.email,
                "exp": datetime.now(timezone.utc)
                + timedelta(days=1),  # JWT not expired
                "type": "refresh",
            },
            auth_service.SECRET_KEY,
            algorithm=auth_service.ALGORITHM,
        )
        # But DB token is expired, so create matching one
        expired_token.token = expired_jwt
        await test_db.commit()

        response = await client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": expired_jwt},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_for_deleted_user_returns_401(self, client, test_db):
        """Refresh token for non-existent user returns unauthorized."""
        # Create token for non-existent user
        auth_service = AuthService()
        from jose import jwt

        orphan_token = jwt.encode(
            {
                "sub": "non-existent-user-id",
                "email": "deleted@example.com",
                "exp": datetime.now(timezone.utc) + timedelta(days=7),
                "type": "refresh",
            },
            auth_service.SECRET_KEY,
            algorithm=auth_service.ALGORITHM,
        )
        # Store in DB
        refresh_token = RefreshToken(
            token=orphan_token,
            user_id="non-existent-user-id",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        test_db.add(refresh_token)
        await test_db.commit()

        response = await client.post(
            f"{API_PREFIX}/auth/refresh",
            json={"refresh_token": orphan_token},
        )

        assert response.status_code == 401


# =============================================================================
# Tests: GET /api/v1/auth/me
# =============================================================================


class TestGoogleMe:
    """Integration tests for GET /api/v1/auth/me endpoint."""

    @pytest.mark.asyncio
    async def test_me_returns_current_user(self, client, test_db):
        """Authenticated request returns current user."""
        user = await create_test_user(
            test_db, email="currentme@example.com", name="Current Me User"
        )
        headers = get_auth_headers(user)

        response = await client.get(f"{API_PREFIX}/auth/me", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user.id
        assert data["email"] == "currentme@example.com"
        assert data["name"] == "Current Me User"

    @pytest.mark.asyncio
    async def test_me_without_auth_returns_403(self, client, test_db):
        """Request without authentication returns 403."""
        response = await client.get(f"{API_PREFIX}/auth/me")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_me_with_invalid_token_returns_401(self, client, test_db):
        """Request with invalid token returns 401."""
        headers = {"Authorization": "Bearer invalid-token-xyz"}

        response = await client.get(f"{API_PREFIX}/auth/me", headers=headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_expired_token_returns_401(self, client, test_db):
        """Request with expired token returns 401."""
        user = await create_test_user(test_db)
        auth_service = AuthService()
        expired_token = auth_service.create_access_token(
            data={"sub": user.id, "email": user.email},
            expires_delta=timedelta(seconds=-10),
        )
        headers = {"Authorization": f"Bearer {expired_token}"}

        response = await client.get(f"{API_PREFIX}/auth/me", headers=headers)

        assert response.status_code == 401


# =============================================================================
# Tests: POST /api/v1/auth/logout
# =============================================================================


class TestGoogleLogout:
    """Integration tests for POST /api/v1/auth/logout endpoint."""

    @pytest.mark.asyncio
    async def test_logout_returns_success(self, client, test_db):
        """Authenticated logout returns success message."""
        user = await create_test_user(test_db, email="logoutgoogle@example.com")
        headers = get_auth_headers(user)

        response = await client.post(f"{API_PREFIX}/auth/logout", headers=headers)

        assert response.status_code == 200
        assert response.json()["message"] == "Successfully logged out"

    @pytest.mark.asyncio
    async def test_logout_deletes_refresh_tokens(self, client, test_db):
        """Logout deletes all refresh tokens for the user."""
        user = await create_test_user(test_db, email="logoutdelete@example.com")

        # Create multiple refresh tokens
        for i in range(3):
            refresh_token = RefreshToken(
                token=f"google-refresh-{i}",
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            test_db.add(refresh_token)
        await test_db.commit()

        headers = get_auth_headers(user)
        await client.post(f"{API_PREFIX}/auth/logout", headers=headers)

        # Verify all refresh tokens are deleted
        result = await test_db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )
        tokens = result.scalars().all()
        assert len(tokens) == 0

    @pytest.mark.asyncio
    async def test_logout_without_auth_returns_403(self, client, test_db):
        """Logout without authentication returns 403."""
        response = await client.post(f"{API_PREFIX}/auth/logout")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_logout_does_not_affect_other_users(self, client, test_db):
        """Logout only deletes tokens for the authenticated user."""
        user1 = await create_test_user(test_db, email="googleuser1@example.com")
        user2 = await create_test_user(test_db, email="googleuser2@example.com")

        # Create refresh tokens for both
        token1 = RefreshToken(
            token="google-user1-token",
            user_id=user1.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        token2 = RefreshToken(
            token="google-user2-token",
            user_id=user2.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        test_db.add(token1)
        test_db.add(token2)
        await test_db.commit()

        # Logout user1
        headers = get_auth_headers(user1)
        await client.post(f"{API_PREFIX}/auth/logout", headers=headers)

        # Verify user2's token still exists
        result = await test_db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user2.id)
        )
        user2_tokens = result.scalars().all()
        assert len(user2_tokens) == 1
