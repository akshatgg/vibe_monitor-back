"""
Unit tests for Datadog Logs Service
Focus on schema validation and response parsing (no DB-heavy tests)
"""


class TestSearchLogsRequestSchema:
    """Tests for SearchLogsRequest schema"""

    def test_valid_request_with_defaults(self):
        """Test creating a valid request with default values"""
        from app.datadog.Logs.schemas import SearchLogsRequest

        request = SearchLogsRequest(query="*")

        assert request.query == "*"
        assert request.from_time is None
        assert request.to_time is None
        assert request.sort == "desc"
        assert request.limit == 100

    def test_valid_request_with_time_range(self):
        """Test creating a valid request with time range"""
        from app.datadog.Logs.schemas import SearchLogsRequest

        request = SearchLogsRequest(
            query="service:my-app status:error",
            **{"from": 1704067200000, "to": 1704153600000},
            sort="-timestamp",
            limit=50,
        )

        assert request.query == "service:my-app status:error"
        assert request.from_time == 1704067200000
        assert request.to_time == 1704153600000
        assert request.sort == "-timestamp"
        assert request.limit == 50

    def test_complex_query(self):
        """Test request with complex Datadog query syntax"""
        from app.datadog.Logs.schemas import SearchLogsRequest

        request = SearchLogsRequest(
            query='service:api-gateway host:prod-* @http.status_code:>=500 "connection timeout"',
        )

        assert "service:api-gateway" in request.query
        assert "@http.status_code:>=500" in request.query


class TestListLogsRequestSchema:
    """Tests for ListLogsRequest schema"""

    def test_valid_request_with_defaults(self):
        """Test creating a valid request with default values"""
        from app.datadog.Logs.schemas import ListLogsRequest

        request = ListLogsRequest(query="*")

        assert request.query == "*"
        assert request.from_time is None
        assert request.to_time is None
        assert request.limit == 100

    def test_valid_request_with_custom_limit(self):
        """Test creating a valid request with custom limit"""
        from app.datadog.Logs.schemas import ListLogsRequest

        request = ListLogsRequest(
            query="service:payment-service",
            limit=25,
        )

        assert request.query == "service:payment-service"
        assert request.limit == 25


class TestListServicesRequestSchema:
    """Tests for ListServicesRequest schema"""

    def test_valid_request_with_defaults(self):
        """Test creating a valid request with default values"""
        from app.datadog.Logs.schemas import ListServicesRequest

        request = ListServicesRequest()

        assert request.from_time is None
        assert request.to_time is None
        assert request.limit == 1000

    def test_valid_request_with_time_range(self):
        """Test creating a valid request with time range"""
        from app.datadog.Logs.schemas import ListServicesRequest

        request = ListServicesRequest(
            **{"from": 1704067200000, "to": 1704153600000},
            limit=500,
        )

        assert request.from_time == 1704067200000
        assert request.to_time == 1704153600000
        assert request.limit == 500


class TestLogAttributesSchema:
    """Tests for LogAttributes schema"""

    def test_full_attributes(self):
        """Test creating LogAttributes with all fields"""
        from app.datadog.Logs.schemas import LogAttributes

        attrs = LogAttributes(
            timestamp="2024-01-01T12:00:00.000Z",
            host="prod-server-01",
            service="api-gateway",
            status="error",
            message="Connection timeout",
            tags=["env:production", "team:backend"],
            attributes={"http.status_code": 500, "duration_ms": 1234},
        )

        assert attrs.timestamp == "2024-01-01T12:00:00.000Z"
        assert attrs.host == "prod-server-01"
        assert attrs.service == "api-gateway"
        assert attrs.status == "error"
        assert attrs.message == "Connection timeout"
        assert "env:production" in attrs.tags
        assert attrs.attributes["http.status_code"] == 500

    def test_minimal_attributes(self):
        """Test creating LogAttributes with minimal fields"""
        from app.datadog.Logs.schemas import LogAttributes

        attrs = LogAttributes()

        assert attrs.timestamp is None
        assert attrs.host is None
        assert attrs.service is None
        assert attrs.status is None
        assert attrs.message is None
        assert attrs.tags is None
        assert attrs.attributes is None


class TestLogDataSchema:
    """Tests for LogData schema"""

    def test_log_data_creation(self):
        """Test creating LogData"""
        from app.datadog.Logs.schemas import LogAttributes, LogData

        attrs = LogAttributes(
            timestamp="2024-01-01T12:00:00.000Z",
            message="Test log message",
            service="test-service",
        )

        log_data = LogData(
            id="log-id-123",
            type="log",
            attributes=attrs,
        )

        assert log_data.id == "log-id-123"
        assert log_data.type == "log"
        assert log_data.attributes.message == "Test log message"


class TestSimplifiedLogEntrySchema:
    """Tests for SimplifiedLogEntry schema"""

    def test_simplified_log_entry(self):
        """Test creating SimplifiedLogEntry"""
        from app.datadog.Logs.schemas import SimplifiedLogEntry

        entry = SimplifiedLogEntry(
            timestamp="2024-01-01T12:00:00.000Z",
            message="Error processing request",
            service="payment-service",
            host="prod-01",
            status="error",
            tags=["env:prod", "version:2.0"],
        )

        assert entry.timestamp == "2024-01-01T12:00:00.000Z"
        assert entry.message == "Error processing request"
        assert entry.service == "payment-service"
        assert entry.status == "error"

    def test_simplified_log_entry_minimal(self):
        """Test creating SimplifiedLogEntry with required fields only"""
        from app.datadog.Logs.schemas import SimplifiedLogEntry

        entry = SimplifiedLogEntry(
            timestamp="2024-01-01T12:00:00.000Z",
            message="Test message",
        )

        assert entry.timestamp == "2024-01-01T12:00:00.000Z"
        assert entry.message == "Test message"
        assert entry.service is None
        assert entry.host is None
        assert entry.status is None
        assert entry.tags is None


class TestLogLinksSchema:
    """Tests for LogLinks schema"""

    def test_log_links_with_next(self):
        """Test LogLinks with next cursor"""
        from app.datadog.Logs.schemas import LogLinks

        links = LogLinks(next="eyJhZnRlciI6IjE3MDQwNjcyMDAwMDAifQ==")

        assert links.next == "eyJhZnRlciI6IjE3MDQwNjcyMDAwMDAifQ=="

    def test_log_links_without_next(self):
        """Test LogLinks without next cursor"""
        from app.datadog.Logs.schemas import LogLinks

        links = LogLinks()

        assert links.next is None


class TestLogMetaSchema:
    """Tests for LogMeta schema"""

    def test_log_meta_full(self):
        """Test LogMeta with all fields"""
        from app.datadog.Logs.schemas import LogMeta

        meta = LogMeta(
            elapsed=1234,
            page={"after": "cursor-123"},
            request_id="req-abc-123",
            status="done",
            warnings=[{"code": "warning", "message": "Some warning"}],
        )

        assert meta.elapsed == 1234
        assert meta.page == {"after": "cursor-123"}
        assert meta.request_id == "req-abc-123"
        assert meta.status == "done"
        assert meta.warnings == [{"code": "warning", "message": "Some warning"}]

    def test_log_meta_minimal(self):
        """Test LogMeta with minimal fields"""
        from app.datadog.Logs.schemas import LogMeta

        meta = LogMeta()

        assert meta.elapsed is None
        assert meta.page is None
        assert meta.request_id is None
        assert meta.status is None
        assert meta.warnings is None


class TestSearchLogsResponseSchema:
    """Tests for SearchLogsResponse schema"""

    def test_search_logs_response(self):
        """Test creating SearchLogsResponse"""
        from app.datadog.Logs.schemas import (
            LogAttributes,
            LogData,
            LogLinks,
            LogMeta,
            SearchLogsResponse,
        )

        attrs = LogAttributes(
            timestamp="2024-01-01T12:00:00.000Z",
            message="Test message",
            service="test-service",
        )
        log_data = LogData(id="log-1", type="log", attributes=attrs)

        response = SearchLogsResponse(
            data=[log_data],
            links=LogLinks(next="cursor-123"),
            meta=LogMeta(status="done"),
            totalCount=1,
        )

        assert len(response.data) == 1
        assert response.data[0].id == "log-1"
        assert response.links.next == "cursor-123"
        assert response.meta.status == "done"
        assert response.totalCount == 1

    def test_empty_search_logs_response(self):
        """Test creating empty SearchLogsResponse"""
        from app.datadog.Logs.schemas import SearchLogsResponse

        response = SearchLogsResponse(
            data=[],
            links=None,
            meta=None,
            totalCount=0,
        )

        assert len(response.data) == 0
        assert response.totalCount == 0


class TestListLogsResponseSchema:
    """Tests for ListLogsResponse schema"""

    def test_list_logs_response(self):
        """Test creating ListLogsResponse"""
        from app.datadog.Logs.schemas import ListLogsResponse, SimplifiedLogEntry

        entry = SimplifiedLogEntry(
            timestamp="2024-01-01T12:00:00.000Z",
            message="Test message",
            service="test-service",
        )

        response = ListLogsResponse(
            logs=[entry],
            totalCount=1,
        )

        assert len(response.logs) == 1
        assert response.logs[0].message == "Test message"
        assert response.totalCount == 1


class TestListServicesResponseSchema:
    """Tests for ListServicesResponse schema"""

    def test_list_services_response(self):
        """Test creating ListServicesResponse"""
        from app.datadog.Logs.schemas import ListServicesResponse

        response = ListServicesResponse(
            services=["api-gateway", "payment-service", "user-service"],
            totalCount=3,
        )

        assert len(response.services) == 3
        assert "api-gateway" in response.services
        assert "payment-service" in response.services
        assert response.totalCount == 3

    def test_empty_services_response(self):
        """Test creating empty ListServicesResponse"""
        from app.datadog.Logs.schemas import ListServicesResponse

        response = ListServicesResponse(
            services=[],
            totalCount=0,
        )

        assert len(response.services) == 0
        assert response.totalCount == 0
