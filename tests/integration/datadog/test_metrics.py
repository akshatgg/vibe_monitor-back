"""
Integration tests for Datadog Metrics endpoints.

Tests the following OPEN endpoints (no authentication required):
- POST /api/v1/datadog/metrics/query/timeseries - Query timeseries metrics
- POST /api/v1/datadog/metrics/query - Simple metrics query
- POST /api/v1/datadog/metrics/events/search - Search events
- GET /api/v1/datadog/metrics/tags/list - List available tags
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models import DatadogIntegration, Integration, Workspace, WorkspaceType

API_PREFIX = "/api/v1"


# =============================================================================
# Helper Functions
# =============================================================================


async def create_test_workspace_with_datadog(test_db) -> tuple[Workspace, str]:
    """Create a workspace with Datadog integration for testing."""
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
        provider="datadog",
        status="active",
    )
    test_db.add(control_plane)

    # Create Datadog integration
    datadog_integration = DatadogIntegration(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        integration_id=integration_id,
        api_key="encrypted_api_key",
        app_key="encrypted_app_key",
        region="us1",
    )
    test_db.add(datadog_integration)

    await test_db.commit()
    return workspace, workspace_id


# =============================================================================
# Test: Query Timeseries
# =============================================================================


@pytest.mark.asyncio
async def test_query_timeseries_simple_format(client, test_db):
    """Test timeseries query with simple format (single query)."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response = {
        "data": {
            "type": "timeseries_response",
            "attributes": {
                "series": [{"group_tags": [], "query_index": 0}],
                "times": [1704067200000, 1704070800000],
                "values": [[85.5, 90.2]],
            },
        }
    }

    with (
        patch(
            "app.datadog.integration.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_response

        response = await client.post(
            f"{API_PREFIX}/datadog/metrics/query/timeseries",
            params={"workspace_id": workspace_id},
            json={
                "query": "avg:system.cpu.user{*}",
                "from": 1704067200000,
                "to": 1704153600000,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert data["data"]["attributes"]["times"] == [1704067200000, 1704070800000]


@pytest.mark.asyncio
async def test_query_timeseries_missing_query(client, test_db):
    """Test timeseries query fails without query or data."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    response = await client.post(
        f"{API_PREFIX}/datadog/metrics/query/timeseries",
        params={"workspace_id": workspace_id},
        json={
            "from": 1704067200000,
            "to": 1704153600000,
            # Missing both 'query' and 'data'
        },
    )

    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_query_timeseries_no_integration(client, test_db):
    """Test timeseries query fails when no integration exists."""
    workspace_id = str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.commit()

    with patch(
        "app.datadog.integration.service.get_datadog_credentials",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await client.post(
            f"{API_PREFIX}/datadog/metrics/query/timeseries",
            params={"workspace_id": workspace_id},
            json={
                "query": "avg:system.cpu.user{*}",
                "from": 1704067200000,
                "to": 1704153600000,
            },
        )

    assert response.status_code == 500


# =============================================================================
# Test: Simple Query
# =============================================================================


@pytest.mark.asyncio
async def test_simple_query_success(client, test_db):
    """Test simple metrics query with clean response format."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    # Mock the timeseries response that the service will parse
    mock_response = {
        "data": {
            "type": "timeseries_response",
            "attributes": {
                "series": [{"group_tags": [], "query_index": 0}],
                "times": [1704067200000, 1704070800000, 1704074400000],
                "values": [[85.5, 90.2, 88.0]],
            },
        }
    }

    with (
        patch(
            "app.datadog.integration.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_response

        response = await client.post(
            f"{API_PREFIX}/datadog/metrics/query",
            params={"workspace_id": workspace_id},
            json={
                "query": "avg:system.cpu.user{*}",
                "from_timestamp": 1704067200000,
                "to_timestamp": 1704153600000,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "avg:system.cpu.user{*}"
    assert "points" in data
    assert data["totalPoints"] == len(data["points"])


# =============================================================================
# Test: Events Search
# =============================================================================


@pytest.mark.asyncio
async def test_events_search_success(client, test_db):
    """Test searching Datadog events."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response = {
        "events": [
            {
                "id": 12345,
                "title": "Deployment started",
                "text": "Deploying v1.2.3",
                "date_happened": 1704067200,
                "alert_type": "info",
                "priority": "normal",
                "source": "jenkins",
                "tags": ["env:prod", "service:api"],
                "host": "deploy-host",
            },
            {
                "id": 12346,
                "title": "Alert fired",
                "text": "High CPU usage",
                "date_happened": 1704070800,
                "alert_type": "error",
                "priority": "normal",
                "source": "datadog",
                "tags": ["env:prod"],
            },
        ]
    }

    with (
        patch(
            "app.datadog.integration.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
    ):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        response = await client.post(
            f"{API_PREFIX}/datadog/metrics/events/search",
            params={"workspace_id": workspace_id},
            json={
                "start": 1704067200,  # Seconds, not milliseconds
                "end": 1704153600,
                "tags": "env:prod",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 2
    assert len(data["events"]) == 2
    assert data["events"][0]["title"] == "Deployment started"


@pytest.mark.asyncio
async def test_events_search_empty(client, test_db):
    """Test events search returns empty list when no events."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response = {"events": []}

    with (
        patch(
            "app.datadog.integration.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
    ):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        response = await client.post(
            f"{API_PREFIX}/datadog/metrics/events/search",
            params={"workspace_id": workspace_id},
            json={
                "start": 1704067200,
                "end": 1704153600,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 0
    assert data["events"] == []


# =============================================================================
# Test: List Tags
# =============================================================================


@pytest.mark.asyncio
async def test_list_tags_success(client, test_db):
    """Test listing available tags."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    # Mock events response that contains tags
    mock_response = {
        "events": [
            {"id": 1, "tags": ["env:prod", "service:api", "region:us-east-1"]},
            {"id": 2, "tags": ["env:staging", "service:api"]},
            {"id": 3, "tags": ["env:prod", "service:db", "region:us-west-2"]},
        ]
    }

    with (
        patch(
            "app.datadog.integration.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
    ):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        response = await client.get(
            f"{API_PREFIX}/datadog/metrics/tags/list",
            params={"workspace_id": workspace_id},
        )

    assert response.status_code == 200
    data = response.json()
    assert "tags" in data
    assert "tagsByCategory" in data
    assert "totalTags" in data


@pytest.mark.asyncio
async def test_list_tags_no_integration(client, test_db):
    """Test list tags fails when no integration exists."""
    workspace_id = str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.commit()

    with patch(
        "app.datadog.integration.service.get_datadog_credentials",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await client.get(
            f"{API_PREFIX}/datadog/metrics/tags/list",
            params={"workspace_id": workspace_id},
        )

    assert response.status_code == 500


# =============================================================================
# Test: API Error Handling
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_api_authentication_error(client, test_db):
    """Test metrics query handles authentication errors."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    with (
        patch(
            "app.datadog.integration.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "invalid_key",
                "app_key": "invalid_app_key",
                "region": "us1",
            },
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value.status_code = 403
        mock_post.return_value.text = "Forbidden"

        response = await client.post(
            f"{API_PREFIX}/datadog/metrics/query",
            params={"workspace_id": workspace_id},
            json={
                "query": "avg:system.cpu.user{*}",
                "from_timestamp": 1704067200000,
                "to_timestamp": 1704153600000,
            },
        )

    assert response.status_code == 500
