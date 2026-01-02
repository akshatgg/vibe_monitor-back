"""
Unit tests for LogsService.

Tests pure functions and validation logic. DB-heavy operations
belong in integration tests.

Tests are organized by method and cover:
- Happy path scenarios
- Edge cases
- Error handling
- Input validation
"""

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.log.service import LogsService


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def logs_service():
    """Create LogsService instance for testing."""
    return LogsService()


# =============================================================================
# Tests: _escape_logql_value (Pure Function)
# =============================================================================


class TestEscapeLogqlValue:
    """Tests for _escape_logql_value - LogQL injection prevention."""

    def test_escape_logql_value_with_normal_string(self, logs_service):
        result = logs_service._escape_logql_value("api-gateway")
        assert result == "api-gateway"

    def test_escape_logql_value_escapes_backslash(self, logs_service):
        result = logs_service._escape_logql_value("path\\to\\file")
        assert result == "path\\\\to\\\\file"

    def test_escape_logql_value_escapes_double_quotes(self, logs_service):
        result = logs_service._escape_logql_value('service="test"')
        assert result == 'service=\\"test\\"'

    def test_escape_logql_value_escapes_mixed_special_chars(self, logs_service):
        result = logs_service._escape_logql_value('test\\"injection')
        assert result == 'test\\\\\\"injection'

    def test_escape_logql_value_with_empty_string(self, logs_service):
        result = logs_service._escape_logql_value("")
        assert result == ""

    def test_escape_logql_value_with_none(self, logs_service):
        result = logs_service._escape_logql_value(None)
        assert result is None

    def test_escape_logql_value_preserves_alphanumeric(self, logs_service):
        result = logs_service._escape_logql_value("Service123")
        assert result == "Service123"

    def test_escape_logql_value_preserves_common_chars(self, logs_service):
        result = logs_service._escape_logql_value("service-name_v1.0")
        assert result == "service-name_v1.0"


# =============================================================================
# Tests: _escape_regex (Pure Function)
# =============================================================================


class TestEscapeRegex:
    """Tests for _escape_regex - regex injection/ReDoS prevention."""

    def test_escape_regex_with_normal_string(self, logs_service):
        result = logs_service._escape_regex("error")
        assert result == "error"

    def test_escape_regex_escapes_dot(self, logs_service):
        result = logs_service._escape_regex("file.txt")
        assert result == r"file\.txt"

    def test_escape_regex_escapes_asterisk(self, logs_service):
        result = logs_service._escape_regex("test*")
        assert result == r"test\*"

    def test_escape_regex_escapes_question_mark(self, logs_service):
        result = logs_service._escape_regex("test?")
        assert result == r"test\?"

    def test_escape_regex_escapes_brackets(self, logs_service):
        result = logs_service._escape_regex("[test]")
        assert result == r"\[test\]"

    def test_escape_regex_escapes_parentheses(self, logs_service):
        result = logs_service._escape_regex("(test)")
        assert result == r"\(test\)"

    def test_escape_regex_escapes_caret(self, logs_service):
        result = logs_service._escape_regex("^start")
        assert result == r"\^start"

    def test_escape_regex_escapes_dollar(self, logs_service):
        result = logs_service._escape_regex("end$")
        assert result == r"end\$"

    def test_escape_regex_escapes_pipe(self, logs_service):
        result = logs_service._escape_regex("a|b")
        assert result == r"a\|b"

    def test_escape_regex_escapes_plus(self, logs_service):
        result = logs_service._escape_regex("a+")
        assert result == r"a\+"

    def test_escape_regex_escapes_complex_pattern(self, logs_service):
        result = logs_service._escape_regex(".*+?^$[](){}|\\")
        # All regex metacharacters should be escaped
        assert "\\" in result

    def test_escape_regex_with_empty_string(self, logs_service):
        result = logs_service._escape_regex("")
        assert result == ""

    def test_escape_regex_with_none(self, logs_service):
        result = logs_service._escape_regex(None)
        assert result is None


# =============================================================================
# Tests: _format_time (Pure Function)
# =============================================================================


class TestFormatTime:
    """Tests for _format_time - time value formatting for Loki API."""

    def test_format_time_with_datetime_object(self, logs_service):
        dt = datetime(2025, 1, 15, 10, 30, 45, 123456, tzinfo=timezone.utc)
        result = logs_service._format_time(dt)
        assert result == "2025-01-15T10:30:45.123456000Z"

    def test_format_time_with_now_string(self, logs_service):
        with patch("app.log.service.datetime") as mock_datetime:
            mock_now = datetime(2025, 1, 15, 12, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = mock_now
            mock_datetime.strftime = datetime.strftime

            result = logs_service._format_time("now")
            assert "2025-01-15T12:00:00" in result

    def test_format_time_with_relative_seconds(self, logs_service):
        with patch("app.log.service.datetime") as mock_datetime:
            mock_now = datetime(2025, 1, 15, 12, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = logs_service._format_time("now-30s")
            # Should be 30 seconds before mock_now
            assert "2025-01-15T11:59:30" in result

    def test_format_time_with_relative_minutes(self, logs_service):
        with patch("app.log.service.datetime") as mock_datetime:
            mock_now = datetime(2025, 1, 15, 12, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = logs_service._format_time("now-5m")
            assert "2025-01-15T11:55:00" in result

    def test_format_time_with_relative_hours(self, logs_service):
        with patch("app.log.service.datetime") as mock_datetime:
            mock_now = datetime(2025, 1, 15, 12, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = logs_service._format_time("now-2h")
            assert "2025-01-15T10:00:00" in result

    def test_format_time_with_relative_days(self, logs_service):
        with patch("app.log.service.datetime") as mock_datetime:
            mock_now = datetime(2025, 1, 15, 12, 0, 0, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = mock_now
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = logs_service._format_time("now-1d")
            assert "2025-01-14T12:00:00" in result

    def test_format_time_with_rfc3339_string_passthrough(self, logs_service):
        time_str = "2025-01-15T10:30:45.000000000Z"
        result = logs_service._format_time(time_str)
        assert result == time_str


# =============================================================================
# Tests: _build_logql_query (Pure Function)
# =============================================================================


class TestBuildLogqlQuery:
    """Tests for _build_logql_query - LogQL query construction."""

    def test_build_logql_query_with_service_name(self, logs_service):
        result = logs_service._build_logql_query(service_name="api-gateway")
        assert result == '{job="api-gateway"}'

    def test_build_logql_query_with_custom_label_key(self, logs_service):
        result = logs_service._build_logql_query(
            service_name="api-gateway", service_label_key="service_name"
        )
        assert result == '{service_name="api-gateway"}'

    def test_build_logql_query_with_filters(self, logs_service):
        result = logs_service._build_logql_query(
            service_name="api-gateway", filters={"env": "prod", "region": "us-west"}
        )
        assert 'job="api-gateway"' in result
        assert 'env="prod"' in result
        assert 'region="us-west"' in result

    def test_build_logql_query_with_search_term(self, logs_service):
        result = logs_service._build_logql_query(
            service_name="api-gateway", search_term="error"
        )
        assert '{job="api-gateway"}' in result
        assert '|= "error"' in result

    def test_build_logql_query_no_service_matches_all(self, logs_service):
        result = logs_service._build_logql_query()
        assert result == '{job=~".+"}'

    def test_build_logql_query_escapes_service_name(self, logs_service):
        result = logs_service._build_logql_query(service_name='test"injection')
        assert 'job="test\\"injection"' in result

    def test_build_logql_query_escapes_filter_values(self, logs_service):
        result = logs_service._build_logql_query(filters={"env": 'prod"test'})
        assert 'env="prod\\"test"' in result

    def test_build_logql_query_escapes_search_term(self, logs_service):
        result = logs_service._build_logql_query(search_term='error"test')
        assert '|= "error\\"test"' in result

    def test_build_logql_query_full_example(self, logs_service):
        result = logs_service._build_logql_query(
            service_name="api-gateway",
            filters={"level": "error"},
            search_term="timeout",
            service_label_key="app",
        )
        assert 'app="api-gateway"' in result
        assert 'level="error"' in result
        assert '|= "timeout"' in result


# =============================================================================
# Tests: _get_headers (Pure Function)
# =============================================================================


class TestGetHeaders:
    """Tests for _get_headers - HTTP header construction."""

    def test_get_headers_with_token(self, logs_service):
        result = logs_service._get_headers("my-api-token")
        assert result["Content-Type"] == "application/json"
        assert result["Authorization"] == "Bearer my-api-token"

    def test_get_headers_without_token(self, logs_service):
        result = logs_service._get_headers("")
        assert result["Content-Type"] == "application/json"
        assert "Authorization" not in result

    def test_get_headers_with_none_token(self, logs_service):
        result = logs_service._get_headers(None)
        assert result["Content-Type"] == "application/json"
        assert "Authorization" not in result


# =============================================================================
# Integration tests for helper method combinations
# =============================================================================


class TestLogqlQueryIntegration:
    """Integration tests combining multiple helper methods."""

    def test_build_query_with_escaped_injection_attempt(self, logs_service):
        """Verify LogQL injection attempts are properly escaped."""
        # Attempt to inject additional query operators
        malicious_service = 'api"} | line_format "{{.}}" # '
        result = logs_service._build_logql_query(service_name=malicious_service)

        # The injection should be escaped, not executed
        assert '|' not in result.split('{')[0]  # No pipe before first brace
        assert '\\"' in result  # Quotes should be escaped

    def test_build_query_prevents_redos_attack(self, logs_service):
        """Verify regex patterns that could cause ReDoS are escaped."""
        malicious_pattern = "(a+)+" * 10  # Classic ReDoS pattern
        escaped = logs_service._escape_regex(malicious_pattern)

        # All + characters should be escaped
        assert escaped.count("\\+") == 10
        assert escaped.count("+") == escaped.count("\\+")
