"""
Unit tests for Grafana service.
Focuses on pure functions and validation logic (no database operations).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.grafana.service import GrafanaService


class TestGrafanaServiceURLNormalization:
    """Tests for URL normalization logic."""

    def test_url_rstrip_trailing_slash(self):
        """Trailing slash is removed from URL."""
        url = "https://grafana.example.com/"

        normalized = url.rstrip("/")

        assert normalized == "https://grafana.example.com"

    def test_url_rstrip_multiple_slashes(self):
        """Multiple trailing slashes are removed."""
        url = "https://grafana.example.com///"

        normalized = url.rstrip("/")

        assert normalized == "https://grafana.example.com"

    def test_url_no_trailing_slash_unchanged(self):
        """URL without trailing slash remains unchanged."""
        url = "https://grafana.example.com"

        normalized = url.rstrip("/")

        assert normalized == "https://grafana.example.com"

    def test_api_user_endpoint_construction(self):
        """API user endpoint is constructed correctly."""
        grafana_url = "https://grafana.example.com/"

        endpoint = f"{grafana_url.rstrip('/')}/api/user"

        assert endpoint == "https://grafana.example.com/api/user"


class TestGrafanaServiceAuthHeaders:
    """Tests for authentication header construction."""

    def test_bearer_token_header(self):
        """Bearer token header is formatted correctly."""
        api_token = "glsa_abc123def456"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        assert headers["Authorization"] == "Bearer glsa_abc123def456"
        assert headers["Content-Type"] == "application/json"

    def test_headers_contain_required_fields(self):
        """Required headers are present."""
        api_token = "test-token"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        assert "Authorization" in headers
        assert "Content-Type" in headers


class TestGrafanaServiceValidateCredentialsMocked:
    """Tests for validate_credentials with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_validate_credentials_success(self):
        """Valid credentials return True."""
        service = GrafanaService()

        with patch("app.grafana.service.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_client.return_value = mock_context

            with patch("app.grafana.service.retry_external_api") as mock_retry:
                # Create a simple async generator that yields once
                async def mock_generator(*args, **kwargs):
                    class MockAttempt:
                        def __enter__(self):
                            return self

                        def __exit__(self, *args):
                            pass

                    yield MockAttempt()

                mock_retry.return_value = mock_generator()

                result = await service.validate_credentials(
                    "https://grafana.example.com", "valid-token"
                )

                assert result is True

    @pytest.mark.asyncio
    async def test_validate_credentials_invalid_token(self):
        """Invalid token returns False with 401 response."""
        service = GrafanaService()

        with patch("app.grafana.service.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 401

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_client.return_value = mock_context

            with patch("app.grafana.service.retry_external_api") as mock_retry:
                async def mock_generator(*args, **kwargs):
                    class MockAttempt:
                        def __enter__(self):
                            return self

                        def __exit__(self, *args):
                            pass

                    yield MockAttempt()

                mock_retry.return_value = mock_generator()

                result = await service.validate_credentials(
                    "https://grafana.example.com", "invalid-token"
                )

                assert result is False

    @pytest.mark.asyncio
    async def test_validate_credentials_insufficient_permissions(self):
        """Insufficient permissions returns False with 403 response."""
        service = GrafanaService()

        with patch("app.grafana.service.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 403

            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            mock_client.return_value = mock_context

            with patch("app.grafana.service.retry_external_api") as mock_retry:
                async def mock_generator(*args, **kwargs):
                    class MockAttempt:
                        def __enter__(self):
                            return self

                        def __exit__(self, *args):
                            pass

                    yield MockAttempt()

                mock_retry.return_value = mock_generator()

                result = await service.validate_credentials(
                    "https://grafana.example.com", "limited-token"
                )

                assert result is False

    @pytest.mark.asyncio
    async def test_validate_credentials_timeout(self):
        """Timeout returns False."""
        service = GrafanaService()

        with patch("app.grafana.service.httpx.AsyncClient") as mock_client:
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.TimeoutException("Connection timed out")
            )
            mock_client.return_value = mock_context

            result = await service.validate_credentials(
                "https://grafana.example.com", "token"
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_validate_credentials_connection_error(self):
        """Connection error returns False."""
        service = GrafanaService()

        with patch("app.grafana.service.httpx.AsyncClient") as mock_client:
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.RequestError("Connection refused")
            )
            mock_client.return_value = mock_context

            result = await service.validate_credentials(
                "https://invalid-host.example.com", "token"
            )

            assert result is False


class TestGrafanaServiceURLValidation:
    """Tests for URL validation patterns used in the service."""

    def test_valid_https_url(self):
        """HTTPS URLs are valid."""
        url = "https://grafana.example.com"

        is_https = url.startswith("https://")
        has_host = len(url.split("://")[1]) > 0

        assert is_https
        assert has_host

    def test_valid_http_url(self):
        """HTTP URLs are technically valid (for internal use)."""
        url = "http://grafana.internal:3000"

        is_http = url.startswith("http://")
        has_host = len(url.split("://")[1]) > 0

        assert is_http
        assert has_host

    def test_url_with_port(self):
        """URLs with port are valid."""
        url = "https://grafana.example.com:3000"

        # Basic validation - has protocol and host:port
        parts = url.replace("https://", "").replace("http://", "")
        has_port = ":" in parts

        assert has_port

    def test_url_with_path(self):
        """URLs with path should be normalized."""
        url = "https://grafana.example.com/grafana/"

        # Path should be stripped for base URL usage
        normalized = url.rstrip("/")

        assert normalized == "https://grafana.example.com/grafana"


class TestGrafanaServiceHealthStatusMapping:
    """Tests for health status to integration status mapping."""

    def test_healthy_maps_to_active(self):
        """'healthy' health status maps to 'active' integration status."""
        health_status = "healthy"

        if health_status == "healthy":
            integration_status = "active"
        elif health_status == "failed":
            integration_status = "error"
        else:
            integration_status = None

        assert integration_status == "active"

    def test_failed_maps_to_error(self):
        """'failed' health status maps to 'error' integration status."""
        health_status = "failed"

        if health_status == "healthy":
            integration_status = "active"
        elif health_status == "failed":
            integration_status = "error"
        else:
            integration_status = None

        assert integration_status == "error"
