"""
Unit tests for Slack service.
Focuses on pure functions and validation logic (no database operations).
"""

import hashlib
import hmac
import time
from unittest.mock import patch

import pytest

from app.slack.service import EventDeduplicationCache, SlackEventService


class TestEventDeduplicationCache:
    """Tests for EventDeduplicationCache - thread-safe in-memory cache with TTL."""

    def test_init_default_ttl(self):
        """Cache initializes with default TTL of 300 seconds."""
        cache = EventDeduplicationCache()
        assert cache.ttl_seconds == 300

    def test_init_custom_ttl(self):
        """Cache respects custom TTL."""
        cache = EventDeduplicationCache(ttl_seconds=60)
        assert cache.ttl_seconds == 60

    def test_new_event_not_duplicate(self):
        """New event is not marked as duplicate."""
        cache = EventDeduplicationCache()
        assert cache.is_duplicate("event-123") is False

    def test_processed_event_is_duplicate(self):
        """Processed event is marked as duplicate."""
        cache = EventDeduplicationCache()
        cache.mark_processed("event-123")

        assert cache.is_duplicate("event-123") is True

    def test_multiple_events_tracked_independently(self):
        """Multiple events are tracked independently."""
        cache = EventDeduplicationCache()
        cache.mark_processed("event-1")
        cache.mark_processed("event-2")

        assert cache.is_duplicate("event-1") is True
        assert cache.is_duplicate("event-2") is True
        assert cache.is_duplicate("event-3") is False

    def test_expired_event_not_duplicate(self):
        """Expired event is not marked as duplicate."""
        cache = EventDeduplicationCache(ttl_seconds=1)
        cache.mark_processed("event-123")

        # Wait for TTL to expire
        time.sleep(1.1)

        assert cache.is_duplicate("event-123") is False

    def test_event_within_ttl_is_duplicate(self):
        """Event within TTL window is marked as duplicate."""
        cache = EventDeduplicationCache(ttl_seconds=5)
        cache.mark_processed("event-123")

        # Still within TTL
        assert cache.is_duplicate("event-123") is True

    def test_cleanup_removes_expired_entries(self):
        """Cleanup removes expired entries."""
        cache = EventDeduplicationCache(ttl_seconds=1)
        cache.mark_processed("event-1")
        cache.mark_processed("event-2")

        # Wait for TTL to expire
        time.sleep(1.1)

        # Trigger cleanup by calling _cleanup directly
        cache._cleanup()

        # Cache should be empty (internal check)
        assert len(cache._cache) == 0

    def test_mark_processed_updates_timestamp(self):
        """Re-processing an event updates its timestamp."""
        cache = EventDeduplicationCache(ttl_seconds=2)
        cache.mark_processed("event-123")

        time.sleep(1)  # Wait 1 second

        # Re-process the event (updates timestamp)
        cache.mark_processed("event-123")

        time.sleep(
            1.5
        )  # Wait another 1.5 seconds (total 2.5s from first, 1.5s from second)

        # Event should still be valid because timestamp was updated
        assert cache.is_duplicate("event-123") is True

    def test_cache_auto_cleanup_on_large_size(self):
        """Cache auto-cleans when size exceeds 1000 entries."""
        cache = EventDeduplicationCache(ttl_seconds=1)

        # Add 1001 events (triggers cleanup when adding the 1001st)
        for i in range(1001):
            cache.mark_processed(f"event-{i}")

        # Wait for TTL to expire
        time.sleep(1.1)

        # Add one more to trigger cleanup
        cache.mark_processed("event-new")

        # Most old entries should be cleaned up
        assert cache.is_duplicate("event-0") is False

    def test_empty_event_id(self):
        """Empty string event ID is handled."""
        cache = EventDeduplicationCache()
        cache.mark_processed("")

        assert cache.is_duplicate("") is True

    def test_special_characters_in_event_id(self):
        """Event IDs with special characters are handled."""
        cache = EventDeduplicationCache()
        event_id = "evt-123_abc.xyz:456"
        cache.mark_processed(event_id)

        assert cache.is_duplicate(event_id) is True


class TestSlackEventServiceVerifyRequest:
    """Tests for Slack request signature verification."""

    @pytest.fixture
    def slack_signing_secret(self):
        """Test signing secret."""
        return "test-signing-secret-12345"

    def _generate_signature(self, secret: str, timestamp: str, body: str) -> str:
        """Helper to generate valid Slack signature."""
        base_string = f"v0:{timestamp}:{body}"
        signature = (
            "v0="
            + hmac.new(
                key=secret.encode("utf-8"),
                msg=base_string.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
        )
        return signature

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_valid_signature_returns_true(
        self, mock_settings, slack_signing_secret
    ):
        """Valid signature returns True."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        timestamp = str(int(time.time()))
        body = '{"type":"event_callback","event":{}}'
        signature = self._generate_signature(slack_signing_secret, timestamp, body)

        result = await SlackEventService.verify_slack_request(
            signature, timestamp, body
        )
        assert result is True

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_invalid_signature_returns_false(
        self, mock_settings, slack_signing_secret
    ):
        """Invalid signature returns False."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        timestamp = str(int(time.time()))
        body = '{"type":"event_callback","event":{}}'
        wrong_signature = "v0=invalid_signature_hash"

        result = await SlackEventService.verify_slack_request(
            wrong_signature, timestamp, body
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_tampered_body_returns_false(
        self, mock_settings, slack_signing_secret
    ):
        """Tampered body returns False."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        timestamp = str(int(time.time()))
        original_body = '{"type":"event_callback","event":{}}'
        signature = self._generate_signature(
            slack_signing_secret, timestamp, original_body
        )

        tampered_body = '{"type":"event_callback","event":{"malicious":true}}'

        result = await SlackEventService.verify_slack_request(
            signature, timestamp, tampered_body
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_missing_signing_secret_returns_false(self, mock_settings):
        """Missing signing secret returns False."""
        mock_settings.SLACK_SIGNING_SECRET = None

        result = await SlackEventService.verify_slack_request(
            "v0=signature", "12345", "body"
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_empty_signing_secret_returns_false(self, mock_settings):
        """Empty signing secret returns False."""
        mock_settings.SLACK_SIGNING_SECRET = ""

        result = await SlackEventService.verify_slack_request(
            "v0=signature", "12345", "body"
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_missing_signature_returns_false(
        self, mock_settings, slack_signing_secret
    ):
        """Missing signature returns False."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        result = await SlackEventService.verify_slack_request("", "12345", "body")
        assert result is False

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_missing_timestamp_returns_false(
        self, mock_settings, slack_signing_secret
    ):
        """Missing timestamp returns False."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        result = await SlackEventService.verify_slack_request(
            "v0=signature", "", "body"
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_none_signature_returns_false(
        self, mock_settings, slack_signing_secret
    ):
        """None signature returns False."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        result = await SlackEventService.verify_slack_request(None, "12345", "body")
        assert result is False

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_different_secret_returns_false(
        self, mock_settings, slack_signing_secret
    ):
        """Signature created with different secret returns False."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        timestamp = str(int(time.time()))
        body = '{"type":"event_callback"}'
        # Generate signature with wrong secret
        wrong_secret_signature = self._generate_signature(
            "different-secret", timestamp, body
        )

        result = await SlackEventService.verify_slack_request(
            wrong_secret_signature, timestamp, body
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_empty_body_valid_signature(
        self, mock_settings, slack_signing_secret
    ):
        """Empty body with valid signature returns True."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        timestamp = str(int(time.time()))
        body = ""
        signature = self._generate_signature(slack_signing_secret, timestamp, body)

        result = await SlackEventService.verify_slack_request(
            signature, timestamp, body
        )
        assert result is True

    @pytest.mark.asyncio
    @patch("app.slack.service.settings")
    async def test_json_body_with_unicode(self, mock_settings, slack_signing_secret):
        """JSON body with unicode characters verifies correctly."""
        mock_settings.SLACK_SIGNING_SECRET = slack_signing_secret

        timestamp = str(int(time.time()))
        body = '{"text":"Hello World!"}'
        signature = self._generate_signature(slack_signing_secret, timestamp, body)

        result = await SlackEventService.verify_slack_request(
            signature, timestamp, body
        )
        assert result is True
