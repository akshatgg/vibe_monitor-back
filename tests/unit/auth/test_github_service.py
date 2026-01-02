"""
Unit tests for GitHub auth service.
Focuses on pure functions and validation logic (no database operations).
"""

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from jose import jwt

from app.auth.github.service import GitHubAuthService


class TestGitHubAuthServicePKCE:
    """Tests for PKCE code generation."""

    def test_generate_pkce_pair_returns_tuple(self):
        """PKCE generation returns a tuple of (verifier, challenge)."""
        service = GitHubAuthService()
        result = service.generate_pkce_pair()

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_generate_pkce_pair_verifier_format(self):
        """Code verifier is base64url encoded without padding."""
        service = GitHubAuthService()
        verifier, _ = service.generate_pkce_pair()

        # Should be base64url safe characters only
        assert all(c.isalnum() or c in "-_" for c in verifier)
        # Should not have padding
        assert "=" not in verifier
        # Should be reasonable length (32 bytes -> ~43 chars)
        assert len(verifier) >= 40

    def test_generate_pkce_pair_challenge_derives_from_verifier(self):
        """Code challenge is SHA256 hash of verifier, base64url encoded."""
        service = GitHubAuthService()
        verifier, challenge = service.generate_pkce_pair()

        # Manually compute expected challenge
        expected_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
            .decode("utf-8")
            .rstrip("=")
        )

        assert challenge == expected_challenge

    def test_generate_pkce_pair_uniqueness(self):
        """Each call generates unique verifier/challenge pairs."""
        service = GitHubAuthService()
        pairs = [service.generate_pkce_pair() for _ in range(10)]

        verifiers = [p[0] for p in pairs]
        challenges = [p[1] for p in pairs]

        # All should be unique
        assert len(set(verifiers)) == 10
        assert len(set(challenges)) == 10


class TestGitHubAuthServiceAuthURL:
    """Tests for GitHub auth URL generation."""

    @patch("app.auth.github.service.settings")
    def test_get_github_auth_url_basic(self, mock_settings):
        """Basic auth URL generation with required parameters."""
        mock_settings.JWT_SECRET_KEY = "test-secret"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()
        url = service.get_github_auth_url(
            redirect_uri="https://example.com/callback",
            state="test-state",
        )

        assert "https://github.com/login/oauth/authorize" in url
        assert "client_id=test-client-id" in url
        assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
        assert "state=test-state" in url
        assert "scope=read%3Auser+user%3Aemail" in url
        assert "allow_signup=true" in url

    @patch("app.auth.github.service.settings")
    def test_get_github_auth_url_with_pkce(self, mock_settings):
        """Auth URL includes PKCE parameters when provided."""
        mock_settings.JWT_SECRET_KEY = "test-secret"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()
        url = service.get_github_auth_url(
            redirect_uri="https://example.com/callback",
            state="test-state",
            code_challenge="test-challenge",
            code_challenge_method="S256",
        )

        assert "code_challenge=test-challenge" in url
        assert "code_challenge_method=S256" in url

    @patch("app.auth.github.service.settings")
    def test_get_github_auth_url_generates_state_if_not_provided(self, mock_settings):
        """State is auto-generated if not provided."""
        mock_settings.JWT_SECRET_KEY = "test-secret"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()
        url = service.get_github_auth_url(redirect_uri="https://example.com/callback")

        # State parameter should be present
        assert "state=" in url

    @patch("app.auth.github.service.settings")
    def test_get_github_auth_url_raises_if_not_configured(self, mock_settings):
        """Raises HTTPException if GitHub OAuth is not configured."""
        mock_settings.JWT_SECRET_KEY = "test-secret"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = None
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()

        with pytest.raises(HTTPException) as exc_info:
            service.get_github_auth_url(redirect_uri="https://example.com/callback")

        assert exc_info.value.status_code == 500
        assert "not configured" in exc_info.value.detail


class TestGitHubAuthServiceJWT:
    """Tests for JWT token operations."""

    @patch("app.auth.github.service.settings")
    def test_create_access_token_valid(self, mock_settings):
        """Access token is created with correct payload."""
        mock_settings.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()
        token = service.create_access_token(
            data={"sub": "user-123", "email": "test@example.com"}
        )

        # Decode and verify
        payload = jwt.decode(token, "test-secret-key", algorithms=["HS256"])

        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"
        assert payload["type"] == "access"
        assert "exp" in payload

    @patch("app.auth.github.service.settings")
    def test_create_access_token_with_custom_expiry(self, mock_settings):
        """Access token respects custom expiry delta."""
        mock_settings.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()
        expires_delta = timedelta(hours=1)
        token = service.create_access_token(
            data={"sub": "user-123"}, expires_delta=expires_delta
        )

        payload = jwt.decode(token, "test-secret-key", algorithms=["HS256"])

        # Check expiry is roughly 1 hour from now
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expected_exp = datetime.now(timezone.utc) + timedelta(hours=1)

        # Allow 5 second tolerance
        assert abs((exp_time - expected_exp).total_seconds()) < 5

    @patch("app.auth.github.service.settings")
    def test_verify_token_valid_access_token(self, mock_settings):
        """Valid access token is verified successfully."""
        mock_settings.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()
        token = service.create_access_token(data={"sub": "user-123"})

        payload = service.verify_token(token, "access")

        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"

    @patch("app.auth.github.service.settings")
    def test_verify_token_wrong_type_raises(self, mock_settings):
        """Verifying token with wrong type raises HTTPException."""
        mock_settings.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()
        token = service.create_access_token(data={"sub": "user-123"})

        with pytest.raises(HTTPException) as exc_info:
            service.verify_token(token, "refresh")  # Wrong type

        assert exc_info.value.status_code == 401
        assert "Invalid token type" in exc_info.value.detail

    @patch("app.auth.github.service.settings")
    def test_verify_token_invalid_token_raises(self, mock_settings):
        """Invalid token raises HTTPException."""
        mock_settings.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()

        with pytest.raises(HTTPException) as exc_info:
            service.verify_token("invalid-token", "access")

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    @patch("app.auth.github.service.settings")
    def test_verify_token_expired_raises(self, mock_settings):
        """Expired token raises HTTPException."""
        mock_settings.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()
        # Create already-expired token
        token = service.create_access_token(
            data={"sub": "user-123"}, expires_delta=timedelta(seconds=-1)
        )

        with pytest.raises(HTTPException) as exc_info:
            service.verify_token(token, "access")

        assert exc_info.value.status_code == 401

    @patch("app.auth.github.service.settings")
    def test_verify_token_wrong_secret_raises(self, mock_settings):
        """Token signed with different secret raises HTTPException."""
        mock_settings.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GITHUB_OAUTH_CLIENT_ID = "test-client-id"
        mock_settings.GITHUB_OAUTH_CLIENT_SECRET = "test-secret"
        mock_settings.GITHUB_OAUTH_AUTH_URL = "https://github.com/login/oauth/authorize"
        mock_settings.GITHUB_OAUTH_TOKEN_URL = (
            "https://github.com/login/oauth/access_token"
        )
        mock_settings.GITHUB_OAUTH_USER_URL = "https://api.github.com/user"
        mock_settings.GITHUB_OAUTH_USER_EMAIL_URL = "https://api.github.com/user/emails"

        service = GitHubAuthService()

        # Create token with different secret
        wrong_token = jwt.encode(
            {
                "sub": "user-123",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "wrong-secret",
            algorithm="HS256",
        )

        with pytest.raises(HTTPException) as exc_info:
            service.verify_token(wrong_token, "access")

        assert exc_info.value.status_code == 401
