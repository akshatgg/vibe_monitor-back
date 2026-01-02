"""
Unit tests for GitHub webhook service.
Focuses on signature verification logic (no database operations).
"""

import hashlib
import hmac
from unittest.mock import patch

import pytest

from app.github.webhook.service import GitHubWebhookService


class TestVerifySignature:
    """Tests for webhook signature verification."""

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_valid(self, mock_settings):
        """Valid signature returns True."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        request_body = '{"action": "created", "installation": {"id": 123}}'

        # Compute valid signature
        expected_signature = hmac.new(
            key=b"test-webhook-secret",
            msg=request_body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        signature = f"sha256={expected_signature}"

        result = GitHubWebhookService.verify_signature(signature, request_body)

        assert result is True

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_invalid_signature_raises(self, mock_settings):
        """Invalid signature raises ValueError."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        request_body = '{"action": "created", "installation": {"id": 123}}'
        invalid_signature = "sha256=invalid_signature_hash"

        with pytest.raises(ValueError) as exc_info:
            GitHubWebhookService.verify_signature(invalid_signature, request_body)

        assert "signature verification failed" in str(exc_info.value).lower()

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_no_secret_configured_raises(self, mock_settings):
        """Raises ValueError when webhook secret is not configured."""
        mock_settings.GITHUB_WEBHOOK_SECRET = None

        request_body = '{"action": "created"}'
        signature = "sha256=somehash"

        with pytest.raises(ValueError) as exc_info:
            GitHubWebhookService.verify_signature(signature, request_body)

        assert "not configured" in str(exc_info.value).lower()

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_empty_secret_configured_raises(self, mock_settings):
        """Raises ValueError when webhook secret is empty string."""
        mock_settings.GITHUB_WEBHOOK_SECRET = ""

        request_body = '{"action": "created"}'
        signature = "sha256=somehash"

        with pytest.raises(ValueError) as exc_info:
            GitHubWebhookService.verify_signature(signature, request_body)

        assert "not configured" in str(exc_info.value).lower()

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_no_signature_provided_raises(self, mock_settings):
        """Raises ValueError when no signature is provided."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        request_body = '{"action": "created"}'

        with pytest.raises(ValueError) as exc_info:
            GitHubWebhookService.verify_signature(None, request_body)

        assert "no signature provided" in str(exc_info.value).lower()

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_empty_signature_raises(self, mock_settings):
        """Raises ValueError when signature is empty string."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        request_body = '{"action": "created"}'

        with pytest.raises(ValueError) as exc_info:
            GitHubWebhookService.verify_signature("", request_body)

        assert "no signature provided" in str(exc_info.value).lower()

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_invalid_format_raises(self, mock_settings):
        """Raises ValueError when signature doesn't have sha256= prefix."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        request_body = '{"action": "created"}'
        invalid_format_signature = "md5=somehash"

        with pytest.raises(ValueError) as exc_info:
            GitHubWebhookService.verify_signature(invalid_format_signature, request_body)

        assert "invalid signature format" in str(exc_info.value).lower()

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_wrong_secret_raises(self, mock_settings):
        """Raises ValueError when signature was computed with different secret."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "correct-secret"

        request_body = '{"action": "created", "installation": {"id": 123}}'

        # Compute signature with WRONG secret
        wrong_signature = hmac.new(
            key=b"wrong-secret",
            msg=request_body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        signature = f"sha256={wrong_signature}"

        with pytest.raises(ValueError) as exc_info:
            GitHubWebhookService.verify_signature(signature, request_body)

        assert "signature verification failed" in str(exc_info.value).lower()

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_tampered_body_raises(self, mock_settings):
        """Raises ValueError when request body was tampered with."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        original_body = '{"action": "created", "installation": {"id": 123}}'
        tampered_body = '{"action": "deleted", "installation": {"id": 123}}'

        # Compute signature with original body
        valid_signature = hmac.new(
            key=b"test-webhook-secret",
            msg=original_body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        signature = f"sha256={valid_signature}"

        # Verify with tampered body should fail
        with pytest.raises(ValueError) as exc_info:
            GitHubWebhookService.verify_signature(signature, tampered_body)

        assert "signature verification failed" in str(exc_info.value).lower()

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_case_sensitive_hash(self, mock_settings):
        """Signature hash comparison handles case correctly."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        request_body = '{"action": "created"}'

        # Compute valid signature (lowercase hex)
        expected_signature = hmac.new(
            key=b"test-webhook-secret",
            msg=request_body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        # GitHub sends lowercase, so test that it works
        signature = f"sha256={expected_signature.lower()}"

        result = GitHubWebhookService.verify_signature(signature, request_body)
        assert result is True

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_unicode_body(self, mock_settings):
        """Signature verification works with unicode characters in body."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        request_body = '{"message": "Hello 世界 🌍"}'

        expected_signature = hmac.new(
            key=b"test-webhook-secret",
            msg=request_body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        signature = f"sha256={expected_signature}"

        result = GitHubWebhookService.verify_signature(signature, request_body)
        assert result is True

    @patch("app.github.webhook.service.settings")
    def test_verify_signature_empty_body(self, mock_settings):
        """Signature verification works with empty body."""
        mock_settings.GITHUB_WEBHOOK_SECRET = "test-webhook-secret"

        request_body = ""

        expected_signature = hmac.new(
            key=b"test-webhook-secret",
            msg=request_body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        signature = f"sha256={expected_signature}"

        result = GitHubWebhookService.verify_signature(signature, request_body)
        assert result is True
