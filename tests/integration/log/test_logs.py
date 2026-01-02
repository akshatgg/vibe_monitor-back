"""
Integration tests for logs endpoints.

Tests the log query API endpoints (available in local environment):
- GET  /api/v1/logs/health
- GET  /api/v1/logs/labels
- GET  /api/v1/logs/labels/{label_name}/values
- POST /api/v1/logs/query
- POST /api/v1/logs/search
- GET  /api/v1/logs/service/{service_name}
- GET  /api/v1/logs/errors
- GET  /api/v1/logs/warnings
- GET  /api/v1/logs/info
- GET  /api/v1/logs/debug
- GET  /api/v1/logs/level/{log_level}

NOTE: These routes are only registered when settings.is_local is True.
Tests mock the logs_service to avoid requiring a real Loki instance.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.log.models import LabelResponse, LogQueryData, LogQueryResponse


# =============================================================================
# Test Constants
# =============================================================================

API_PREFIX = "/api/v1/logs"
TEST_WORKSPACE_ID = "test-workspace-123"


# =============================================================================
# Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_logs_service():
    """Fixture to mock the logs service."""
    with patch("app.log.router.logs_service") as mock:
        # Configure default mock returns
        mock.health_check = AsyncMock(return_value=True)
        mock.get_all_labels = AsyncMock(
            return_value=LabelResponse(
                status="success",
                data=["job", "level", "service_name", "trace_id"],
            )
        )
        mock.get_label_values = AsyncMock(
            return_value=LabelResponse(
                status="success",
                data=["api-gateway", "user-service", "payment-service"],
            )
        )
        mock.query_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )
        mock.search_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )
        mock.get_logs_by_service = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )
        mock.get_error_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )
        mock.get_warning_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )
        mock.get_info_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )
        mock.get_debug_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )
        mock.get_logs_by_level = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )
        yield mock


# =============================================================================
# Standalone Function Tests
# =============================================================================

# NOTE: The log router conditionally registers routes only when settings.is_local.
# In non-local environments, only the standalone functions are available.
# These tests focus on the standalone functions that are always available.


@pytest.mark.asyncio
async def test_get_logs_health_func():
    """Test the standalone logs health check function."""
    from app.log.router import get_logs_health_func

    with patch("app.log.router.logs_service") as mock:
        mock.health_check = AsyncMock(return_value=True)

        result = await get_logs_health_func(TEST_WORKSPACE_ID)

        assert result.status == "healthy"
        assert result.provider_type == "LokiProvider"
        assert result.provider_healthy is True
        mock.health_check.assert_called_once_with(TEST_WORKSPACE_ID)


@pytest.mark.asyncio
async def test_get_logs_health_func_unhealthy():
    """Test the standalone logs health check function when provider is unhealthy."""
    from app.log.router import get_logs_health_func

    with patch("app.log.router.logs_service") as mock:
        mock.health_check = AsyncMock(return_value=False)

        result = await get_logs_health_func(TEST_WORKSPACE_ID)

        assert result.status == "unhealthy"
        assert result.provider_healthy is False


@pytest.mark.asyncio
async def test_get_log_labels_func():
    """Test the standalone get log labels function."""
    from app.log.router import get_log_labels_func

    expected_labels = ["job", "level", "service_name", "trace_id"]

    with patch("app.log.router.logs_service") as mock:
        mock.get_all_labels = AsyncMock(
            return_value=LabelResponse(status="success", data=expected_labels)
        )

        result = await get_log_labels_func(TEST_WORKSPACE_ID)

        assert result.status == "success"
        assert result.data == expected_labels
        mock.get_all_labels.assert_called_once_with(TEST_WORKSPACE_ID)


@pytest.mark.asyncio
async def test_get_label_values_func():
    """Test the standalone get label values function."""
    from app.log.router import get_label_values_func

    label_name = "service_name"
    expected_values = ["api-gateway", "user-service", "payment-service"]

    with patch("app.log.router.logs_service") as mock:
        mock.get_label_values = AsyncMock(
            return_value=LabelResponse(status="success", data=expected_values)
        )

        result = await get_label_values_func(TEST_WORKSPACE_ID, label_name)

        assert result.status == "success"
        assert result.data == expected_values
        mock.get_label_values.assert_called_once_with(TEST_WORKSPACE_ID, label_name)


@pytest.mark.asyncio
async def test_query_logs_func():
    """Test the standalone query logs function."""
    from app.log.router import LogsQueryRequest, query_logs_func

    request = LogsQueryRequest(
        query='{job="test"}',
        start="now-1h",
        end="now",
        limit=100,
        direction="BACKWARD",
    )

    with patch("app.log.router.logs_service") as mock:
        mock.query_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[
                        {
                            "stream": {"job": "test"},
                            "values": [["1234567890000000000", "test log line"]],
                        }
                    ],
                    stats=None,
                ),
            )
        )

        result = await query_logs_func(TEST_WORKSPACE_ID, request)

        assert result.status == "success"
        assert result.data.resultType == "streams"
        mock.query_logs.assert_called_once()


@pytest.mark.asyncio
async def test_search_logs_func():
    """Test the standalone search logs function."""
    from app.log.router import LogsSearchRequest, search_logs_func

    request = LogsSearchRequest(
        search_term="error",
        service_name="api-gateway",
        start="now-1h",
        end="now",
        limit=50,
    )

    with patch("app.log.router.logs_service") as mock:
        mock.search_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )

        result = await search_logs_func(TEST_WORKSPACE_ID, request)

        assert result.status == "success"
        mock.search_logs.assert_called_once()


@pytest.mark.asyncio
async def test_get_service_logs_func():
    """Test the standalone get service logs function."""
    from app.log.router import get_service_logs_func

    with patch("app.log.router.logs_service") as mock:
        mock.get_logs_by_service = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )

        result = await get_service_logs_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name="api-gateway",
            start="now-1h",
            end="now",
            limit=100,
            direction="BACKWARD",
        )

        assert result.status == "success"
        mock.get_logs_by_service.assert_called_once()


@pytest.mark.asyncio
async def test_get_error_logs_func():
    """Test the standalone get error logs function."""
    from app.log.router import get_error_logs_func

    with patch("app.log.router.logs_service") as mock:
        mock.get_error_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )

        result = await get_error_logs_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name="api-gateway",
            start="now-1h",
            end="now",
            limit=100,
        )

        assert result.status == "success"
        mock.get_error_logs.assert_called_once()


@pytest.mark.asyncio
async def test_get_warning_logs_func():
    """Test the standalone get warning logs function."""
    from app.log.router import get_warning_logs_func

    with patch("app.log.router.logs_service") as mock:
        mock.get_warning_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )

        result = await get_warning_logs_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name=None,
            start="now-1h",
            end="now",
            limit=100,
        )

        assert result.status == "success"
        mock.get_warning_logs.assert_called_once()


@pytest.mark.asyncio
async def test_get_info_logs_func():
    """Test the standalone get info logs function."""
    from app.log.router import get_info_logs_func

    with patch("app.log.router.logs_service") as mock:
        mock.get_info_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )

        result = await get_info_logs_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name=None,
            start="now-1h",
            end="now",
            limit=100,
        )

        assert result.status == "success"
        mock.get_info_logs.assert_called_once()


@pytest.mark.asyncio
async def test_get_debug_logs_func():
    """Test the standalone get debug logs function."""
    from app.log.router import get_debug_logs_func

    with patch("app.log.router.logs_service") as mock:
        mock.get_debug_logs = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )

        result = await get_debug_logs_func(
            workspace_id=TEST_WORKSPACE_ID,
            service_name=None,
            start="now-1h",
            end="now",
            limit=100,
        )

        assert result.status == "success"
        mock.get_debug_logs.assert_called_once()


@pytest.mark.asyncio
async def test_get_logs_by_level_func():
    """Test the standalone get logs by level function."""
    from app.log.router import get_logs_by_level_func

    with patch("app.log.router.logs_service") as mock:
        mock.get_logs_by_level = AsyncMock(
            return_value=LogQueryResponse(
                status="success",
                data=LogQueryData(
                    resultType="streams",
                    result=[],
                    stats=None,
                ),
            )
        )

        result = await get_logs_by_level_func(
            workspace_id=TEST_WORKSPACE_ID,
            log_level="trace",
            service_name=None,
            start="now-1h",
            end="now",
            limit=100,
        )

        assert result.status == "success"
        mock.get_logs_by_level.assert_called_once()


# =============================================================================
# HTTP Endpoint Tests (Local Environment Only)
# =============================================================================

# These tests verify the HTTP endpoints when routes are registered.
# They require settings.is_local to be True.


@pytest.mark.asyncio
async def test_logs_health_endpoint(client, mock_logs_service):
    """Test the logs health HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/health",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    # Route may not be registered if not in local env
    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["provider_type"] == "LokiProvider"


@pytest.mark.asyncio
async def test_logs_labels_endpoint(client, mock_logs_service):
    """Test the logs labels HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/labels",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_logs_label_values_endpoint(client, mock_logs_service):
    """Test the logs label values HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/labels/service_name/values",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_logs_query_endpoint(client, mock_logs_service):
    """Test the logs query HTTP endpoint."""
    response = await client.post(
        f"{API_PREFIX}/query",
        headers={"workspace-id": TEST_WORKSPACE_ID},
        json={
            "query": '{job="test"}',
            "start": "now-1h",
            "end": "now",
            "limit": 100,
        },
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_logs_search_endpoint(client, mock_logs_service):
    """Test the logs search HTTP endpoint."""
    response = await client.post(
        f"{API_PREFIX}/search",
        headers={"workspace-id": TEST_WORKSPACE_ID},
        json={
            "search_term": "error",
            "start": "now-1h",
            "end": "now",
        },
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_logs_service_endpoint(client, mock_logs_service):
    """Test the logs service HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/service/api-gateway",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logs_errors_endpoint(client, mock_logs_service):
    """Test the logs errors HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/errors",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logs_warnings_endpoint(client, mock_logs_service):
    """Test the logs warnings HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/warnings",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logs_info_endpoint(client, mock_logs_service):
    """Test the logs info HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/info",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logs_debug_endpoint(client, mock_logs_service):
    """Test the logs debug HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/debug",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logs_level_endpoint(client, mock_logs_service):
    """Test the logs by level HTTP endpoint."""
    response = await client.get(
        f"{API_PREFIX}/level/trace",
        headers={"workspace-id": TEST_WORKSPACE_ID},
    )

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 200


# =============================================================================
# Missing Workspace ID Tests
# =============================================================================


@pytest.mark.asyncio
async def test_logs_labels_missing_workspace_id(client, mock_logs_service):
    """Test that missing workspace-id header returns 422."""
    response = await client.get(f"{API_PREFIX}/labels")

    if response.status_code == 404:
        pytest.skip("Logs routes not registered (settings.is_local is False)")

    assert response.status_code == 422  # Validation error
