"""
Unit tests for New Relic Integration Service.

Tests credential verification logic with mocked HTTP responses.
DB-heavy operations belong in integration tests.

Tests are organized by function and cover:
- Happy path scenarios
- Error handling
- Input validation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.newrelic.integration.service import verify_newrelic_credentials


# =============================================================================
# Tests: verify_newrelic_credentials (HTTP response handling)
# =============================================================================


class TestVerifyNewRelicCredentials:
    """Tests for verify_newrelic_credentials - credential verification logic."""

    @pytest.mark.asyncio
    async def test_verify_credentials_success(self):
        """Should return success when credentials are valid."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "actor": {
                    "account": {"id": "123456", "name": "Test Account"}
                }
            }
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            is_valid, error_msg = await verify_newrelic_credentials(
                account_id="123456", api_key="NRAK-XXXXXXXXXX"
            )

        assert is_valid is True
        assert error_msg == ""

    @pytest.mark.asyncio
    async def test_verify_credentials_invalid_api_key(self):
        """Should return error when API key is invalid (401)."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            is_valid, error_msg = await verify_newrelic_credentials(
                account_id="123456", api_key="invalid-key"
            )

        assert is_valid is False
        assert error_msg == "Invalid API key"

    @pytest.mark.asyncio
    async def test_verify_credentials_no_account_access(self):
        """Should return error when API key lacks account access (403)."""
        mock_response = MagicMock()
        mock_response.status_code = 403

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            is_valid, error_msg = await verify_newrelic_credentials(
                account_id="123456", api_key="NRAK-XXXXXXXXXX"
            )

        assert is_valid is False
        assert error_msg == "API key does not have access to this account"

    @pytest.mark.asyncio
    async def test_verify_credentials_graphql_error(self):
        """Should handle GraphQL errors in response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "errors": [{"message": "Account not found"}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            is_valid, error_msg = await verify_newrelic_credentials(
                account_id="999999", api_key="NRAK-XXXXXXXXXX"
            )

        assert is_valid is False
        assert "Account not found" in error_msg

    @pytest.mark.asyncio
    async def test_verify_credentials_empty_account_response(self):
        """Should handle empty account in response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"actor": {"account": None}}
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            is_valid, error_msg = await verify_newrelic_credentials(
                account_id="123456", api_key="NRAK-XXXXXXXXXX"
            )

        assert is_valid is False
        assert "Could not access account" in error_msg

    @pytest.mark.asyncio
    async def test_verify_credentials_timeout(self):
        """Should handle timeout gracefully."""
        import httpx

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Request timed out")
            )

            is_valid, error_msg = await verify_newrelic_credentials(
                account_id="123456", api_key="NRAK-XXXXXXXXXX"
            )

        assert is_valid is False
        assert "timeout" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_verify_credentials_network_error(self):
        """Should handle network errors gracefully."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            is_valid, error_msg = await verify_newrelic_credentials(
                account_id="123456", api_key="NRAK-XXXXXXXXXX"
            )

        assert is_valid is False
        assert "Connection refused" in error_msg

    @pytest.mark.asyncio
    async def test_verify_credentials_unexpected_status_code(self):
        """Should handle unexpected HTTP status codes."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            is_valid, error_msg = await verify_newrelic_credentials(
                account_id="123456", api_key="NRAK-XXXXXXXXXX"
            )

        assert is_valid is False
        assert "500" in error_msg
