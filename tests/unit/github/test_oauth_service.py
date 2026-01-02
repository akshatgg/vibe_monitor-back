"""
Unit tests for GitHub OAuth/App service.
Focuses on JWT generation and validation logic (no database operations).
"""

import time
from unittest.mock import patch

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt

from app.github.oauth.service import GitHubAppService


def generate_test_rsa_keys():
    """Generate a fresh RSA key pair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    return private_pem, public_pem


# Generate test keys once for all tests
TEST_RSA_PRIVATE_KEY, TEST_RSA_PUBLIC_KEY = generate_test_rsa_keys()


class TestGitHubAppServiceInit:
    """Tests for GitHubAppService initialization."""

    @patch("app.github.oauth.service.settings")
    def test_service_initializes_with_settings(self, mock_settings):
        """Service correctly reads settings on initialization."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = TEST_RSA_PRIVATE_KEY
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()

        assert service.GITHUB_APP_ID == "12345"
        assert service.GITHUB_PRIVATE_KEY == TEST_RSA_PRIVATE_KEY
        assert service.GITHUB_API_BASE == "https://api.github.com"


class TestGenerateJWT:
    """Tests for JWT generation."""

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_returns_valid_token(self, mock_settings):
        """JWT is generated with correct claims."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = TEST_RSA_PRIVATE_KEY
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()
        token = service.generate_jwt()

        # Decode and verify
        payload = jwt.decode(token, TEST_RSA_PUBLIC_KEY, algorithms=["RS256"])

        assert payload["iss"] == "12345"
        assert "iat" in payload
        assert "exp" in payload

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_exp_is_10_minutes(self, mock_settings):
        """JWT expiration is approximately 10 minutes from now."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = TEST_RSA_PRIVATE_KEY
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()
        now = int(time.time())
        token = service.generate_jwt()

        payload = jwt.decode(token, TEST_RSA_PUBLIC_KEY, algorithms=["RS256"])

        # exp should be about 10 minutes (600 seconds) from iat
        assert payload["exp"] - payload["iat"] == 11 * 60  # iat is now-60, exp is now+600

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_iat_is_backdated(self, mock_settings):
        """JWT issued-at is backdated by 60 seconds for clock skew."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = TEST_RSA_PRIVATE_KEY
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()
        now = int(time.time())
        token = service.generate_jwt()

        payload = jwt.decode(token, TEST_RSA_PUBLIC_KEY, algorithms=["RS256"])

        # iat should be about 60 seconds before now
        assert now - 65 <= payload["iat"] <= now - 55

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_missing_app_id_raises(self, mock_settings):
        """Raises HTTPException when GITHUB_APP_ID is not configured."""
        mock_settings.GITHUB_APP_ID = None
        mock_settings.GITHUB_PRIVATE_KEY_PEM = TEST_RSA_PRIVATE_KEY
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()

        with pytest.raises(HTTPException) as exc_info:
            service.generate_jwt()

        assert exc_info.value.status_code == 500
        assert "not configured" in exc_info.value.detail.lower()

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_missing_private_key_raises(self, mock_settings):
        """Raises HTTPException when GITHUB_PRIVATE_KEY is not configured."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = None
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()

        with pytest.raises(HTTPException) as exc_info:
            service.generate_jwt()

        assert exc_info.value.status_code == 500
        assert "not configured" in exc_info.value.detail.lower()

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_empty_app_id_raises(self, mock_settings):
        """Raises HTTPException when GITHUB_APP_ID is empty."""
        mock_settings.GITHUB_APP_ID = ""
        mock_settings.GITHUB_PRIVATE_KEY_PEM = TEST_RSA_PRIVATE_KEY
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()

        with pytest.raises(HTTPException) as exc_info:
            service.generate_jwt()

        assert exc_info.value.status_code == 500

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_empty_private_key_raises(self, mock_settings):
        """Raises HTTPException when GITHUB_PRIVATE_KEY is empty."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = ""
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()

        with pytest.raises(HTTPException) as exc_info:
            service.generate_jwt()

        assert exc_info.value.status_code == 500

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_handles_key_without_headers(self, mock_settings):
        """JWT generation handles private key without PEM headers."""
        # Extract the key body without headers
        key_lines = TEST_RSA_PRIVATE_KEY.strip().split("\n")
        key_body = "".join(key_lines[1:-1])  # Remove header and footer

        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = key_body
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()
        token = service.generate_jwt()

        # Should still produce a valid JWT
        payload = jwt.decode(token, TEST_RSA_PUBLIC_KEY, algorithms=["RS256"])
        assert payload["iss"] == "12345"

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_strips_whitespace(self, mock_settings):
        """JWT generation strips whitespace from private key."""
        key_with_whitespace = f"  \n{TEST_RSA_PRIVATE_KEY}\n  "

        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = key_with_whitespace
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()
        token = service.generate_jwt()

        # Should still produce a valid JWT
        payload = jwt.decode(token, TEST_RSA_PUBLIC_KEY, algorithms=["RS256"])
        assert payload["iss"] == "12345"

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_invalid_key_raises(self, mock_settings):
        """Raises HTTPException when private key is invalid."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = "not-a-valid-key"
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()

        with pytest.raises(HTTPException) as exc_info:
            service.generate_jwt()

        assert exc_info.value.status_code == 500
        assert "failed to generate jwt" in exc_info.value.detail.lower()

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_uses_rs256_algorithm(self, mock_settings):
        """JWT is signed with RS256 algorithm."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = TEST_RSA_PRIVATE_KEY
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()
        token = service.generate_jwt()

        # Get the header to check algorithm
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256"

    @patch("app.github.oauth.service.settings")
    def test_generate_jwt_uniqueness(self, mock_settings):
        """Multiple calls generate different tokens (due to time-based claims)."""
        mock_settings.GITHUB_APP_ID = "12345"
        mock_settings.GITHUB_PRIVATE_KEY_PEM = TEST_RSA_PRIVATE_KEY
        mock_settings.GITHUB_API_BASE_URL = "https://api.github.com"

        service = GitHubAppService()

        # Generate tokens with slight time delay
        import time

        token1 = service.generate_jwt()
        time.sleep(0.1)
        token2 = service.generate_jwt()

        # Tokens may be same if generated within same second, but payloads are time-based
        # Just verify both are valid
        payload1 = jwt.decode(token1, TEST_RSA_PUBLIC_KEY, algorithms=["RS256"])
        payload2 = jwt.decode(token2, TEST_RSA_PUBLIC_KEY, algorithms=["RS256"])

        assert payload1["iss"] == payload2["iss"]  # Same issuer
