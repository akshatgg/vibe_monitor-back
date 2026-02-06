"""Unit tests for WebProgressCallback.on_chain_error suppression logic."""

from unittest.mock import AsyncMock, patch

import pytest

from app.chat.notifiers.web_callback import WebProgressCallback


@pytest.fixture
def callback():
    """Create a WebProgressCallback with mocked internals."""
    with patch.object(WebProgressCallback, "__init__", lambda self, *a, **kw: None):
        cb = WebProgressCallback.__new__(WebProgressCallback)
        cb.turn_id = "turn-123"
        cb.db = AsyncMock()
        cb.notifier = AsyncMock()
        cb.step_counter = 0
        cb._current_step_id = None
        cb._current_tool_display_name = None
        cb._suppressed_error_count = 0
        return cb


class TestOnChainErrorSuppression:
    """Tests for retryable error suppression in on_chain_error."""

    @pytest.mark.asyncio
    async def test_retryable_error_suppressed_below_limit(self, callback):
        """Retryable errors are suppressed and not forwarded to notifier."""
        err = Exception("Tool call validation failed for tool xyz")
        await callback.on_chain_error(err)

        callback.notifier.on_error.assert_not_awaited()
        assert callback._suppressed_error_count == 1

    @pytest.mark.asyncio
    async def test_non_retryable_error_always_forwarded(self, callback):
        """Non-retryable errors are always forwarded to the notifier."""
        err = Exception("Connection refused to Grafana")
        await callback.on_chain_error(err)

        callback.notifier.on_error.assert_awaited_once()
        assert callback._suppressed_error_count == 0

    @pytest.mark.asyncio
    async def test_retryable_error_surfaced_after_limit(self, callback):
        """After exceeding max retries, retryable errors are forwarded."""
        # Default RCA_EVIDENCE_AGENT_MAX_RETRIES = 2
        err = Exception("tool call validation failed")

        # Suppress first 2 (within limit)
        await callback.on_chain_error(err)
        await callback.on_chain_error(err)
        assert callback.notifier.on_error.await_count == 0

        # Third call exceeds limit — should surface
        await callback.on_chain_error(err)
        callback.notifier.on_error.assert_awaited_once()
        assert callback._suppressed_error_count == 3

    @pytest.mark.asyncio
    async def test_suppressed_count_increments(self, callback):
        """Each retryable error increments the suppressed counter."""
        err = Exception("is not a valid tool")
        await callback.on_chain_error(err)
        await callback.on_chain_error(err)

        assert callback._suppressed_error_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_does_not_increment_counter(self, callback):
        """Non-retryable errors do not affect the suppressed counter."""
        await callback.on_chain_error(Exception("some other error"))
        assert callback._suppressed_error_count == 0

    @pytest.mark.asyncio
    async def test_logging_escalates_past_half_limit(self, callback):
        """After half the limit, suppression logs at WARNING instead of DEBUG."""
        err = Exception("tool call validation failed")

        # RCA_EVIDENCE_AGENT_MAX_RETRIES defaults to 2; half = 1
        # First call: count=1 > 1 (half), so should log WARNING
        # Actually: max_suppress // 2 = 1, count=1 is NOT > 1, so DEBUG
        with patch("app.chat.notifiers.web_callback.logger") as mock_logger:
            await callback.on_chain_error(err)
            mock_logger.debug.assert_called_once()
            mock_logger.warning.assert_not_called()

        with patch("app.chat.notifiers.web_callback.logger") as mock_logger:
            # count=2 > half(1), so WARNING
            await callback.on_chain_error(err)
            mock_logger.warning.assert_called_once()
            mock_logger.debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_not_a_valid_tool_pattern_matched(self, callback):
        """'is not a valid tool' pattern is correctly detected as retryable."""
        err = Exception("fetch_logs is not a valid tool, try another one")
        await callback.on_chain_error(err)

        callback.notifier.on_error.assert_not_awaited()
        assert callback._suppressed_error_count == 1

    @pytest.mark.asyncio
    async def test_error_message_truncated_to_500(self, callback):
        """Non-retryable error messages forwarded to notifier are truncated."""
        long_msg = "x" * 1000
        await callback.on_chain_error(Exception(long_msg))

        call_args = callback.notifier.on_error.call_args[0][0]
        assert len(call_args) == 500
