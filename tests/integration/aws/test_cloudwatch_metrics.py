"""
Integration tests for CloudWatch Metrics API endpoints.

These tests verify the /api/v1/cloudwatch/metrics/* endpoints work correctly.
CloudWatch Metrics endpoints are OPEN (no authentication required).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import API_PREFIX


@pytest.mark.asyncio
async def test_list_metrics_success(client, test_db):
    """Test listing metrics returns expected response structure"""
    mock_response = {
        "Metrics": [
            {
                "Namespace": "AWS/EC2",
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-1234567890abcdef0"}],
            },
            {
                "Namespace": "AWS/Lambda",
                "MetricName": "Invocations",
                "Dimensions": [{"Name": "FunctionName", "Value": "my-function"}],
            },
        ],
        "TotalCount": 2,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.list_metrics",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/list?workspace_id=test-workspace-id",
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert "Metrics" in data
    assert "TotalCount" in data


@pytest.mark.asyncio
async def test_list_metrics_with_filters(client, test_db):
    """Test listing metrics with namespace and metric name filters"""
    mock_response = {
        "Metrics": [
            {
                "Namespace": "AWS/EC2",
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-1234567890abcdef0"}],
            }
        ],
        "TotalCount": 1,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.list_metrics",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/list?workspace_id=test-workspace-id",
            json={
                "Namespace": "AWS/EC2",
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-1234567890abcdef0"}],
                "Limit": 50,
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_metrics_missing_workspace_id(client, test_db):
    """Test listing metrics without workspace_id returns 422"""
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/metrics/list",
        json={},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_metrics_service_error(client, test_db):
    """Test listing metrics handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.list_metrics",
        new_callable=AsyncMock,
        side_effect=Exception("AWS service unavailable"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/list?workspace_id=test-workspace-id",
            json={},
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to list metrics" in data["detail"]


@pytest.mark.asyncio
async def test_list_namespaces_success(client, test_db):
    """Test listing namespaces returns expected response structure"""
    mock_response = {
        "Namespaces": ["AWS/EC2", "AWS/Lambda", "AWS/RDS", "Custom/MyApp"],
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.list_namespaces",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.get(
            f"{API_PREFIX}/cloudwatch/metrics/namespaces?workspace_id=test-workspace-id",
        )

    assert response.status_code == 200
    data = response.json()
    assert "Namespaces" in data
    assert isinstance(data["Namespaces"], list)


@pytest.mark.asyncio
async def test_list_namespaces_missing_workspace_id(client, test_db):
    """Test listing namespaces without workspace_id returns 422"""
    response = await client.get(
        f"{API_PREFIX}/cloudwatch/metrics/namespaces",
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_namespaces_service_error(client, test_db):
    """Test listing namespaces handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.list_namespaces",
        new_callable=AsyncMock,
        side_effect=Exception("Failed to connect to AWS"),
    ):
        response = await client.get(
            f"{API_PREFIX}/cloudwatch/metrics/namespaces?workspace_id=test-workspace-id",
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to list namespaces" in data["detail"]


@pytest.mark.asyncio
async def test_get_metric_data_success(client, test_db):
    """Test getting metric data returns expected response structure"""
    mock_response = {
        "MetricDataResults": [
            {
                "Id": "m1",
                "Label": "CPUUtilization",
                "Timestamps": [
                    datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 0, 5, 0, tzinfo=timezone.utc),
                ],
                "Values": [45.5, 52.3],
                "StatusCode": "Complete",
                "Messages": None,
            }
        ],
        "Messages": None,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.get_metric_data",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/data?workspace_id=test-workspace-id",
            json={
                "MetricDataQueries": [
                    {
                        "Id": "m1",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/EC2",
                                "MetricName": "CPUUtilization",
                                "Dimensions": [
                                    {
                                        "Name": "InstanceId",
                                        "Value": "i-1234567890abcdef0",
                                    }
                                ],
                            },
                            "Period": 300,
                            "Stat": "Average",
                        },
                    }
                ],
                "StartTime": 1704067200,
                "EndTime": 1704070800,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "MetricDataResults" in data


@pytest.mark.asyncio
async def test_get_metric_data_with_all_options(client, test_db):
    """Test getting metric data with all optional parameters"""
    mock_response = {
        "MetricDataResults": [],
        "Messages": None,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.get_metric_data",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/data?workspace_id=test-workspace-id",
            json={
                "MetricDataQueries": [
                    {
                        "Id": "m1",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/Lambda",
                                "MetricName": "Duration",
                            },
                            "Period": 60,
                            "Stat": "p99",
                        },
                    }
                ],
                "StartTime": 1704067200,
                "EndTime": 1704070800,
                "ScanBy": "TimestampAscending",
                "MaxDatapoints": 100,
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_metric_data_missing_required_fields(client, test_db):
    """Test getting metric data without required fields returns 422"""
    # Missing MetricDataQueries
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/metrics/data?workspace_id=test-workspace-id",
        json={
            "StartTime": 1704067200,
            "EndTime": 1704070800,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_metric_data_service_error(client, test_db):
    """Test getting metric data handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.get_metric_data",
        new_callable=AsyncMock,
        side_effect=Exception("Invalid metric query"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/data?workspace_id=test-workspace-id",
            json={
                "MetricDataQueries": [{"Id": "m1"}],
                "StartTime": 1704067200,
                "EndTime": 1704070800,
            },
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to get metric data" in data["detail"]


@pytest.mark.asyncio
async def test_get_metric_statistics_success(client, test_db):
    """Test getting metric statistics returns expected response structure"""
    mock_response = {
        "Label": "CPUUtilization",
        "Datapoints": [
            {
                "Timestamp": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "Average": 45.5,
                "Maximum": 78.2,
                "Minimum": 12.1,
                "SampleCount": 5.0,
            }
        ],
        "TotalDatapoints": 1,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.get_metric_statistics",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/statistics?workspace_id=test-workspace-id",
            json={
                "Namespace": "AWS/EC2",
                "MetricName": "CPUUtilization",
                "StartTime": 1704067200,
                "EndTime": 1704070800,
                "Period": 300,
                "Statistics": ["Average", "Maximum", "Minimum"],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "Label" in data
    assert "Datapoints" in data
    assert "TotalDatapoints" in data


@pytest.mark.asyncio
async def test_get_metric_statistics_with_dimensions(client, test_db):
    """Test getting metric statistics with dimensions filter"""
    mock_response = {
        "Label": "Duration",
        "Datapoints": [],
        "TotalDatapoints": 0,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.get_metric_statistics",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/statistics?workspace_id=test-workspace-id",
            json={
                "Namespace": "AWS/Lambda",
                "MetricName": "Duration",
                "Dimensions": [{"Name": "FunctionName", "Value": "my-function"}],
                "StartTime": 1704067200,
                "EndTime": 1704070800,
                "Period": 60,
                "ExtendedStatistics": ["p50", "p90", "p99"],
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_metric_statistics_missing_required_fields(client, test_db):
    """Test getting metric statistics without required fields returns 422"""
    # Missing Namespace
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/metrics/statistics?workspace_id=test-workspace-id",
        json={
            "MetricName": "CPUUtilization",
            "StartTime": 1704067200,
            "EndTime": 1704070800,
            "Period": 300,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_metric_statistics_service_error(client, test_db):
    """Test getting metric statistics handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.get_metric_statistics",
        new_callable=AsyncMock,
        side_effect=Exception("Metric not found"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/statistics?workspace_id=test-workspace-id",
            json={
                "Namespace": "AWS/EC2",
                "MetricName": "NonExistentMetric",
                "StartTime": 1704067200,
                "EndTime": 1704070800,
                "Period": 300,
            },
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to get metric statistics" in data["detail"]


@pytest.mark.asyncio
async def test_list_metric_streams_success(client, test_db):
    """Test listing metric streams returns expected response structure"""
    mock_response = {
        "Entries": [
            {
                "Arn": "arn:aws:cloudwatch:us-west-1:123456789012:metric-stream/test-stream",
                "CreationDate": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "LastUpdateDate": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                "Name": "test-stream",
                "FirehoseArn": "arn:aws:firehose:us-west-1:123456789012:deliverystream/test",
                "State": "running",
                "OutputFormat": "json",
            }
        ],
        "TotalCount": 1,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.list_metric_streams",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/streams/list?workspace_id=test-workspace-id",
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert "Entries" in data
    assert "TotalCount" in data


@pytest.mark.asyncio
async def test_list_metric_streams_with_limit(client, test_db):
    """Test listing metric streams with limit parameter"""
    mock_response = {
        "Entries": [],
        "TotalCount": 0,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.list_metric_streams",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/streams/list?workspace_id=test-workspace-id",
            json={"Limit": 10},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_metric_streams_service_error(client, test_db):
    """Test listing metric streams handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.list_metric_streams",
        new_callable=AsyncMock,
        side_effect=Exception("Access denied"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/streams/list?workspace_id=test-workspace-id",
            json={},
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to list metric streams" in data["detail"]


@pytest.mark.asyncio
async def test_get_metric_stream_success(client, test_db):
    """Test getting metric stream details returns expected response structure"""
    mock_response = {
        "Arn": "arn:aws:cloudwatch:us-west-1:123456789012:metric-stream/test-stream",
        "Name": "test-stream",
        "FirehoseArn": "arn:aws:firehose:us-west-1:123456789012:deliverystream/test",
        "State": "running",
        "CreationDate": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        "LastUpdateDate": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        "OutputFormat": "json",
        "IncludeFilters": None,
        "ExcludeFilters": None,
        "StatisticsConfigurations": None,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.get_metric_stream",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/streams/get?workspace_id=test-workspace-id",
            json={"Name": "test-stream"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "Name" in data


@pytest.mark.asyncio
async def test_get_metric_stream_missing_name(client, test_db):
    """Test getting metric stream without Name returns 422"""
    response = await client.post(
        f"{API_PREFIX}/cloudwatch/metrics/streams/get?workspace_id=test-workspace-id",
        json={},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_metric_stream_service_error(client, test_db):
    """Test getting metric stream handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.get_metric_stream",
        new_callable=AsyncMock,
        side_effect=Exception("Stream not found"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/streams/get?workspace_id=test-workspace-id",
            json={"Name": "nonexistent-stream"},
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to get metric stream" in data["detail"]


@pytest.mark.asyncio
async def test_describe_anomaly_detectors_success(client, test_db):
    """Test describing anomaly detectors returns expected response structure"""
    mock_response = {
        "AnomalyDetectors": [
            {
                "Namespace": "AWS/EC2",
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-1234567890abcdef0"}],
                "Stat": "Average",
                "Configuration": None,
                "StateValue": "TRAINED",
            }
        ],
        "TotalCount": 1,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.describe_anomaly_detectors",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/anomaly-detectors?workspace_id=test-workspace-id",
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert "AnomalyDetectors" in data
    assert "TotalCount" in data


@pytest.mark.asyncio
async def test_describe_anomaly_detectors_with_filters(client, test_db):
    """Test describing anomaly detectors with namespace and metric filters"""
    mock_response = {
        "AnomalyDetectors": [],
        "TotalCount": 0,
    }

    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.describe_anomaly_detectors",
        new_callable=AsyncMock,
        return_value=type("Response", (), mock_response)(),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/anomaly-detectors?workspace_id=test-workspace-id",
            json={
                "Namespace": "AWS/Lambda",
                "MetricName": "Duration",
                "Dimensions": [{"Name": "FunctionName", "Value": "my-function"}],
                "Limit": 25,
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_describe_anomaly_detectors_service_error(client, test_db):
    """Test describing anomaly detectors handles service errors correctly"""
    with patch(
        "app.aws.cloudwatch.Metrics.router.cloudwatch_metrics_service.describe_anomaly_detectors",
        new_callable=AsyncMock,
        side_effect=Exception("Access denied to CloudWatch"),
    ):
        response = await client.post(
            f"{API_PREFIX}/cloudwatch/metrics/anomaly-detectors?workspace_id=test-workspace-id",
            json={},
        )

    assert response.status_code == 500
    data = response.json()
    assert "Failed to describe anomaly detectors" in data["detail"]
