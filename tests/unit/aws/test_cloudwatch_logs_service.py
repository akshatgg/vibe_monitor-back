"""
Unit tests for CloudWatch Logs Service
Focus on pure functions and cache management (no DB-heavy tests)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


class TestCreateBotoSession:
    """Tests for the _create_boto_session static method"""

    @patch("app.aws.cloudwatch.Logs.service.boto3")
    def test_create_session_with_credentials(self, mock_boto3):
        """Test session creation with all credentials"""
        from app.aws.cloudwatch.Logs.service import CloudWatchLogsService

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        result = CloudWatchLogsService._create_boto_session(
            access_key_id="AKIAIOSFODNN7EXAMPLE",
            secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            session_token="FwoGZXIvYXdzEBY...",
            region="us-west-1",
        )

        mock_boto3.Session.assert_called_once_with(
            aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
            aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            aws_session_token="FwoGZXIvYXdzEBY...",
            region_name="us-west-1",
        )
        assert result == mock_session

    @patch("app.aws.cloudwatch.Logs.service.boto3")
    def test_create_session_different_region(self, mock_boto3):
        """Test session creation with different region"""
        from app.aws.cloudwatch.Logs.service import CloudWatchLogsService

        mock_session = MagicMock()
        mock_boto3.Session.return_value = mock_session

        CloudWatchLogsService._create_boto_session(
            access_key_id="AKIATEST",
            secret_access_key="secret",
            session_token="token",
            region="eu-central-1",
        )

        mock_boto3.Session.assert_called_once_with(
            aws_access_key_id="AKIATEST",
            aws_secret_access_key="secret",
            aws_session_token="token",
            region_name="eu-central-1",
        )


class TestClearClientCache:
    """Tests for the clear_client_cache static method"""

    def test_clear_specific_workspace_cache(self):
        """Test clearing cache for a specific workspace"""
        from app.aws.cloudwatch.Logs.service import CloudWatchLogsService

        # Setup: Add some entries to the cache
        workspace_id_1 = "workspace-1"
        workspace_id_2 = "workspace-2"
        CloudWatchLogsService._client_cache = {
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
        CloudWatchLogsService.clear_client_cache(workspace_id_1)

        # Verify workspace_id_1 is removed but workspace_id_2 remains
        assert workspace_id_1 not in CloudWatchLogsService._client_cache
        assert workspace_id_2 in CloudWatchLogsService._client_cache

        # Cleanup
        CloudWatchLogsService._client_cache.clear()

    def test_clear_all_cache(self):
        """Test clearing all cache entries"""
        from app.aws.cloudwatch.Logs.service import CloudWatchLogsService

        # Setup: Add some entries to the cache
        CloudWatchLogsService._client_cache = {
            "workspace-1": {
                "client": MagicMock(),
                "expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "workspace-2": {
                "client": MagicMock(),
                "expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "workspace-3": {
                "client": MagicMock(),
                "expiration": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        }

        # Clear all (pass None or no argument)
        CloudWatchLogsService.clear_client_cache()

        # Verify all entries are removed
        assert len(CloudWatchLogsService._client_cache) == 0

    def test_clear_nonexistent_workspace_cache(self):
        """Test clearing cache for a workspace that doesn't exist"""
        from app.aws.cloudwatch.Logs.service import CloudWatchLogsService

        # Setup: Empty cache
        CloudWatchLogsService._client_cache = {}

        # Should not raise an error
        CloudWatchLogsService.clear_client_cache("nonexistent-workspace")

        # Cache should still be empty
        assert len(CloudWatchLogsService._client_cache) == 0


class TestLogSchemas:
    """Tests for CloudWatch Logs schemas"""

    def test_list_log_groups_request_defaults(self):
        """Test ListLogGroupsRequest with default values"""
        from app.aws.cloudwatch.Logs.schemas import ListLogGroupsRequest

        request = ListLogGroupsRequest()

        assert request.logGroupNamePrefix is None
        assert request.limit == 100

    def test_list_log_groups_request_with_values(self):
        """Test ListLogGroupsRequest with custom values"""
        from app.aws.cloudwatch.Logs.schemas import ListLogGroupsRequest

        request = ListLogGroupsRequest(
            logGroupNamePrefix="/aws/lambda/",
            limit=100,
        )

        assert request.logGroupNamePrefix == "/aws/lambda/"
        assert request.limit == 100

    def test_list_log_streams_request(self):
        """Test ListLogStreamsRequest schema"""
        from app.aws.cloudwatch.Logs.schemas import ListLogStreamsRequest

        request = ListLogStreamsRequest(
            logGroupName="/aws/lambda/my-function",
            logStreamNamePrefix="2024/01/",
            descending=True,
            limit=25,
        )

        assert request.logGroupName == "/aws/lambda/my-function"
        assert request.logStreamNamePrefix == "2024/01/"
        assert request.descending is True
        assert request.limit == 25

    def test_get_log_events_request(self):
        """Test GetLogEventsRequest schema"""
        from app.aws.cloudwatch.Logs.schemas import GetLogEventsRequest

        request = GetLogEventsRequest(
            logGroupName="/aws/lambda/my-function",
            logStreamName="2024/01/01/[$LATEST]abc123",
            startTime=1704067200000,
            endTime=1704153600000,
            limit=100,
        )

        assert request.logGroupName == "/aws/lambda/my-function"
        assert request.logStreamName == "2024/01/01/[$LATEST]abc123"
        assert request.startTime == 1704067200000
        assert request.endTime == 1704153600000
        assert request.limit == 100

    def test_filter_log_events_request(self):
        """Test FilterLogEventsRequest schema"""
        from app.aws.cloudwatch.Logs.schemas import FilterLogEventsRequest

        request = FilterLogEventsRequest(
            logGroupName="/aws/lambda/my-function",
            logStreamNames=["stream-1", "stream-2"],
            filterPattern="ERROR",
            startTime=1704067200000,
            endTime=1704153600000,
            limit=50,
        )

        assert request.logGroupName == "/aws/lambda/my-function"
        assert request.logStreamNames == ["stream-1", "stream-2"]
        assert request.filterPattern == "ERROR"
        assert request.startTime == 1704067200000
        assert request.endTime == 1704153600000

    def test_start_query_request(self):
        """Test StartQueryRequest schema"""
        from app.aws.cloudwatch.Logs.schemas import StartQueryRequest

        request = StartQueryRequest(
            logGroupName="/aws/lambda/my-function",
            startTime=1704067200,
            endTime=1704153600,
            queryString="fields @timestamp, @message | filter @message like /ERROR/",
            limit=1000,
        )

        assert request.logGroupName == "/aws/lambda/my-function"
        assert (
            request.queryString
            == "fields @timestamp, @message | filter @message like /ERROR/"
        )
        assert request.startTime == 1704067200
        assert request.endTime == 1704153600
        assert request.limit == 1000


class TestLogResponseSchemas:
    """Tests for CloudWatch Logs response schemas"""

    def test_log_group_info(self):
        """Test LogGroupInfo schema"""
        from app.aws.cloudwatch.Logs.schemas import LogGroupInfo

        log_group = LogGroupInfo(
            logGroupName="/aws/lambda/my-function",
            arn="arn:aws:logs:us-west-1:123456789012:log-group:/aws/lambda/my-function:*",
            logGroupArn="arn:aws:logs:us-west-1:123456789012:log-group:/aws/lambda/my-function:*",
            creationTime=1704067200000,
            storedBytes=1024000,
            logGroupClass="STANDARD",
            retentionInDays=30,
        )

        assert log_group.logGroupName == "/aws/lambda/my-function"
        assert log_group.storedBytes == 1024000
        assert log_group.retentionInDays == 30
        assert log_group.logGroupClass == "STANDARD"

    def test_log_stream_info(self):
        """Test LogStreamInfo schema"""
        from app.aws.cloudwatch.Logs.schemas import LogStreamInfo

        log_stream = LogStreamInfo(
            logStreamName="2024/01/01/[$LATEST]abc123",
            arn="arn:aws:logs:us-west-1:123456789012:log-group:/aws/lambda/my-function:log-stream:2024/01/01/[$LATEST]abc123",
            creationTime=1704067200000,
            firstEventTimestamp=1704067200000,
            lastEventTimestamp=1704070800000,
            lastIngestionTime=1704070805000,
            storedBytes=512000,
        )

        assert log_stream.logStreamName == "2024/01/01/[$LATEST]abc123"
        assert log_stream.firstEventTimestamp == 1704067200000
        assert log_stream.lastEventTimestamp == 1704070800000

    def test_log_event(self):
        """Test LogEvent schema"""
        from app.aws.cloudwatch.Logs.schemas import LogEvent

        event = LogEvent(
            timestamp=1704067200000,
            message="ERROR: Something went wrong",
            ingestionTime=1704067200500,
        )

        assert event.timestamp == 1704067200000
        assert event.message == "ERROR: Something went wrong"
        assert event.ingestionTime == 1704067200500

    def test_query_result_field(self):
        """Test QueryResultField schema"""
        from app.aws.cloudwatch.Logs.schemas import QueryResultField

        field = QueryResultField(
            field="@timestamp",
            value="2024-01-01T12:00:00.000Z",
        )

        assert field.field == "@timestamp"
        assert field.value == "2024-01-01T12:00:00.000Z"

    def test_query_statistics(self):
        """Test QueryStatistics schema"""
        from app.aws.cloudwatch.Logs.schemas import QueryStatistics

        stats = QueryStatistics(
            recordsMatched=100,
            recordsScanned=10000,
            bytesScanned=1048576,
        )

        assert stats.recordsMatched == 100
        assert stats.recordsScanned == 10000
        assert stats.bytesScanned == 1048576
