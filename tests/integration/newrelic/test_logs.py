"""
Integration tests for New Relic Logs endpoints.

Tests the following OPEN endpoints (no authentication required):
- POST /api/v1/newrelic/logs/query - Query logs using NRQL
- POST /api/v1/newrelic/logs/filter - Filter logs with common parameters
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Integration, NewRelicIntegration, Workspace

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
# Test: Query Logs (NRQL)
# =============================================================================


@pytest.mark.asyncio
async def test_query_logs_success(client, test_db):
    """Test successful log query using NRQL."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {
                                "timestamp": 1704067200000,
                                "message": "Error in API call",
                                "level": "error",
                            },
                            {
                                "timestamp": 1704067260000,
                                "message": "Request processed",
                                "level": "info",
                            },
                        ],
                        "metadata": {
                            "eventTypes": ["Log"],
                            "timeWindow": {
                                "end": 1704153600000,
                                "start": 1704067200000,
                            },
                        },
                    }
                }
            }
        }
    }

    mock_response = create_mock_httpx_response(200, mock_graphql_response)

    with (
        patch(
            "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("app.newrelic.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/query",
            params={"workspace_id": workspace_id},
            json={
                "nrql_query": "SELECT * FROM Log WHERE level = 'error' SINCE 1 hour ago"
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 2
    assert len(data["results"]) == 2


@pytest.mark.asyncio
async def test_query_logs_with_facet(client, test_db):
    """Test log query with FACET clause."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {"level": "error", "count": 150},
                            {"level": "warn", "count": 320},
                            {"level": "info", "count": 1500},
                        ],
                        "metadata": {"eventTypes": ["Log"]},
                    }
                }
            }
        }
    }

    mock_response = create_mock_httpx_response(200, mock_graphql_response)

    with (
        patch(
            "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("app.newrelic.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/query",
            params={"workspace_id": workspace_id},
            json={"nrql_query": "SELECT count(*) FROM Log FACET level SINCE 1 day ago"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 3


@pytest.mark.asyncio
async def test_query_logs_no_integration(client, test_db):
    """Test log query fails when no integration exists."""
    workspace_id = str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.commit()

    with patch(
        "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
        new_callable=AsyncMock,
        side_effect=Exception("New Relic integration not found"),
    ):
        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/query",
            params={"workspace_id": workspace_id},
            json={"nrql_query": "SELECT * FROM Log SINCE 1 hour ago"},
        )

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_query_logs_graphql_error(client, test_db):
    """Test log query handles GraphQL errors."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_error_response = {
        "errors": [
            {
                "message": "Invalid NRQL query syntax",
                "extensions": {"code": "NRQL_PARSE_ERROR"},
            }
        ]
    }

    mock_response = create_mock_httpx_response(200, mock_error_response)

    with (
        patch(
            "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("app.newrelic.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/query",
            params={"workspace_id": workspace_id},
            json={"nrql_query": "INVALID QUERY"},
        )

    assert response.status_code == 500


# =============================================================================
# Test: Filter Logs
# =============================================================================


@pytest.mark.asyncio
async def test_filter_logs_success(client, test_db):
    """Test successful log filtering with common parameters."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {
                                "timestamp": 1704067200000,
                                "message": "Connection timeout",
                            },
                            {
                                "timestamp": 1704067260000,
                                "message": "Connection reset",
                            },
                        ],
                        "metadata": {"eventTypes": ["Log"]},
                    }
                }
            }
        }
    }

    mock_response = create_mock_httpx_response(200, mock_graphql_response)

    with (
        patch(
            "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("app.newrelic.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/filter",
            params={"workspace_id": workspace_id},
            json={
                "query": "timeout",
                "startTime": 1704067200000,
                "endTime": 1704153600000,
                "limit": 50,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["totalCount"] == 2
    assert "logs" in data


@pytest.mark.asyncio
async def test_filter_logs_with_pagination(client, test_db):
    """Test log filtering with pagination offset."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [
                            {"timestamp": 1704067200000, "message": "Log entry 11"},
                            {"timestamp": 1704067260000, "message": "Log entry 12"},
                        ],
                        "metadata": {"eventTypes": ["Log"]},
                    }
                }
            }
        }
    }

    mock_response = create_mock_httpx_response(200, mock_graphql_response)

    with (
        patch(
            "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("app.newrelic.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/filter",
            params={"workspace_id": workspace_id},
            json={
                "query": "*",
                "limit": 10,
                "offset": 10,  # Skip first 10 results
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "hasMore" in data


@pytest.mark.asyncio
async def test_filter_logs_default_parameters(client, test_db):
    """Test log filtering with default parameters."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_graphql_response = {
        "data": {
            "actor": {
                "account": {
                    "nrql": {
                        "results": [],
                        "metadata": {"eventTypes": ["Log"]},
                    }
                }
            }
        }
    }

    mock_response = create_mock_httpx_response(200, mock_graphql_response)

    with (
        patch(
            "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "test_api_key"},
        ),
        patch("app.newrelic.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/filter",
            params={"workspace_id": workspace_id},
            json={"query": "error"},  # Only required field
        )

    assert response.status_code == 200


# =============================================================================
# Test: API Error Handling
# =============================================================================


@pytest.mark.asyncio
async def test_query_logs_authentication_error(client, test_db):
    """Test log query handles authentication errors."""
    workspace, workspace_id = await create_test_workspace_with_newrelic(test_db)

    mock_response = create_mock_httpx_response(401, text="Unauthorized")

    with (
        patch(
            "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
            new_callable=AsyncMock,
            return_value={"account_id": "1234567", "api_key": "invalid_key"},
        ),
        patch("app.newrelic.Logs.service.httpx.AsyncClient") as mock_client_class,
    ):
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client

        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/query",
            params={"workspace_id": workspace_id},
            json={"nrql_query": "SELECT * FROM Log SINCE 1 hour ago"},
        )

    assert response.status_code == 500


@pytest.mark.asyncio
async def test_filter_logs_no_integration(client, test_db):
    """Test log filtering fails when no integration exists."""
    workspace_id = str(uuid.uuid4())
    workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
    )
    test_db.add(workspace)
    await test_db.commit()

    with patch(
        "app.newrelic.Logs.service.NewRelicLogsService._get_newrelic_credentials",
        new_callable=AsyncMock,
        side_effect=Exception("New Relic integration not found"),
    ):
        response = await client.post(
            f"{API_PREFIX}/newrelic/logs/filter",
            params={"workspace_id": workspace_id},
            json={"query": "error"},
        )

    assert response.status_code == 500
