"""
Integration tests for CloudWatch Logs API endpoints.

These tests verify the /api/v1/cloudwatch/logs/* endpoints work correctly.
CloudWatch Logs endpoints are OPEN (no authentication required).
"""

from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import API_PREFIX


@pytest.mark.asyncio
async def test_list_log_groups_success(client, test_db):
    """Test listing log groups returns expected response structure"""
    mock_response = {
        "logGroups": [
            {
                "logGroupName": "/aws/lambda/test-function",
                "creationTime": 1704067200000,
                "arn": "arn:aws:logs:us-west-1:123456789012:log-group:/aws/lambda/test-function",
                "storedBytes": 1024,
                "logGroupClass": "STANDARD",
                "logGroupArn": "arn:aws:logs:us-west-1:123456789012:log-group:/aws/lambda/test-function:*",
                "metricFilterCount": 0,
                "retentionInDays": 30,
            }
        ],
        "totalCount": 1,
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.list_log_groups",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/groups?workspace_id=test-workspace-id",
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert "logGroups" in data
    assert "totalCount" in data


@pytest.mark.asyncio
async def test_list_log_groups_with_prefix_filter(client, test_db):
    """Test listing log groups with name prefix filter"""
    mock_response = {
        "logGroups": [
            {
                "logGroupName": "/aws/lambda/my-function",
                "creationTime": 1704067200000,
                "arn": "arn:aws:logs:us-west-1:123456789012:log-group:/aws/lambda/my-function",
                "storedBytes": 2048,
                "logGroupClass": "STANDARD",
                "logGroupArn": "arn:aws:logs:us-west-1:123456789012:log-group:/aws/lambda/my-function:*",
            }
        ],
        "totalCount": 1,
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.list_log_groups",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/groups?workspace_id=test-workspace-id",
            json={"logGroupNamePrefix": "/aws/lambda/"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_log_groups_missing_workspace_id(client, test_db):
    """Test listing log groups without workspace_id returns 422"""
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/logs/groups",
        json={},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_log_groups_service_error(client, test_db):
    """Test listing log groups handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.list_log_groups",
        new_callable=AsyncMock,
        side_effect=Exception("AWS service unavailable"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/groups?workspace_id=test-workspace-id",
            json={},
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to list log groups" in data["detail"]


@pytest.mark.asyncio
async def test_list_log_streams_success(client, test_db):
    """Test listing log streams returns expected response structure"""
    mock_response = {
        "logStreams": [
            {
                "logStreamName": "2024/01/01/[$LATEST]abcd1234",
                "creationTime": 1704067200000,
                "arn": "arn:aws:logs:us-west-1:123456789012:log-group:/aws/lambda/test:log-stream:2024/01/01/[$LATEST]abcd1234",
                "storedBytes": 512,
                "firstEventTimestamp": 1704067200000,
                "lastEventTimestamp": 1704070800000,
                "lastIngestionTime": 1704070800000,
            }
        ],
        "totalCount": 1,
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.list_log_streams",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/streams?workspace_id=test-workspace-id",
            json={"logGroupName": "/aws/lambda/test-function"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "logStreams" in data
    assert "totalCount" in data


@pytest.mark.asyncio
async def test_list_log_streams_missing_log_group_name(client, test_db):
    """Test listing log streams without logGroupName returns 422"""
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/logs/streams?workspace_id=test-workspace-id",
        json={},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_log_streams_service_error(client, test_db):
    """Test listing log streams handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.list_log_streams",
        new_callable=AsyncMock,
        side_effect=Exception("Log group not found"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/streams?workspace_id=test-workspace-id",
            json={"logGroupName": "/aws/lambda/nonexistent"},
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to list log streams" in data["detail"]


@pytest.mark.asyncio
async def test_get_log_events_success(client, test_db):
    """Test getting log events returns expected response structure"""
    mock_response = {
        "events": [
            {
                "timestamp": 1704067200000,
                "message": "START RequestId: abc-123",
                "ingestionTime": 1704067200100,
            },
            {
                "timestamp": 1704067201000,
                "message": "END RequestId: abc-123",
                "ingestionTime": 1704067201100,
            },
        ],
        "totalCount": 2,
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.get_log_events",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/events?workspace_id=test-workspace-id",
            json={
                "logGroupName": "/aws/lambda/test-function",
                "logStreamName": "2024/01/01/[$LATEST]abcd1234",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    assert "totalCount" in data


@pytest.mark.asyncio
async def test_get_log_events_with_time_range(client, test_db):
    """Test getting log events with time range filter"""
    mock_response = {
        "events": [],
        "totalCount": 0,
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.get_log_events",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/events?workspace_id=test-workspace-id",
            json={
                "logGroupName": "/aws/lambda/test-function",
                "logStreamName": "2024/01/01/[$LATEST]abcd1234",
                "startTime": 1704067200000,
                "endTime": 1704070800000,
                "limit": 50,
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_log_events_missing_required_fields(client, test_db):
    """Test getting log events without required fields returns 422"""
    # Missing logStreamName
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/logs/events?workspace_id=test-workspace-id",
        json={"logGroupName": "/aws/lambda/test-function"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_execute_query_success(client, test_db):
    """Test executing CloudWatch Insights query returns expected response"""
    mock_response = {
        "results": [
            [
                {"field": "@timestamp", "value": "2024-01-01T00:00:00.000Z"},
                {"field": "@message", "value": "Test log message"},
            ]
        ],
        "statistics": {
            "recordsMatched": 1.0,
            "recordsScanned": 100.0,
            "bytesScanned": 10240.0,
        },
        "status": "Complete",
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.execute_query",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/query?workspace_id=test-workspace-id",
            json={
                "logGroupName": "/aws/lambda/test-function",
                "startTime": 1704067200,
                "endTime": 1704070800,
                "queryString": "fields @timestamp, @message | sort @timestamp desc | limit 20",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "status" in data


@pytest.mark.asyncio
async def test_execute_query_with_custom_timeout(client, test_db):
    """Test executing query with custom max_wait_seconds parameter"""
    mock_response = {
        "results": [],
        "statistics": None,
        "status": "Complete",
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.execute_query",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/query?workspace_id=test-workspace-id&max_wait_seconds=120",
            json={
                "logGroupName": "/aws/lambda/test-function",
                "startTime": 1704067200,
                "endTime": 1704070800,
                "queryString": "stats count() by bin(5m)",
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_execute_query_missing_required_fields(client, test_db):
    """Test executing query without required fields returns 422"""
    # Missing queryString
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/logs/query?workspace_id=test-workspace-id",
        json={
            "logGroupName": "/aws/lambda/test-function",
            "startTime": 1704067200,
            "endTime": 1704070800,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_execute_query_service_error(client, test_db):
    """Test executing query handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.execute_query",
        new_callable=AsyncMock,
        side_effect=Exception("Query timed out"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/query?workspace_id=test-workspace-id",
            json={
                "logGroupName": "/aws/lambda/test-function",
                "startTime": 1704067200,
                "endTime": 1704070800,
                "queryString": "fields @timestamp, @message",
            },
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to execute query" in data["detail"]


@pytest.mark.asyncio
async def test_filter_log_events_success(client, test_db):
    """Test filtering log events returns expected response structure"""
    mock_response = {
        "events": [
            {
                "logStreamName": "2024/01/01/[$LATEST]abcd1234",
                "timestamp": 1704067200000,
                "message": "[ERROR] Something went wrong",
                "ingestionTime": 1704067200100,
                "eventId": "event-123",
            }
        ],
        "searchedLogStreams": [
            {
                "logStreamName": "2024/01/01/[$LATEST]abcd1234",
                "searchedCompletely": True,
            }
        ],
        "totalCount": 1,
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.filter_log_events",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/filter?workspace_id=test-workspace-id",
            json={
                "logGroupName": "/aws/lambda/test-function",
                "filterPattern": "ERROR",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "events" in data
    assert "totalCount" in data


@pytest.mark.asyncio
async def test_filter_log_events_with_all_options(client, test_db):
    """Test filtering log events with all optional parameters"""
    mock_response = {
        "events": [],
        "searchedLogStreams": None,
        "totalCount": 0,
    }

    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.filter_log_events",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/filter?workspace_id=test-workspace-id",
            json={
                "logGroupName": "/aws/lambda/test-function",
                "logStreamNames": ["stream1", "stream2"],
                "startTime": 1704067200000,
                "endTime": 1704070800000,
                "filterPattern": '{ $.level = "error" }',
                "limit": 50,
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_filter_log_events_missing_log_group_name(client, test_db):
    """Test filtering log events without logGroupName returns 422"""
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/logs/filter?workspace_id=test-workspace-id",
        json={"filterPattern": "ERROR"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_filter_log_events_service_error(client, test_db):
    """Test filtering log events handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Logs.router.cloudwatch_logs_service.filter_log_events",
        new_callable=AsyncMock,
        side_effect=Exception("Access denied to log group"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/logs/filter?workspace_id=test-workspace-id",
            json={"logGroupName": "/aws/lambda/test-function"},
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to filter log events" in data["detail"]
