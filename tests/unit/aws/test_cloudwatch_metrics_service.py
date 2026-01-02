"""
Unit tests for CloudWatch Metrics Service
Focus on pure functions and cache management (no DB-heavy tests)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


class TestCreateBotoSession:
    """Tests for the _create_boto_session static method"""

    @patch("app.aws.cloudwatch.Metrics.service.boto3")
    def test_create_session_with_credentials(self, mock_boto3):
        """Test session creation with all credentials"""
        from app.aws.cloudwatch.Metrics.service import CloudWatchMetricsService

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        result = CloudWatchMetricsService._create_boto_session(
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            session_token="FwoGZXIvYXdzEBY...",
            region="us-west-2",
        )

        mock_boto3.Session.assert_called_once_with(
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            aws_session_token="FwoGZXIvYXdzEBY...",
            region_name="us-west-2",
        )
        assert result == mock_session

    @patch("app.aws.cloudwatch.Metrics.service.boto3")
    def test_create_session_different_region(self, mock_boto3):
        """Test session creation with different region"""
        from app.aws.cloudwatch.Metrics.service import CloudWatchMetricsService

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        CloudWatchMetricsService._create_boto_session(
            access_key_id="AKIATEST",
            secret_access_key="secret",
            session_token="token",
            region="ap-southeast-1",
        )

        mock_boto3.Session.assert_called_once_with(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
            aws_session_token="token",
            region_name="ap-southeast-1",
        )


class TestClearClientCache:
    """Tests for the clear_client_cache static method"""

    def test_clear_specific_workspace_cache(self):
        """Test clearing cache for a specific workspace"""
        from app.aws.cloudwatch.Metrics.service import CloudWatchMetricsService

        # Setup: Add some entries to the cache
        workspace_id_1 = "workspace-1"
        workspace_id_2 = "workspace-2"
        CloudWatchMetricsService._client_cache = {
            workspace_id_1: {
                "client": MagicMock(),
                "expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            workspace_id_2: {
                "client": MagicMock(),
                "expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        }

        # Clear only workspace_id_1
        CloudWatchMetricsService.clear_client_cache(workspace_id_1)

        # Verify workspace_id_1 is removed but workspace_id_2 remains
        assert workspace_id_1 not in CloudWatchMetricsService._client_cache
        assert workspace_id_2 in CloudWatchMetricsService._client_cache

        # Cleanup
        CloudWatchMetricsService._client_cache.clear()

    def test_clear_all_cache(self):
        """Test clearing all cache entries"""
        from app.aws.cloudwatch.Metrics.service import CloudWatchMetricsService

        # Setup: Add some entries to the cache
        CloudWatchMetricsService._client_cache = {
            "workspace-1": {
                "client": MagicMock(),
                "expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "workspace-2": {
                "client": MagicMock(),
                "expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        }

        # Clear all
        CloudWatchMetricsService.clear_client_cache()

        # Verify all entries are removed
        assert len(CloudWatchMetricsService._client_cache) == 0

    def test_clear_nonexistent_workspace_cache(self):
        """Test clearing cache for a workspace that doesn't exist"""
        from app.aws.cloudwatch.Metrics.service import CloudWatchMetricsService

        # Setup: Empty cache
        CloudWatchMetricsService._client_cache = {}

        # Should not raise an error
        CloudWatchMetricsService.clear_client_cache("nonexistent-workspace")

        # Cache should still be empty
        assert len(CloudWatchMetricsService._client_cache) == 0


class TestMetricsSchemas:
    """Tests for CloudWatch Metrics schemas"""

    def test_list_metrics_request_defaults(self):
        """Test ListMetricsRequest with default values"""
        from app.aws.cloudwatch.Metrics.schemas import ListMetricsRequest

        request = ListMetricsRequest()

        assert request.Namespace is None
        assert request.MetricName is None
        assert request.Dimensions is None
        assert request.Limit == 50

    def test_list_metrics_request_with_values(self):
        """Test ListMetricsRequest with custom values"""
        from app.aws.cloudwatch.Metrics.schemas import (
            DimensionFilter,
            ListMetricsRequest,
        )

        request = ListMetricsRequest(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[
                DimensionFilter(Name="InstanceId", Value="i-1234567890abcdef0")
            ],
            Limit=100,
        )

        assert request.Namespace == "AWS/EC2"
        assert request.MetricName == "CPUUtilization"
        assert len(request.Dimensions) == 1
        assert request.Dimensions[0].Name == "InstanceId"
        assert request.Limit == 100

    def test_dimension_filter(self):
        """Test DimensionFilter schema"""
        from app.aws.cloudwatch.Metrics.schemas import DimensionFilter

        dim = DimensionFilter(Name="InstanceId", Value="i-1234567890abcdef0")

        assert dim.Name == "InstanceId"
        assert dim.Value == "i-1234567890abcdef0"

    def test_dimension_filter_without_value(self):
        """Test DimensionFilter without value (used for filtering by dimension name only)"""
        from app.aws.cloudwatch.Metrics.schemas import DimensionFilter

        dim = DimensionFilter(Name="InstanceId")

        assert dim.Name == "InstanceId"
        assert dim.Value is None

    def test_get_metric_statistics_request(self):
        """Test GetMetricStatisticsRequest schema"""
        from app.aws.cloudwatch.Metrics.schemas import (
            Dimension,
            GetMetricStatisticsRequest,
        )

        request = GetMetricStatisticsRequest(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            StartTime=1704067200,
            EndTime=1704153600,
            Period=300,
            Statistics=["Average", "Maximum"],
            Dimensions=[Dimension(Name="InstanceId", Value="i-1234567890abcdef0")],
            MaxDatapoints=100,
        )

        assert request.Namespace == "AWS/EC2"
        assert request.MetricName == "CPUUtilization"
        assert request.Period == 300
        assert "Average" in request.Statistics
        assert "Maximum" in request.Statistics
        assert request.MaxDatapoints == 100

    def test_list_metric_streams_request_defaults(self):
        """Test ListMetricStreamsRequest with default values"""
        from app.aws.cloudwatch.Metrics.schemas import ListMetricStreamsRequest

        request = ListMetricStreamsRequest()

        assert request.Limit == 50

    def test_get_metric_stream_request(self):
        """Test GetMetricStreamRequest schema"""
        from app.aws.cloudwatch.Metrics.schemas import GetMetricStreamRequest

        request = GetMetricStreamRequest(Name="my-metric-stream")

        assert request.Name == "my-metric-stream"

    def test_describe_anomaly_detectors_request(self):
        """Test DescribeAnomalyDetectorsRequest schema"""
        from app.aws.cloudwatch.Metrics.schemas import (
            DescribeAnomalyDetectorsRequest,
            Dimension,
        )

        request = DescribeAnomalyDetectorsRequest(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[Dimension(Name="InstanceId", Value="i-1234567890abcdef0")],
            Limit=25,
        )

        assert request.Namespace == "AWS/EC2"
        assert request.MetricName == "CPUUtilization"
        assert request.Limit == 25


class TestMetricsResponseSchemas:
    """Tests for CloudWatch Metrics response schemas"""

    def test_metric_info(self):
        """Test MetricInfo schema"""
        from app.aws.cloudwatch.Metrics.schemas import MetricInfo

        metric = MetricInfo(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": "i-1234567890abcdef0"}],
        )

        assert metric.Namespace == "AWS/EC2"
        assert metric.MetricName == "CPUUtilization"
        assert len(metric.Dimensions) == 1

    def test_datapoint(self):
        """Test Datapoint schema"""
        from app.aws.cloudwatch.Metrics.schemas import Datapoint

        datapoint = Datapoint(
            Timestamp=datetime.now(timezone.utc),
            Average=45.5,
            Maximum=90.0,
            Minimum=10.0,
            Sum=455.0,
            SampleCount=10.0,
            Unit="Percent",
        )

        assert datapoint.Average == 45.5
        assert datapoint.Maximum == 90.0
        assert datapoint.Minimum == 10.0
        assert datapoint.Unit == "Percent"

    def test_metric_data_result(self):
        """Test MetricDataResult schema"""
        from app.aws.cloudwatch.Metrics.schemas import MetricDataResult

        result = MetricDataResult(
            Id="m1",
            Label="CPUUtilization",
            Timestamps=[datetime.now(timezone.utc)],
            Values=[45.5],
            StatusCode="Complete",
        )

        assert result.Id == "m1"
        assert result.Label == "CPUUtilization"
        assert result.StatusCode == "Complete"

    def test_anomaly_detector(self):
        """Test AnomalyDetector schema"""
        from app.aws.cloudwatch.Metrics.schemas import AnomalyDetector

        detector = AnomalyDetector(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": "i-1234567890abcdef0"}],
            Stat="Average",
            StateValue="TRAINED_INSUFFICIENT_DATA",
        )

        assert detector.Namespace == "AWS/EC2"
        assert detector.MetricName == "CPUUtilization"
        assert detector.Stat == "Average"
        assert detector.StateValue == "TRAINED_INSUFFICIENT_DATA"

    def test_metric_stream_info(self):
        """Test MetricStreamInfo schema"""
        from datetime import datetime, timezone

        from app.aws.cloudwatch.Metrics.schemas import MetricStreamInfo

        now = datetime.now(timezone.utc)
        stream = MetricStreamInfo(
            Arn="arn:aws:cloudwatch:us-west-1:123456789012:metric-stream/my-stream",
            Name="my-stream",
            FirehoseArn="arn:aws:firehose:us-west-1:123456789012:deliverystream/my-firehose",
            State="running",
            OutputFormat="json",
            CreationDate=now,
            LastUpdateDate=now,
        )

        assert stream.Name == "my-stream"
        assert stream.State == "running"
        assert stream.OutputFormat == "json"


class TestGetMetricDataRequest:
    """Tests for GetMetricDataRequest schema"""

    def test_get_metric_data_request(self):
        """Test GetMetricDataRequest with MetricStat"""
        from app.aws.cloudwatch.Metrics.schemas import (
            GetMetricDataRequest,
            MetricDataQuery,
            MetricSpecification,
            MetricStat,
        )

        request = GetMetricDataRequest(
            MetricDataQueries=[
                MetricDataQuery(
                    Id="m1",
                    metric_stat=MetricStat(
                        Metric=MetricSpecification(
                            Namespace="AWS/EC2",
                            MetricName="CPUUtilization",
                        ),
                        Period=300,
                        Stat="Average",
                    ),
                )
            ],
            StartTime=1704067200,
            EndTime=1704153600,
            MaxDatapoints=100,
        )

        assert len(request.MetricDataQueries) == 1
        assert request.MetricDataQueries[0].Id == "m1"
        assert request.StartTime == 1704067200
        assert request.EndTime == 1704153600
        assert request.MaxDatapoints == 100

    def test_metric_specification_with_dimensions(self):
        """Test MetricSpecification with dimensions"""
        from app.aws.cloudwatch.Metrics.schemas import (
            MetricDimension,
            MetricSpecification,
        )

        spec = MetricSpecification(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[
                MetricDimension(Name="InstanceId", Value="i-1234567890abcdef0")
            ],
        )

        assert spec.Namespace == "AWS/EC2"
        assert spec.MetricName == "CPUUtilization"
        assert len(spec.Dimensions) == 1
        assert spec.Dimensions[0].Name == "InstanceId"
