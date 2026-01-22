"""
Unit tests for MetricsService.

Tests pure functions and validation logic. DB-heavy operations
belong in integration tests.

Tests are organized by method and cover:
- Happy path scenarios
- Edge cases
- Error handling
- Input validation
"""

from datetime import datetime, timezone

import pytest

from app.metrics.service import MetricsService


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def metrics_service():
    """Create MetricsService instance for testing."""
    return MetricsService()


# =============================================================================
# Tests: _escape_promql_value (Pure Function)
# =============================================================================


class TestEscapePromqlValue:
    """Tests for _escape_promql_value - PromQL injection prevention."""

    def test_escape_promql_value_with_normal_string(self, metrics_service):
        result = metrics_service._escape_promql_value("api-gateway")
        assert result == "api-gateway"

    def test_escape_promql_value_escapes_backslash(self, metrics_service):
        result = metrics_service._escape_promql_value("path\\to\\file")
        assert result == "path\\\\to\\\\file"

    def test_escape_promql_value_escapes_double_quotes(self, metrics_service):
        result = metrics_service._escape_promql_value('service="test"')
        assert result == 'service=\\"test\\"'

    def test_escape_promql_value_escapes_mixed_special_chars(self, metrics_service):
        result = metrics_service._escape_promql_value('test\\"injection')
        assert result == 'test\\\\\\"injection'

    def test_escape_promql_value_with_empty_string(self, metrics_service):
        result = metrics_service._escape_promql_value("")
        assert result == ""

    def test_escape_promql_value_with_none(self, metrics_service):
        result = metrics_service._escape_promql_value(None)
        assert result is None

    def test_escape_promql_value_preserves_alphanumeric(self, metrics_service):
        result = metrics_service._escape_promql_value("Service123")
        assert result == "Service123"

    def test_escape_promql_value_preserves_common_chars(self, metrics_service):
        result = metrics_service._escape_promql_value("service-name_v1.0")
        assert result == "service-name_v1.0"


# =============================================================================
# Tests: _get_headers (Pure Function)
# =============================================================================


class TestGetHeaders:
    """Tests for _get_headers - HTTP header construction."""

    def test_get_headers_with_token(self, metrics_service):
        result = metrics_service._get_headers("my-api-token")
        assert result["Content-Type"] == "application/json"
        assert result["Authorization"] == "Bearer my-api-token"

    def test_get_headers_without_token(self, metrics_service):
        result = metrics_service._get_headers("")
        assert result["Content-Type"] == "application/json"
        assert "Authorization" not in result

    def test_get_headers_with_none_token(self, metrics_service):
        result = metrics_service._get_headers(None)
        assert result["Content-Type"] == "application/json"
        assert "Authorization" not in result


# =============================================================================
# Tests: _format_time (Pure Function)
# =============================================================================


class TestFormatTime:
    """Tests for _format_time - time value formatting for Grafana API."""

    def test_format_time_with_datetime_object(self, metrics_service):
        dt = datetime(2025, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
        result = metrics_service._format_time(dt)
        # Should return milliseconds since epoch
        expected = int(dt.timestamp() * 1000)
        assert result == expected

    def test_format_time_with_now_string(self, metrics_service):
        # Test that "now" returns a valid milliseconds timestamp
        result = metrics_service._format_time("now")
        assert isinstance(result, int)
        assert result > 0
        # Should be a reasonable timestamp (after year 2020)
        assert result > 1577836800000  # Jan 1, 2020 in ms

    def test_format_time_with_relative_seconds(self, metrics_service):
        # Test relative time parsing for seconds
        now_result = metrics_service._format_time("now")
        past_result = metrics_service._format_time("now-30s")
        # Past should be less than now
        assert past_result < now_result
        # Difference should be approximately 30 seconds (30000 ms)
        assert 25000 < (now_result - past_result) < 35000

    def test_format_time_with_relative_minutes(self, metrics_service):
        # Test relative time parsing for minutes
        now_result = metrics_service._format_time("now")
        past_result = metrics_service._format_time("now-5m")
        # Past should be less than now
        assert past_result < now_result
        # Difference should be approximately 5 minutes (300000 ms)
        assert 290000 < (now_result - past_result) < 310000

    def test_format_time_with_relative_hours(self, metrics_service):
        # Test relative time parsing for hours
        now_result = metrics_service._format_time("now")
        past_result = metrics_service._format_time("now-2h")
        # Past should be less than now
        assert past_result < now_result
        # Difference should be approximately 2 hours (7200000 ms)
        assert 7100000 < (now_result - past_result) < 7300000

    def test_format_time_with_relative_days(self, metrics_service):
        # Test relative time parsing for days
        now_result = metrics_service._format_time("now")
        past_result = metrics_service._format_time("now-1d")
        # Past should be less than now
        assert past_result < now_result
        # Difference should be approximately 1 day (86400000 ms)
        assert 86300000 < (now_result - past_result) < 86500000

    def test_format_time_with_integer(self, metrics_service):
        timestamp = 1705319400000  # Milliseconds
        result = metrics_service._format_time(timestamp)
        assert result == timestamp

    def test_format_time_with_float(self, metrics_service):
        timestamp = 1705319400000.5
        result = metrics_service._format_time(timestamp)
        assert result == 1705319400000

    def test_format_time_with_numeric_string(self, metrics_service):
        result = metrics_service._format_time("1705319400000")
        assert result == 1705319400000

    def test_format_time_with_invalid_string_raises_error(self, metrics_service):
        with pytest.raises(ValueError) as exc_info:
            metrics_service._format_time("invalid-time")
        assert "Invalid time_value" in str(exc_info.value)


# =============================================================================
# Tests: _build_label_filter (Pure Function)
# =============================================================================


class TestBuildLabelFilter:
    """Tests for _build_label_filter - PromQL label filter construction."""

    def test_build_label_filter_with_service_name(self, metrics_service):
        result = metrics_service._build_label_filter(service_name="api-gateway")
        assert result == '{job="api-gateway"}'

    def test_build_label_filter_with_labels(self, metrics_service):
        result = metrics_service._build_label_filter(
            labels={"env": "prod", "region": "us-west"}
        )
        assert 'env="prod"' in result
        assert 'region="us-west"' in result

    def test_build_label_filter_with_service_and_labels(self, metrics_service):
        result = metrics_service._build_label_filter(
            service_name="api-gateway", labels={"env": "prod"}
        )
        assert 'job="api-gateway"' in result
        assert 'env="prod"' in result

    def test_build_label_filter_empty_returns_empty_string(self, metrics_service):
        result = metrics_service._build_label_filter()
        assert result == ""

    def test_build_label_filter_escapes_service_name(self, metrics_service):
        result = metrics_service._build_label_filter(service_name='test"injection')
        assert 'job="test\\"injection"' in result

    def test_build_label_filter_escapes_label_values(self, metrics_service):
        result = metrics_service._build_label_filter(labels={"env": 'prod"test'})
        assert 'env="prod\\"test"' in result


# =============================================================================
# Tests: _build_promql_query (Pure Function)
# =============================================================================


class TestBuildPromqlQuery:
    """Tests for _build_promql_query - PromQL query construction."""

    def test_build_promql_query_simple_metric(self, metrics_service):
        result = metrics_service._build_promql_query("http_requests_total")
        assert result == "http_requests_total"

    def test_build_promql_query_with_service_name(self, metrics_service):
        result = metrics_service._build_promql_query(
            "http_requests_total", service_name="api-gateway"
        )
        assert result == 'http_requests_total{job="api-gateway"}'

    def test_build_promql_query_with_labels(self, metrics_service):
        result = metrics_service._build_promql_query(
            "http_requests_total", labels={"status": "200", "method": "GET"}
        )
        assert 'status="200"' in result
        assert 'method="GET"' in result

    def test_build_promql_query_with_aggregation(self, metrics_service):
        result = metrics_service._build_promql_query(
            "http_requests_total", aggregation="sum"
        )
        assert result == "sum(http_requests_total)"

    def test_build_promql_query_full_example(self, metrics_service):
        result = metrics_service._build_promql_query(
            "http_requests_total",
            service_name="api-gateway",
            labels={"status": "200"},
            aggregation="rate",
        )
        assert "rate(" in result
        assert "http_requests_total" in result
        assert 'job="api-gateway"' in result
        assert 'status="200"' in result

    def test_build_promql_query_escapes_injection(self, metrics_service):
        """Verify PromQL injection attempts are properly escaped."""
        malicious_service = 'api"} or vector(1) # '
        result = metrics_service._build_promql_query(
            "http_requests_total", service_name=malicious_service
        )

        # The injection should be escaped
        assert '\\"' in result


# =============================================================================
# Integration tests for helper method combinations
# =============================================================================


class TestPromqlQueryIntegration:
    """Integration tests combining multiple helper methods."""

    def test_build_query_with_escaped_injection_attempt(self, metrics_service):
        """Verify PromQL injection attempts are properly escaped."""
        malicious_service = 'api"} or up{job="'
        result = metrics_service._build_promql_query(
            "http_requests_total", service_name=malicious_service
        )

        # Should not contain unescaped quotes that could break out of label
        # Count should be: opening quote + escaped quotes + closing quote
        assert result.count('="') == 1  # Only one label value opening

    def test_format_time_and_build_query_workflow(self, metrics_service):
        """Test typical workflow of formatting time and building query."""
        query = metrics_service._build_promql_query(
            "http_requests_total", service_name="api-gateway", aggregation="rate"
        )

        assert query == 'rate(http_requests_total{job="api-gateway"})'

        # Format time values
        dt = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        formatted = metrics_service._format_time(dt)
        assert isinstance(formatted, int)
        assert formatted > 0
