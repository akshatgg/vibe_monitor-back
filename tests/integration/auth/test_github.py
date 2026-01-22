"""
Integration tests for GitHub OAuth authentication endpoints.

These tests use a real test database to verify:
- GitHub OAuth login URL generation
- OAuth callback token exchange
- Current user retrieval
- Logout functionality

Endpoints tested:
- GET /api/v1/auth/github/login
- POST /api/v1/auth/github/callback
- GET /api/v1/auth/github/me
- POST /api/v1/auth/github/logout
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.auth.github.service import GitHubAuthService
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


def get_auth_headers(user: User) -> dict:
    """Generate auth headers for a user."""
    github_auth_service = GitHubAuthService()
    access_token = github_auth_service.create_access_token(
        data={"sub": user.id, "email": user.email}
    )
    return {"Authorization": f"Bearer {access_token}"}


# =============================================================================
# Tests: GET /api/v1/auth/github/login
# =============================================================================


class TestGitHubLogin:
    """Integration tests for GET /api/v1/auth/github/login endpoint."""

    @pytest.mark.asyncio
    async def test_login_returns_auth_url(self, client, test_db):
        """Login endpoint returns GitHub OAuth URL."""
        response = await client.get(
            f"{API_PREFIX}/auth/github/login",
            params={"redirect_uri": "http://localhost:3000/auth/github/callback"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "github.com" in data["auth_url"]
        assert "client_id" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_includes_redirect_uri_in_url(self, client, test_db):
        """Login URL includes the provided redirect_uri."""
        redirect_uri = "http://localhost:3000/auth/github/callback"
        response = await client.get(
            f"{API_PREFIX}/auth/github/login",
            params={"redirect_uri": redirect_uri},
        )

        assert response.status_code == 200
        data = response.json()
        # URL-encoded redirect_uri should be in auth_url
        assert "redirect_uri" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_with_state_parameter(self, client, test_db):
        """Login with state parameter includes it in response."""
        response = await client.get(
            f"{API_PREFIX}/auth/github/login",
            params={
                "redirect_uri": "http://localhost:3000/callback",
                "state": "test-state-123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "test-state-123"
        assert "state=test-state-123" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_with_pkce_parameters(self, client, test_db):
        """Login with PKCE parameters includes code_challenge."""
        response = await client.get(
            f"{API_PREFIX}/auth/github/login",
            params={
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": "test-challenge-abc123",
                "code_challenge_method": "S256",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "code_challenge" in data["auth_url"]

    @pytest.mark.asyncio
    async def test_login_without_redirect_uri_returns_422(self, client, test_db):
        """Login without redirect_uri returns validation error."""
        response = await client.get(f"{API_PREFIX}/auth/github/login")

        assert response.status_code == 422


# =============================================================================
# Tests: POST /api/v1/auth/github/callback
# =============================================================================


class TestGitHubCallback:
    """Integration tests for POST /api/v1/auth/github/callback endpoint."""

    @pytest.mark.asyncio
    @patch("app.auth.github.service.GitHubAuthService.exchange_code_for_tokens")
    @patch("app.auth.github.service.GitHubAuthService.get_user_info_from_github")
    @patch("app.email_service.service.email_service.send_welcome_email")
    async def test_callback_creates_new_user(
        self, mock_welcome, mock_user_info, mock_exchange, client, test_db
    ):
        """Callback with valid code creates new user."""
        mock_exchange.return_value = {"access_token": "github-access-token"}
        mock_user_info.return_value = {
            "id": "12345",
            "login": "testuser",
            "name": "Test GitHub User",
            "email": "github@example.com",
        }
        mock_welcome.return_value = None

        response = await client.post(
            f"{API_PREFIX}/auth/github/callback",
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

    @pytest.mark.asyncio
    @patch("app.auth.github.service.GitHubAuthService.exchange_code_for_tokens")
    @patch("app.auth.github.service.GitHubAuthService.get_user_info_from_github")
    async def test_callback_returns_existing_user(
        self, mock_user_info, mock_exchange, client, test_db
    ):
        """Callback for existing user returns their data."""
        # Create existing user
        await create_test_user(
            test_db, email="existing@example.com", name="Existing User"
        )

        mock_exchange.return_value = {"access_token": "github-access-token"}
        mock_user_info.return_value = {
            "id": "12345",
            "login": "existinguser",
            "name": "Existing User",
            "email": "existing@example.com",
        }

        response = await client.post(
            f"{API_PREFIX}/auth/github/callback",
            params={
                "code": "valid-auth-code",
                "redirect_uri": "http://localhost:3000/callback",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == "existing@example.com"

    @pytest.mark.asyncio
    @patch("app.auth.github.service.GitHubAuthService.exchange_code_for_tokens")
    @patch("app.auth.github.service.GitHubAuthService.get_user_info_from_github")
    @patch("app.email_service.service.email_service.send_welcome_email")
    async def test_callback_stores_refresh_token_in_database(
        self, mock_welcome, mock_user_info, mock_exchange, client, test_db
    ):
        """Callback stores refresh token in database."""
        mock_exchange.return_value = {"access_token": "github-access-token"}
        mock_user_info.return_value = {
            "id": "67890",
            "login": "refreshuser",
            "name": "Refresh User",
            "email": "refresh@example.com",
        }
        mock_welcome.return_value = None

        response = await client.post(
            f"{API_PREFIX}/auth/github/callback",
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
            f"{API_PREFIX}/auth/github/callback",
            params={
                "code": "valid-auth-code",
                "redirect_uri": "http://localhost:3000/callback",
                "state": "invalid-state",
            },
        )

        assert response.status_code == 403
        assert "CSRF" in response.json()["detail"]

    @pytest.mark.asyncio
    @patch("app.auth.github.service.GitHubAuthService.exchange_code_for_tokens")
    async def test_callback_with_invalid_code_returns_400(
        self, mock_exchange, client, test_db
    ):
        """Callback with invalid code returns error."""
        mock_exchange.side_effect = Exception("Invalid authorization code")

        response = await client.post(
            f"{API_PREFIX}/auth/github/callback",
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
            f"{API_PREFIX}/auth/github/callback",
            params={"redirect_uri": "http://localhost:3000/callback"},
        )

        assert response.status_code == 422


# =============================================================================
# Tests: GET /api/v1/auth/github/me
# =============================================================================


class TestGitHubMe:
    """Integration tests for GET /api/v1/auth/github/me endpoint."""

    @pytest.mark.asyncio
    async def test_me_returns_current_user(self, client, test_db):
        """Authenticated request returns current user."""
        user = await create_test_user(
            test_db, email="me@example.com", name="Current User"
        )
        headers = get_auth_headers(user)

        response = await client.get(f"{API_PREFIX}/auth/github/me", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user.id
        assert data["email"] == "me@example.com"
        assert data["name"] == "Current User"

    @pytest.mark.asyncio
    async def test_me_without_auth_returns_403(self, client, test_db):
        """Request without authentication returns 403."""
        response = await client.get(f"{API_PREFIX}/auth/github/me")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_me_with_invalid_token_returns_401(self, client, test_db):
        """Request with invalid token returns 401."""
        headers = {"Authorization": "Bearer invalid-token"}

        response = await client.get(f"{API_PREFIX}/auth/github/me", headers=headers)

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_expired_token_returns_401(self, client, test_db):
        """Request with expired token returns 401."""
        user = await create_test_user(test_db)
        github_auth_service = GitHubAuthService()
        # Create expired token
        expired_token = github_auth_service.create_access_token(
            data={"sub": user.id, "email": user.email},
            expires_delta=timedelta(seconds=-10),  # Already expired
        )
        headers = {"Authorization": f"Bearer {expired_token}"}

        response = await client.get(f"{API_PREFIX}/auth/github/me", headers=headers)

        assert response.status_code == 401


# =============================================================================
# Tests: POST /api/v1/auth/github/logout
# =============================================================================


class TestGitHubLogout:
    """Integration tests for POST /api/v1/auth/github/logout endpoint."""

    @pytest.mark.asyncio
    async def test_logout_returns_success(self, client, test_db):
        """Authenticated logout returns success message."""
        user = await create_test_user(test_db, email="logout@example.com")
        headers = get_auth_headers(user)

        response = await client.post(
            f"{API_PREFIX}/auth/github/logout", headers=headers
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Successfully logged out"

    @pytest.mark.asyncio
    async def test_logout_deletes_refresh_tokens(self, client, test_db):
        """Logout deletes all refresh tokens for the user."""
        user = await create_test_user(test_db, email="logoutrefresh@example.com")

        # Create refresh tokens
        for i in range(3):
            refresh_token = RefreshToken(
                token=f"refresh-token-{i}",
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            )
            test_db.add(refresh_token)
        await test_db.commit()

        headers = get_auth_headers(user)
        await client.post(f"{API_PREFIX}/auth/github/logout", headers=headers)

        # Verify all refresh tokens are deleted
        result = await test_db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user.id)
        )
        tokens = result.scalars().all()
        assert len(tokens) == 0

    @pytest.mark.asyncio
    async def test_logout_without_auth_returns_403(self, client, test_db):
        """Logout without authentication returns 403."""
        response = await client.post(f"{API_PREFIX}/auth/github/logout")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_logout_does_not_affect_other_users(self, client, test_db):
        """Logout only deletes tokens for the authenticated user."""
        # Create two users
        user1 = await create_test_user(test_db, email="user1@example.com")
        user2 = await create_test_user(test_db, email="user2@example.com")

        # Create refresh tokens for both
        token1 = RefreshToken(
            token="user1-refresh-token",
            user_id=user1.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        token2 = RefreshToken(
            token="user2-refresh-token",
            user_id=user2.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        test_db.add(token1)
        test_db.add(token2)
        await test_db.commit()

        # Logout user1
        headers = get_auth_headers(user1)
        await client.post(f"{API_PREFIX}/auth/github/logout", headers=headers)

        # Verify user2's token still exists
        result = await test_db.execute(
            select(RefreshToken).where(RefreshToken.user_id == user2.id)
        )
        user2_tokens = result.scalars().all()
        assert len(user2_tokens) == 1
