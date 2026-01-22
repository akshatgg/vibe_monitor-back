"""
Unit tests for AuthService.

Tests pure functions and validation logic. DB-heavy operations
(create_or_get_user, refresh_access_token, get_current_user) belong
in integration tests.

Tests are organized by method and cover:
- Happy path scenarios
- Edge cases
- Error handling
- Input validation
"""

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt


# Use the module-scoped fixture from conftest.py to set up mocks before import
@pytest.fixture(scope="module")
def auth_service_module(mock_auth_service_dependencies):
    """Import AuthService after mocks are set up."""
    from app.onboarding.services.auth_service import AuthService

    return AuthService


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def auth_service(auth_service_module):
    """Create AuthService instance with mocked settings."""
    with patch("app.onboarding.services.auth_service.settings") as mock_settings:
        mock_settings.JWT_SECRET_KEY = "test-secret-key"
        mock_settings.JWT_ALGORITHM = "HS256"
        mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
        mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
        mock_settings.GOOGLE_CLIENT_ID = "test-google-client-id"
        mock_settings.GOOGLE_CLIENT_SECRET = "test-google-client-secret"
        mock_settings.GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
        mock_settings.GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
        mock_settings.GOOGLE_USERINFO_URL = (
            "https://www.googleapis.com/oauth2/v3/userinfo"
        )
        yield auth_service_module()


@pytest.fixture
def google_user_info():
    """Sample Google user info response."""
    return {
        "sub": "google-user-id-123",
        "email": "test@example.com",
        "name": "Test User",
        "picture": "https://example.com/photo.jpg",
    }


# =============================================================================
# Tests: generate_pkce_pair (Pure Function)
# =============================================================================


class TestGeneratePkcePair:
    """Tests for generate_pkce_pair method - pure cryptographic function."""

    def test_generate_pkce_pair_returns_tuple(self, auth_service):
        result = auth_service.generate_pkce_pair()

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_generate_pkce_pair_verifier_is_base64_url_safe(self, auth_service):
        code_verifier, _ = auth_service.generate_pkce_pair()

        # Should only contain URL-safe base64 characters (no padding)
        assert "=" not in code_verifier
        assert "+" not in code_verifier
        assert "/" not in code_verifier

    def test_generate_pkce_pair_challenge_matches_verifier(self, auth_service):
        code_verifier, code_challenge = auth_service.generate_pkce_pair()

        # Verify challenge is SHA256 of verifier
        expected_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            )
            .decode("utf-8")
            .rstrip("=")
        )
        assert code_challenge == expected_challenge

    def test_generate_pkce_pair_returns_unique_values(self, auth_service):
        pair1 = auth_service.generate_pkce_pair()
        pair2 = auth_service.generate_pkce_pair()

        assert pair1[0] != pair2[0]  # Verifiers should be different
        assert pair1[1] != pair2[1]  # Challenges should be different


# =============================================================================
# Tests: get_google_auth_url (Pure Function)
# =============================================================================


class TestGetGoogleAuthUrl:
    """Tests for get_google_auth_url method - URL construction logic."""

    def test_get_google_auth_url_returns_valid_url(self, auth_service):
        url = auth_service.get_google_auth_url(
            redirect_uri="https://example.com/callback"
        )

        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=test-google-client-id" in url
        assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
        assert "response_type=code" in url

    def test_get_google_auth_url_includes_state_when_provided(self, auth_service):
        url = auth_service.get_google_auth_url(
            redirect_uri="https://example.com/callback",
            state="custom-state-123",
        )

        assert "state=custom-state-123" in url

    def test_get_google_auth_url_generates_state_when_not_provided(self, auth_service):
        url = auth_service.get_google_auth_url(
            redirect_uri="https://example.com/callback"
        )

        assert "state=" in url

    def test_get_google_auth_url_includes_pkce_when_provided(self, auth_service):
        url = auth_service.get_google_auth_url(
            redirect_uri="https://example.com/callback",
            code_challenge="test-challenge",
            code_challenge_method="S256",
        )

        assert "code_challenge=test-challenge" in url
        assert "code_challenge_method=S256" in url

    def test_get_google_auth_url_without_client_id_raises_error(
        self, auth_service_module
    ):
        with patch("app.onboarding.services.auth_service.settings") as mock_settings:
            mock_settings.GOOGLE_CLIENT_ID = None
            mock_settings.JWT_SECRET_KEY = "test"
            mock_settings.JWT_ALGORITHM = "HS256"
            mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
            mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
            service = auth_service_module()

            with pytest.raises(HTTPException) as exc_info:
                service.get_google_auth_url(redirect_uri="https://example.com/callback")

            assert exc_info.value.status_code == 500
            assert "Google OAuth not configured" in exc_info.value.detail


# =============================================================================
# Tests: create_access_token (Pure Function)
# =============================================================================


class TestCreateAccessToken:
    """Tests for create_access_token method - JWT encoding logic."""

    def test_create_access_token_returns_valid_jwt(self, auth_service):
        token = auth_service.create_access_token(data={"sub": "user-123"})

        assert isinstance(token, str)
        decoded = jwt.decode(token, "test-secret-key", algorithms=["HS256"])
        assert decoded["sub"] == "user-123"
        assert decoded["type"] == "access"

    def test_create_access_token_uses_default_expiry(self, auth_service):
        token = auth_service.create_access_token(data={"sub": "user-123"})

        decoded = jwt.decode(token, "test-secret-key", algorithms=["HS256"])
        exp = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)

        # Should expire in approximately 30 minutes (default)
        assert timedelta(minutes=29) < (exp - now) < timedelta(minutes=31)

    def test_create_access_token_uses_custom_expiry(self, auth_service):
        token = auth_service.create_access_token(
            data={"sub": "user-123"},
            expires_delta=timedelta(hours=2),
        )

        decoded = jwt.decode(token, "test-secret-key", algorithms=["HS256"])
        exp = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)

        # Should expire in approximately 2 hours
        assert (
            timedelta(hours=1, minutes=59) < (exp - now) < timedelta(hours=2, minutes=1)
        )

    def test_create_access_token_preserves_original_data(self, auth_service):
        original_data = {"sub": "user-123", "email": "test@example.com"}

        auth_service.create_access_token(data=original_data)

        # Original data should not be modified
        assert "exp" not in original_data
        assert "type" not in original_data


# =============================================================================
# Tests: verify_token (Pure Function)
# =============================================================================


class TestVerifyToken:
    """Tests for verify_token method - JWT decoding and validation logic."""

    def test_verify_token_with_valid_access_token_returns_payload(self, auth_service):
        token = auth_service.create_access_token(data={"sub": "user-123"})

        payload = auth_service.verify_token(token, token_type="access")

        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"

    def test_verify_token_with_wrong_type_raises_error(self, auth_service):
        token = auth_service.create_access_token(data={"sub": "user-123"})

        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_token(token, token_type="refresh")

        assert exc_info.value.status_code == 401
        assert "Invalid token type" in exc_info.value.detail

    def test_verify_token_with_invalid_token_raises_error(self, auth_service):
        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_token("invalid-token", token_type="access")

        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    def test_verify_token_with_wrong_secret_raises_error(self, auth_service):
        # Create token with different secret
        token = jwt.encode(
            {
                "sub": "user-123",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "different-secret",
            algorithm="HS256",
        )

        with pytest.raises(HTTPException) as exc_info:
            auth_service.verify_token(token, token_type="access")

        assert exc_info.value.status_code == 401


# =============================================================================
# Tests: validate_id_token (Pure Function)
# =============================================================================


class TestValidateIdToken:
    """Tests for validate_id_token method - Google ID token validation logic."""

    @pytest.mark.asyncio
    async def test_validate_id_token_with_valid_token_returns_payload(
        self, auth_service
    ):
        payload = {
            "sub": "user-id-123",
            "email": "test@example.com",
            "aud": "test-google-client-id",
            "iss": "https://accounts.google.com",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "secret", algorithm="HS256")

        result = await auth_service.validate_id_token(token)

        assert result["sub"] == "user-id-123"
        assert result["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_validate_id_token_with_wrong_audience_raises_error(
        self, auth_service
    ):
        payload = {
            "sub": "user-id-123",
            "aud": "wrong-client-id",
            "iss": "https://accounts.google.com",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "secret", algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.validate_id_token(token)

        assert exc_info.value.status_code == 400
        assert "Invalid token audience" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_validate_id_token_with_expired_token_raises_error(
        self, auth_service
    ):
        payload = {
            "sub": "user-id-123",
            "aud": "test-google-client-id",
            "iss": "https://accounts.google.com",
            "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "secret", algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.validate_id_token(token)

        assert exc_info.value.status_code == 400
        assert "Token has expired" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_validate_id_token_with_wrong_issuer_raises_error(self, auth_service):
        payload = {
            "sub": "user-id-123",
            "aud": "test-google-client-id",
            "iss": "https://malicious-site.com",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }
        token = jwt.encode(payload, "secret", algorithm="HS256")

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.validate_id_token(token)

        assert exc_info.value.status_code == 400
        assert "Invalid token issuer" in exc_info.value.detail


# =============================================================================
# Tests: get_user_info_from_google (Mocks HTTP, Tests Validation)
# =============================================================================


class TestGetUserInfoFromGoogle:
    """Tests for get_user_info_from_google - response validation logic.

    Mocks HTTP calls to Google, but tests the validation logic that
    ensures required fields (sub, email) are present.
    """

    @pytest.mark.asyncio
    async def test_get_user_info_from_google_success(
        self, auth_service, google_user_info
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = google_user_info
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await auth_service.get_user_info_from_google("access-token")

        assert result["email"] == "test@example.com"
        assert result["sub"] == "google-user-id-123"

    @pytest.mark.asyncio
    async def test_get_user_info_from_google_missing_sub_raises_error(
        self, auth_service
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"email": "test@example.com"}  # Missing 'sub'
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(HTTPException) as exc_info:
                await auth_service.get_user_info_from_google("access-token")

            assert exc_info.value.status_code == 400
            assert "Missing required user information" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_user_info_from_google_missing_email_raises_error(
        self, auth_service
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"sub": "123"}  # Missing 'email'
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(HTTPException) as exc_info:
                await auth_service.get_user_info_from_google("access-token")

            assert exc_info.value.status_code == 400


# =============================================================================
# Tests: exchange_code_for_tokens (Mocks HTTP, Tests Request Construction)
# =============================================================================


class TestExchangeCodeForTokens:
    """Tests for exchange_code_for_tokens - request construction logic.

    Mocks HTTP calls, but verifies that the request payload is
    constructed correctly (PKCE code_verifier included, etc.).
    """

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_includes_code_verifier(self, auth_service):
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "token"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await auth_service.exchange_code_for_tokens(
                code="auth-code",
                redirect_uri="https://example.com/callback",
                code_verifier="test-verifier",
            )

            # Verify code_verifier was included in request
            call_args = mock_post.call_args
            assert call_args[1]["data"]["code_verifier"] == "test-verifier"

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens_without_credentials_raises_error(
        self, auth_service_module
    ):
        with patch("app.onboarding.services.auth_service.settings") as mock_settings:
            mock_settings.GOOGLE_CLIENT_ID = None
            mock_settings.GOOGLE_CLIENT_SECRET = None
            mock_settings.JWT_SECRET_KEY = "test"
            mock_settings.JWT_ALGORITHM = "HS256"
            mock_settings.ACCESS_TOKEN_EXPIRE_MINUTES = 30
            mock_settings.REFRESH_TOKEN_EXPIRE_DAYS = 7
            service = auth_service_module()

            with pytest.raises(HTTPException) as exc_info:
                await service.exchange_code_for_tokens(
                    code="auth-code",
                    redirect_uri="https://example.com/callback",
                )

            assert exc_info.value.status_code == 500
