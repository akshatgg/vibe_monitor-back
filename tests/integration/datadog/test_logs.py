"""
Integration tests for Datadog Logs endpoints.

Tests the following OPEN endpoints (no authentication required):
- POST /api/v1/datadog/logs/search - Search logs
- POST /api/v1/datadog/logs/list - List logs (simplified)
- POST /api/v1/datadog/logs/services - List unique services
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import (
    DatadogIntegration,
    Integration,
    Workspace,
    WorkspaceType,
)

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


def create_mock_httpx_response(
    status_code: int, json_data: dict = None, text: str = ""
):
    """Create a mock httpx response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = json_data or {}
    mock_response.text = text
    return mock_response


# =============================================================================
# Test: Search Logs
# =============================================================================


@pytest.mark.asyncio
async def test_search_logs_success(client, test_db):
    """Test successful log search."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response_data = {
        "data": [
            {
                "id": "log-123",
                "type": "log",
                "attributes": {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "host": "host-1",
                    "service": "api-service",
                    "status": "error",
                    "message": "Something went wrong",
                    "tags": ["env:prod"],
                },
            }
        ],
        "links": {"next": None},
        "meta": {"elapsed": 100, "status": "done"},
    }

    mock_response = create_mock_httpx_response(200, mock_response_data)

    with (
        patch(
            "app.datadog.Logs.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("app.datadog.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/datadog/logs/search",
            params={"workspace_id": workspace_id},
            json={"query": "status:error", "limit": 100},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 1
    assert len(data["data"]) == 1
    assert data["data"][0]["attributes"]["service"] == "api-service"


@pytest.mark.asyncio
async def test_search_logs_with_time_range(client, test_db):
    """Test log search with explicit time range."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response_data = {"data": [], "meta": {"status": "done"}}
    mock_response = create_mock_httpx_response(200, mock_response_data)

    with (
        patch(
            "app.datadog.Logs.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("app.datadog.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/datadog/logs/search",
            params={"workspace_id": workspace_id},
            json={
                "query": "service:my-app",
                "from": 1704067200000,  # 2024-01-01 00:00:00 UTC
                "to": 1704153600000,  # 2024-01-02 00:00:00 UTC
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 0


@pytest.mark.asyncio
async def test_search_logs_no_integration(client, test_db):
    """Test log search fails when no integration exists."""
    workspace_id = str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
        type=WorkspaceType.TEAM,
    )
    test_db.add(workspace)
    await test_db.commit()

    with patch(
        "app.datadog.Logs.service.get_datadog_credentials",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await client.post(
            f"{API_PREFIX}/datadog/logs/search",
            params={"workspace_id": workspace_id},
            json={"query": "status:error"},
        )

    assert response.status_code == 500
    assert "No Datadog integration found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_search_logs_api_error(client, test_db):
    """Test log search handles API errors gracefully."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response = create_mock_httpx_response(403, text="Forbidden")

    with (
        patch(
            "app.datadog.Logs.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("app.datadog.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/datadog/logs/search",
            params={"workspace_id": workspace_id},
            json={"query": "status:error"},
        )

    assert response.status_code == 500
    assert "Invalid API key" in response.json()["detail"]


# =============================================================================
# Test: List Logs (Simplified)
# =============================================================================


@pytest.mark.asyncio
async def test_list_logs_success(client, test_db):
    """Test successful simplified log listing."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response_data = {
        "data": [
            {
                "id": "log-1",
                "type": "log",
                "attributes": {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "host": "host-1",
                    "service": "api-service",
                    "status": "info",
                    "message": "Request processed",
                    "tags": ["env:prod"],
                },
            },
            {
                "id": "log-2",
                "type": "log",
                "attributes": {
                    "timestamp": "2024-01-01T00:01:00Z",
                    "host": "host-2",
                    "service": "db-service",
                    "status": "error",
                    "message": "Connection timeout",
                    "tags": ["env:prod"],
                },
            },
        ],
        "meta": {"status": "done"},
    }

    mock_response = create_mock_httpx_response(200, mock_response_data)

    with (
        patch(
            "app.datadog.Logs.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("app.datadog.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/datadog/logs/list",
            params={"workspace_id": workspace_id},
            json={"query": "*", "limit": 50},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 2
    assert len(data["logs"]) == 2
    # Check simplified format
    assert "timestamp" in data["logs"][0]
    assert "message" in data["logs"][0]
    assert "service" in data["logs"][0]


@pytest.mark.asyncio
async def test_list_logs_default_query(client, test_db):
    """Test listing logs with default query (*)."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response_data = {"data": [], "meta": {"status": "done"}}
    mock_response = create_mock_httpx_response(200, mock_response_data)

    with (
        patch(
            "app.datadog.Logs.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("app.datadog.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/datadog/logs/list",
            params={"workspace_id": workspace_id},
            json={},  # Use defaults
        )

    assert response.status_code == 200


# =============================================================================
# Test: List Services
# =============================================================================


@pytest.mark.asyncio
async def test_list_services_success(client, test_db):
    """Test successful listing of unique services."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response_data = {
        "data": [
            {
                "id": "log-1",
                "type": "log",
                "attributes": {"service": "api-service", "message": "msg1"},
            },
            {
                "id": "log-2",
                "type": "log",
                "attributes": {"service": "db-service", "message": "msg2"},
            },
            {
                "id": "log-3",
                "type": "log",
                "attributes": {"service": "api-service", "message": "msg3"},
            },
            {
                "id": "log-4",
                "type": "log",
                "attributes": {"service": "cache-service", "message": "msg4"},
            },
        ],
        "meta": {"status": "done"},
    }

    mock_response = create_mock_httpx_response(200, mock_response_data)

    with (
        patch(
            "app.datadog.Logs.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("app.datadog.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/datadog/logs/services",
            params={"workspace_id": workspace_id},
            json={"limit": 1000},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 3  # Unique services
    assert "api-service" in data["services"]
    assert "db-service" in data["services"]
    assert "cache-service" in data["services"]
    # Should be sorted
    assert data["services"] == sorted(data["services"])


@pytest.mark.asyncio
async def test_list_services_empty(client, test_db):
    """Test listing services when no logs exist."""
    workspace, workspace_id = await create_test_workspace_with_datadog(test_db)

    mock_response_data = {"data": [], "meta": {"status": "done"}}
    mock_response = create_mock_httpx_response(200, mock_response_data)

    with (
        patch(
            "app.datadog.Logs.service.get_datadog_credentials",
            new_callable=AsyncMock,
            return_value={
                "api_key": "test_api_key",
                "app_key": "test_app_key",
                "region": "us1",
            },
        ),
        patch("app.datadog.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/datadog/logs/services",
            params={"workspace_id": workspace_id},
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 0
    assert data["services"] == []
