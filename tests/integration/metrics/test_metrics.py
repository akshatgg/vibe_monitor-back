"""
Integration tests for metrics endpoints.

Tests the metrics query API endpoints (available in local environment):
- GET  /api/v1/metrics/health
- GET  /api/v1/metrics/labels
- GET  /api/v1/metrics/labels/{label_name}/values
- GET  /api/v1/metrics/names
- GET  /api/v1/metrics/targets
- POST /api/v1/metrics/query/instant
- POST /api/v1/metrics/query/range
- GET  /api/v1/metrics/cpu
- GET  /api/v1/metrics/memory
- GET  /api/v1/metrics/http/requests
- GET  /api/v1/metrics/http/latency
- GET  /api/v1/metrics/errors
- GET  /api/v1/metrics/throughput
- GET  /api/v1/metrics/availability

NOTE: These routes are only registered when settings.is_local is True.
Tests mock the metrics_service to avoid requiring a real Grafana/Prometheus instance.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.metrics.models import (
    InstantMetricResponse,
    LabelResponse,
    MetricSeries,
    MetricValue,
    RangeMetricResponse,
    TargetsResponse,
)


# =============================================================================
# Test Constants
# =============================================================================

API_PREFIX = "/api/v1/metrics"
TEST_WORKSPACE_ID = "test-workspace-123"


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_metrics_service():
    """Fixture to mock the metrics service."""
    with patch("app.metrics.router.metrics_service") as mock:
        # Configure default mock returns
        mock.health_check = AsyncMock(return_value=True)
        mock.get_all_labels = AsyncMock(
            return_value=LabelResponse(
                status="success",
                data=["__name__", "job", "instance", "service_name"],
            )
        )
        mock.get_label_values = AsyncMock(
            return_value=LabelResponse(
                status="success",
                data=["api-gateway", "user-service", "payment-service"],
            )
        )
        mock.get_all_metric_names = AsyncMock(
            return_value=[
                "http_requests_total",
                "http_request_duration_seconds",
                "process_cpu_seconds_total",
                "process_resident_memory_bytes",
            ]
        )
        mock.get_targets_status = AsyncMock(
            return_value=TargetsResponse(
                status="success",
                data={"activeTargets": [], "droppedTargets": []},
            )
        )
        mock.get_instant_metrics = AsyncMock(
            return_value=InstantMetricResponse(
                status="success",
                data={},
                metric_name="test_metric",
                result_type="vector",
                result=[],
            )
        )
        mock.get_range_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="test_metric",
                result_type="matrix",
                result=[],
            )
        )
        mock.get_cpu_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="cpu_usage",
                result_type="matrix",
                result=[],
            )
        )
        mock.get_memory_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="memory_usage",
                result_type="matrix",
                result=[],
            )
        )
        mock.get_http_request_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="http_requests",
                result_type="matrix",
                result=[],
            )
        )
        mock.get_http_latency_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="http_latency",
                result_type="matrix",
                result=[],
            )
        )
        mock.get_error_rate_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="error_rate",
                result_type="matrix",
                result=[],
            )
        )
        mock.get_throughput_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="throughput",
                result_type="matrix",
                result=[],
            )
        )
        mock.get_availability_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="availability",
                result_type="matrix",
                result=[],
            )
        )
        yield mock


# =============================================================================
# Standalone Function Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_metrics_health_func():
    """Test the standalone metrics health check function."""
    from app.metrics.router import get_metrics_health_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.health_check = AsyncMock(return_value=True)

        result = await get_metrics_health_func(TEST_WORKSPACE_ID)

        assert result.status == "healthy"
        assert result.provider_type == "GrafanaProvider"
        assert result.provider_healthy is True


@pytest.mark.asyncio
async def test_get_metrics_health_func_unhealthy():
    """Test the standalone metrics health check when provider is unhealthy."""
    from app.metrics.router import get_metrics_health_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.health_check = AsyncMock(return_value=False)

        result = await get_metrics_health_func(TEST_WORKSPACE_ID)

        assert result.status == "unhealthy"
        assert result.provider_healthy is False


@pytest.mark.asyncio
async def test_get_metric_labels_func():
    """Test the standalone get metric labels function."""
    from app.metrics.router import get_metric_labels_func

    expected_labels = ["__name__", "job", "instance", "service_name"]

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_all_labels = AsyncMock(
            return_value=LabelResponse(status="success", data=expected_labels)
        )

        result = await get_metric_labels_func(TEST_WORKSPACE_ID)

        assert result.status == "success"
        assert result.data == expected_labels


@pytest.mark.asyncio
async def test_get_label_values_func():
    """Test the standalone get label values function."""
    from app.metrics.router import get_label_values_func

    label_name = "service_name"
    expected_values = ["api-gateway", "user-service", "payment-service"]

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_label_values = AsyncMock(
            return_value=LabelResponse(status="success", data=expected_values)
        )

        result = await get_label_values_func(TEST_WORKSPACE_ID, label_name)

        assert result.status == "success"
        assert result.data == expected_values


@pytest.mark.asyncio
async def test_get_metric_names_func():
    """Test the standalone get metric names function."""
    from app.metrics.router import get_metric_names_func

    expected_names = [
        "http_requests_total",
        "http_request_duration_seconds",
        "process_cpu_seconds_total",
    ]

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_all_metric_names = AsyncMock(return_value=expected_names)

        result = await get_metric_names_func(TEST_WORKSPACE_ID)

        assert result == expected_names


@pytest.mark.asyncio
async def test_get_targets_status_func():
    """Test the standalone get targets status function."""
    from app.metrics.router import get_targets_status_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_targets_status = AsyncMock(
            return_value=TargetsResponse(
                status="success",
                data={"activeTargets": [], "droppedTargets": []},
            )
        )

        result = await get_targets_status_func(TEST_WORKSPACE_ID)

        assert result.status == "success"


@pytest.mark.asyncio
async def test_query_instant_metrics_func():
    """Test the standalone query instant metrics function."""
    from app.metrics.router import CustomMetricRequest, query_instant_metrics_func

    request = CustomMetricRequest(
        metric_name="http_requests_total",
        service_name="api-gateway",
        labels={"method": "GET"},
        timeout="30s",
    )

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_instant_metrics = AsyncMock(
            return_value=InstantMetricResponse(
                status="success",
                data={},
                metric_name="http_requests_total",
                result_type="vector",
                result=[{"metric": {}, "value": [1234567890, "100"]}],
            )
        )

        result = await query_instant_metrics_func(TEST_WORKSPACE_ID, request)

        assert result.status == "success"
        assert result.metric_name == "http_requests_total"


@pytest.mark.asyncio
async def test_query_range_metrics_func():
    """Test the standalone query range metrics function."""
    from app.metrics.router import RangeMetricRequest, query_range_metrics_func

    request = RangeMetricRequest(
        metric_name="http_requests_total",
        service_name="api-gateway",
        start_time="now-1h",
        end_time="now",
        step="60s",
    )

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_range_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="http_requests_total",
                result_type="matrix",
                result=[],
            )
        )

        result = await query_range_metrics_func(TEST_WORKSPACE_ID, request)

        assert result.status == "success"


@pytest.mark.asyncio
async def test_get_cpu_metrics_func():
    """Test the standalone get CPU metrics function."""
    from app.metrics.router import get_cpu_metrics_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_cpu_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="cpu_usage",
                result_type="matrix",
                result=[
                    MetricSeries(
                        metric={"service_name": "api-gateway"},
                        values=[
                            MetricValue(
                                timestamp=datetime.now(timezone.utc), value=45.5
                            )
                        ],
                    )
                ],
            )
        )

        result = await get_cpu_metrics_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name="api-gateway",
            start_time="now-1h",
            end_time="now",
            step="60s",
        )

        assert result.status == "success"
        assert result.metric_name == "cpu_usage"


@pytest.mark.asyncio
async def test_get_memory_metrics_func():
    """Test the standalone get memory metrics function."""
    from app.metrics.router import get_memory_metrics_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_memory_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="memory_usage",
                result_type="matrix",
                result=[],
            )
        )

        result = await get_memory_metrics_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name=None,
            start_time="now-1h",
            end_time="now",
            step="60s",
        )

        assert result.status == "success"


@pytest.mark.asyncio
async def test_get_http_request_metrics_func():
    """Test the standalone get HTTP request metrics function."""
    from app.metrics.router import get_http_request_metrics_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_http_request_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="http_requests",
                result_type="matrix",
                result=[],
            )
        )

        result = await get_http_request_metrics_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name="api-gateway",
            start_time="now-1h",
            end_time="now",
            step="60s",
        )

        assert result.status == "success"


@pytest.mark.asyncio
async def test_get_http_latency_metrics_func():
    """Test the standalone get HTTP latency metrics function."""
    from app.metrics.router import get_http_latency_metrics_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_http_latency_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="http_latency_p95",
                result_type="matrix",
                result=[],
            )
        )

        result = await get_http_latency_metrics_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name="api-gateway",
            percentile=0.95,
            start_time="now-1h",
            end_time="now",
            step="60s",
        )

        assert result.status == "success"


@pytest.mark.asyncio
async def test_get_http_latency_metrics_func_invalid_percentile():
    """Test that invalid percentile raises ValueError."""
    from app.metrics.router import get_http_latency_metrics_func

    with pytest.raises(ValueError, match="Percentile must be between 0.0 and 1.0"):
        await get_http_latency_metrics_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name="api-gateway",
            percentile=1.5,  # Invalid
            start_time="now-1h",
            end_time="now",
            step="60s",
        )


@pytest.mark.asyncio
async def test_get_error_rate_metrics_func():
    """Test the standalone get error rate metrics function."""
    from app.metrics.router import get_error_rate_metrics_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_error_rate_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="error_rate",
                result_type="matrix",
                result=[],
            )
        )

        result = await get_error_rate_metrics_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name=None,
            start_time="now-1h",
            end_time="now",
            step="60s",
        )

        assert result.status == "success"


@pytest.mark.asyncio
async def test_get_throughput_metrics_func():
    """Test the standalone get throughput metrics function."""
    from app.metrics.router import get_throughput_metrics_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_throughput_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="throughput",
                result_type="matrix",
                result=[],
            )
        )

        result = await get_throughput_metrics_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name="api-gateway",
            start_time="now-1h",
            end_time="now",
            step="60s",
        )

        assert result.status == "success"


@pytest.mark.asyncio
async def test_get_availability_metrics_func():
    """Test the standalone get availability metrics function."""
    from app.metrics.router import get_availability_metrics_func

    with patch("app.metrics.router.metrics_service") as mock:
        mock.get_availability_metrics = AsyncMock(
            return_value=RangeMetricResponse(
                status="success",
                data={},
                metric_name="availability",
                result_type="matrix",
                result=[],
            )
        )

        result = await get_availability_metrics_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name="api-gateway",
            start_time="now-1h",
            end_time="now",
            step="60s",
        )

        assert result.status == "success"


# =============================================================================
# HTTP Endpoint Tests (Local Environment Only)
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_health_endpoint(client, mock_metrics_service):
    """Test the metrics health HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/health",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_metrics_labels_endpoint(client, mock_metrics_service):
    """Test the metrics labels HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/labels",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_label_values_endpoint(client, mock_metrics_service):
    """Test the metrics label values HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/labels/service_name/values",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_names_endpoint(client, mock_metrics_service):
    """Test the metrics names HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/names",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_metrics_targets_endpoint(client, mock_metrics_service):
    """Test the metrics targets HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/targets",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_query_instant_endpoint(client, mock_metrics_service):
    """Test the metrics query instant HTTP endpoint."""
    response = await client.post(
        f"{API_PREFIX}/query/instant",
        headers={"workspace-id": TEST_WORKSPACE_ID},
        json={
            "metric_name": "http_requests_total",
            "service_name": "api-gateway",
        },
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_query_range_endpoint(client, mock_metrics_service):
    """Test the metrics query range HTTP endpoint."""
    response = await client.post(
        f"{API_PREFIX}/query/range",
        headers={"workspace-id": TEST_WORKSPACE_ID},
        json={
            "metric_name": "http_requests_total",
            "start_time": "now-1h",
            "end_time": "now",
            "step": "60s",
        },
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_cpu_endpoint(client, mock_metrics_service):
    """Test the metrics CPU HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/cpu",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_memory_endpoint(client, mock_metrics_service):
    """Test the metrics memory HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/memory",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_http_requests_endpoint(client, mock_metrics_service):
    """Test the metrics HTTP requests endpoint."""
    response = await client.get(
        f"{API_PREFIX}/http/requests",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_http_latency_endpoint(client, mock_metrics_service):
    """Test the metrics HTTP latency endpoint."""
    response = await client.get(
        f"{API_PREFIX}/http/latency",
        headers={"workspace-id": TEST_WORKSPACE_ID},
        params={"percentile": 0.95},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_http_latency_invalid_percentile(client, mock_metrics_service):
    """Test the metrics HTTP latency endpoint with invalid percentile."""
    response = await client.get(
        f"{API_PREFIX}/http/latency",
        headers={"workspace-id": TEST_WORKSPACE_ID},
        params={"percentile": 1.5},  # Invalid
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_metrics_errors_endpoint(client, mock_metrics_service):
    """Test the metrics errors endpoint."""
    response = await client.get(
        f"{API_PREFIX}/errors",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_throughput_endpoint(client, mock_metrics_service):
    """Test the metrics throughput endpoint."""
    response = await client.get(
        f"{API_PREFIX}/throughput",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_availability_endpoint(client, mock_metrics_service):
    """Test the metrics availability endpoint."""
    response = await client.get(
        f"{API_PREFIX}/availability",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


# =============================================================================
# Query Parameter Tests
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_cpu_with_service_filter(client, mock_metrics_service):
    """Test CPU metrics with service name filter."""
    response = await client.get(
        f"{API_PREFIX}/cpu",
        headers={"workspace-id": TEST_WORKSPACE_ID},
        params={"service_name": "api-gateway"},
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_metrics_cpu_with_time_range(client, mock_metrics_service):
    """Test CPU metrics with custom time range."""
    response = await client.get(
        f"{API_PREFIX}/cpu",
        headers={"workspace-id": TEST_WORKSPACE_ID},
        params={
            "start_time": "now-6h",
            "end_time": "now",
            "step": "5m",
        },
    )

    if response.status_code == 404:
        pytest.skip("Metrics routes not registered (settings.is_local is False)")

    assert response.status_code == 200
