"""
Integration tests for New Relic Metrics endpoints.

Tests the following OPEN endpoints (no authentication required):
- POST /api/v1/newrelic/metrics/query - Query metrics using NRQL
- POST /api/v1/newrelic/metrics/timeseries - Get time series metrics
- POST /api/v1/newrelic/metrics/infrastructure - Get infrastructure metrics
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Integration, NewRelicIntegration, Workspace, WorkspaceType

API_PREFIX = "/api/v1"


# =============================================================================
# Helper Functions
# =============================================================================


async def create_test_workspace_with_newrelic(test_db) -> tuple[Workspace, str]:
    """Create a workspace with New Relic integration for testing."""
    workspace_id = str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)

    # Create control plane integration
    integration_id = str(uuid.uuid4())
    control_plane = Integration(
        id=integration_id,
        workspace_id=workspace_id,
        provider="newrelic",
        status="active",
    )
    test_db.add(control_plane)

    # Create New Relic integration
    newrelic_integration = NewRelicIntegration(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        integration_id=integration_id,
        account_id="1234567",
        api_key="encrypted_api_key",
    )
    test_db.add(newrelic_integration)

    await test_db.commit()
    return workspace, workspace_id


# =============================================================================
# Test: Query Metrics (NRQL)
# =============================================================================


@pytest.mark.asyncio
async def test_query_metrics_success(client, test_db):
    """Test successful metrics query using NRQL."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {"average.duration": 0.234, "appName": "my-app"},
                            {"average.duration": 0.567, "appName": "other-app"},
                        ],
                        "metadata": {
                            "eventTypes": ["Transaction"],
                            "timeWindow": {"end": 1704153600, "start": 1704067200},
                        },
                    }
                }
            }
        }
    }

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_graphql_response

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/query",
            params={"workspace_id": workspace_id},
            json={
                "nrql_query": "SELECT average(duration) FROM Transaction FACET appName SINCE 1 hour ago"
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 2
    assert len(data["results"]) == 2


@pytest.mark.asyncio
async def test_query_metrics_timeseries(client, test_db):
    """Test metrics query with TIMESERIES."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {
                                "beginTimeSeconds": 1704067200,
                                "endTimeSeconds": 1704070800,
                                "average.duration": 0.234,
                            },
                            {
                                "beginTimeSeconds": 1704070800,
                                "endTimeSeconds": 1704074400,
                                "average.duration": 0.256,
                            },
                        ],
                        "metadata": {"eventTypes": ["Transaction"]},
                    }
                }
            }
        }
    }

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_graphql_response

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/query",
            params={"workspace_id": workspace_id},
            json={
                "nrql_query": "SELECT average(duration) FROM Transaction TIMESERIES SINCE 1 hour ago"
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 2


@pytest.mark.asyncio
async def test_query_metrics_no_integration(client, test_db):
    """Test metrics query fails when no integration exists."""
    workspace_id = str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.commit()

    with patch(
        "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/query",
            params={"workspace_id": workspace_id},
            json={
                "nrql_query": "SELECT average(duration) FROM Transaction SINCE 1 hour ago"
            },
        )

    assert response.status_code == 500


# =============================================================================
# Test: Time Series Metrics
# =============================================================================


@pytest.mark.asyncio
async def test_get_timeseries_success(client, test_db):
    """Test successful time series metrics query."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {
                                "beginTimeSeconds": 1704067200,
                                "endTimeSeconds": 1704070800,
                                "average.duration": 0.234,
                            },
                            {
                                "beginTimeSeconds": 1704070800,
                                "endTimeSeconds": 1704074400,
                                "average.duration": 0.256,
                            },
                            {
                                "beginTimeSeconds": 1704074400,
                                "endTimeSeconds": 1704078000,
                                "average.duration": 0.245,
                            },
                        ],
                        "metadata": {"eventTypes": ["Transaction"]},
                    }
                }
            }
        }
    }

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_graphql_response

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/timeseries",
            params={"workspace_id": workspace_id},
            json={
                "metric_name": "duration",
                "startTime": 1704067200,
                "endTime": 1704153600,
                "aggregation": "average",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["metricName"] == "duration"
    assert data["aggregation"] == "average"
    assert data["totalCount"] == len(data["dataPoints"])


@pytest.mark.asyncio
async def test_get_timeseries_with_filter(client, test_db):
    """Test time series with WHERE clause filter."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {"beginTimeSeconds": 1704067200, "average.duration": 0.180},
                            {"beginTimeSeconds": 1704070800, "average.duration": 0.190},
                        ],
                        "metadata": {"eventTypes": ["Transaction"]},
                    }
                }
            }
        }
    }

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_graphql_response

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/timeseries",
            params={"workspace_id": workspace_id},
            json={
                "metric_name": "duration",
                "startTime": 1704067200,
                "endTime": 1704153600,
                "aggregation": "average",
                "where_clause": "appName = 'my-app'",
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_timeseries_different_aggregations(client, test_db):
    """Test time series with different aggregation functions."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {"beginTimeSeconds": 1704067200, "max.duration": 1.5},
                            {"beginTimeSeconds": 1704070800, "max.duration": 2.1},
                        ],
                        "metadata": {"eventTypes": ["Transaction"]},
                    }
                }
            }
        }
    }

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_graphql_response

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/timeseries",
            params={"workspace_id": workspace_id},
            json={
                "metric_name": "duration",
                "startTime": 1704067200,
                "endTime": 1704153600,
                "aggregation": "max",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["aggregation"] == "max"


# =============================================================================
# Test: Infrastructure Metrics
# =============================================================================


@pytest.mark.asyncio
async def test_get_infra_metrics_success(client, test_db):
    """Test successful infrastructure metrics query."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {
                                "beginTimeSeconds": 1704067200,
                                "average.cpuPercent": 45.5,
                            },
                            {
                                "beginTimeSeconds": 1704070800,
                                "average.cpuPercent": 52.3,
                            },
                            {
                                "beginTimeSeconds": 1704074400,
                                "average.cpuPercent": 48.7,
                            },
                        ],
                        "metadata": {"eventTypes": ["SystemSample"]},
                    }
                }
            }
        }
    }

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_graphql_response

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/infrastructure",
            params={"workspace_id": workspace_id},
            json={
                "metric_name": "cpuPercent",
                "startTime": 1704067200,
                "endTime": 1704153600,
                "aggregation": "average",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["metricName"] == "cpuPercent"
    assert data["aggregation"] == "average"
    assert data["totalCount"] == 3


@pytest.mark.asyncio
async def test_get_infra_metrics_with_hostname(client, test_db):
    """Test infrastructure metrics filtered by hostname."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {
                                "beginTimeSeconds": 1704067200,
                                "average.memoryUsedPercent": 72.5,
                            },
                            {
                                "beginTimeSeconds": 1704070800,
                                "average.memoryUsedPercent": 75.8,
                            },
                        ],
                        "metadata": {"eventTypes": ["SystemSample"]},
                    }
                }
            }
        }
    }

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_graphql_response

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/infrastructure",
            params={"workspace_id": workspace_id},
            json={
                "metric_name": "memoryUsedPercent",
                "hostname": "prod-server-01",
                "startTime": 1704067200,
                "endTime": 1704153600,
                "aggregation": "average",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["metricName"] == "memoryUsedPercent"


@pytest.mark.asyncio
async def test_get_infra_metrics_no_integration(client, test_db):
    """Test infrastructure metrics fails when no integration exists."""
    workspace_id = str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.commit()

    with patch(
        "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/infrastructure",
            params={"workspace_id": workspace_id},
            json={
                "metric_name": "cpuPercent",
                "startTime": 1704067200,
                "endTime": 1704153600,
            },
        )

    assert response.status_code == 500


# =============================================================================
# Test: API Error Handling
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_api_authentication_error(client, test_db):
    """Test metrics query handles authentication errors."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "invalid_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 401
        mock_post.return_value.text = "Unauthorized"

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/query",
            params={"workspace_id": workspace_id},
            json={
                "nrql_query": "SELECT average(duration) FROM Transaction SINCE 1 hour ago"
            },
        )

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_metrics_graphql_error(client, test_db):
    """Test metrics query handles GraphQL errors."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_error_response = {
        "errors": [
            {
                "message": "Invalid NRQL query",
                "extensions": {"code": "NRQL_PARSE_ERROR"},
            }
        ]
    }

    with (
        patch(
            "app.newrelic.Metrics.service.newrelic_metrics_service._get_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_error_response

        response = await client.post(
            f"{API_PREFIX}/newrelic/metrics/query",
            params={"workspace_id": workspace_id},
            json={"nrql_query": "INVALID QUERY SYNTAX"},
        )

    assert response.status_code == 500
