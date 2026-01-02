"""
Unit tests for Datadog Metrics Service
Focus on schema validation and response parsing (no DB-heavy tests)
"""


class TestQueryTimeseriesRequestSchema:
    """Tests for QueryTimeseriesRequest schema"""

    def test_simple_query_request(self):
        """Test creating a simple query request"""
        from app.datadog.Metrics.schemas import QueryTimeseriesRequest

        request = QueryTimeseriesRequest(
            query="avg:system.cpu.user{*}",
            **{"from": 1704067200, "to": 1704153600},
        )

        assert request.query == "avg:system.cpu.user{*}"
        assert request.from_timestamp == 1704067200
        assert request.to_timestamp == 1704153600
        assert request.data is None

    def test_complex_query_request(self):
        """Test creating a complex query request with formula"""
        from app.datadog.Metrics.schemas import (
            QueryTimeseriesRequest,
            TimeseriesFormulaAndFunction,
            TimeseriesQuery,
        )

        request = QueryTimeseriesRequest(
            data=TimeseriesFormulaAndFunction(
                formula="a + b",
                queries=[
                    TimeseriesQuery(
                        data_source="metrics",
                        query="avg:system.cpu.user{host:prod-*}",
                        name="a",
                    ),
                    TimeseriesQuery(
                        data_source="metrics",
                        query="avg:system.cpu.system{host:prod-*}",
                        name="b",
                    ),
                ],
            ),
            **{"from": 1704067200, "to": 1704153600},
        )

        assert request.data is not None
        assert request.data.formula == "a + b"
        assert len(request.data.queries) == 2
        assert request.data.queries[0].name == "a"
        assert request.data.queries[1].name == "b"


class TestTimeseriesQuerySchema:
    """Tests for TimeseriesQuery schema"""

    def test_metrics_query(self):
        """Test creating a metrics query"""
        from app.datadog.Metrics.schemas import TimeseriesQuery

        query = TimeseriesQuery(
            data_source="metrics",
            query="avg:system.cpu.user{*} by {host}",
            name="cpu_usage",
        )

        assert query.data_source == "metrics"
        assert query.query == "avg:system.cpu.user{*} by {host}"
        assert query.name == "cpu_usage"

    def test_query_without_name(self):
        """Test creating a query without explicit name"""
        from app.datadog.Metrics.schemas import TimeseriesQuery

        query = TimeseriesQuery(
            data_source="metrics",
            query="avg:system.memory.used{*}",
        )

        assert query.data_source == "metrics"
        assert query.name is None


class TestTimeseriesFormulaAndFunctionSchema:
    """Tests for TimeseriesFormulaAndFunction schema"""

    def test_single_query_formula(self):
        """Test formula with single query"""
        from app.datadog.Metrics.schemas import (
            TimeseriesFormulaAndFunction,
            TimeseriesQuery,
        )

        formula = TimeseriesFormulaAndFunction(
            formula="a",
            queries=[
                TimeseriesQuery(
                    data_source="metrics",
                    query="avg:system.cpu.user{*}",
                    name="a",
                ),
            ],
        )

        assert formula.formula == "a"
        assert len(formula.queries) == 1

    def test_multi_query_formula(self):
        """Test formula with multiple queries"""
        from app.datadog.Metrics.schemas import (
            TimeseriesFormulaAndFunction,
            TimeseriesQuery,
        )

        formula = TimeseriesFormulaAndFunction(
            formula="(a / b) * 100",
            queries=[
                TimeseriesQuery(
                    data_source="metrics",
                    query="sum:requests.error{*}",
                    name="a",
                ),
                TimeseriesQuery(
                    data_source="metrics",
                    query="sum:requests.total{*}",
                    name="b",
                ),
            ],
        )

        assert formula.formula == "(a / b) * 100"
        assert len(formula.queries) == 2


class TestSimpleQueryRequestSchema:
    """Tests for SimpleQueryRequest schema"""

    def test_simple_query(self):
        """Test creating a simple query request"""
        from app.datadog.Metrics.schemas import SimpleQueryRequest

        request = SimpleQueryRequest(
            query="avg:system.cpu.user{*}",
            from_timestamp=1704067200,
            to_timestamp=1704153600,
        )

        assert request.query == "avg:system.cpu.user{*}"
        assert request.from_timestamp == 1704067200
        assert request.to_timestamp == 1704153600


class TestEventsSearchRequestSchema:
    """Tests for EventsSearchRequest schema"""

    def test_events_search_request(self):
        """Test creating an events search request"""
        from app.datadog.Metrics.schemas import EventsSearchRequest

        request = EventsSearchRequest(
            start=1704067200,
            end=1704153600,
            tags="env:production,service:api",
        )

        assert request.start == 1704067200
        assert request.end == 1704153600
        assert request.tags == "env:production,service:api"

    def test_events_search_request_without_tags(self):
        """Test creating an events search request without tags"""
        from app.datadog.Metrics.schemas import EventsSearchRequest

        request = EventsSearchRequest(
            start=1704067200,
            end=1704153600,
        )

        assert request.start == 1704067200
        assert request.end == 1704153600
        assert request.tags is None


class TestTimeseriesResponseSchemas:
    """Tests for timeseries response schemas"""

    def test_timeseries_series(self):
        """Test TimeseriesSeries schema"""
        from app.datadog.Metrics.schemas import TimeseriesSeries

        series = TimeseriesSeries(
            group_tags=["host:prod-01", "env:production"],
            query_index=0,
            unit=[
                {
                    "family": "percentage",
                    "scale_factor": 1,
                    "name": "percent",
                    "short_name": "%",
                }
            ],
        )

        assert series.group_tags == ["host:prod-01", "env:production"]
        assert series.query_index == 0
        assert series.unit is not None

    def test_timeseries_attributes(self):
        """Test TimeseriesAttributes schema"""
        from app.datadog.Metrics.schemas import TimeseriesAttributes, TimeseriesSeries

        series = TimeseriesSeries(
            group_tags=["host:prod-01"],
            query_index=0,
        )

        attrs = TimeseriesAttributes(
            series=[series],
            times=[1704067200000, 1704067500000, 1704067800000],
            values=[[45.5, 50.2, 48.8]],
        )

        assert len(attrs.series) == 1
        assert len(attrs.times) == 3
        assert len(attrs.values) == 1
        assert len(attrs.values[0]) == 3

    def test_timeseries_data(self):
        """Test TimeseriesData schema"""
        from app.datadog.Metrics.schemas import (
            TimeseriesAttributes,
            TimeseriesData,
            TimeseriesSeries,
        )

        series = TimeseriesSeries(group_tags=[], query_index=0)
        attrs = TimeseriesAttributes(
            series=[series],
            times=[1704067200000],
            values=[[45.5]],
        )

        data = TimeseriesData(
            type="timeseries_response",
            attributes=attrs,
        )

        assert data.type == "timeseries_response"
        assert data.attributes is not None

    def test_query_timeseries_response(self):
        """Test QueryTimeseriesResponse schema"""
        from app.datadog.Metrics.schemas import (
            QueryTimeseriesResponse,
            TimeseriesAttributes,
            TimeseriesData,
            TimeseriesSeries,
        )

        series = TimeseriesSeries(group_tags=[], query_index=0)
        attrs = TimeseriesAttributes(
            series=[series],
            times=[1704067200000],
            values=[[45.5]],
        )
        data = TimeseriesData(type="timeseries_response", attributes=attrs)

        response = QueryTimeseriesResponse(data=data, errors=None)

        assert response.data is not None
        assert response.errors is None

    def test_query_timeseries_response_with_errors(self):
        """Test QueryTimeseriesResponse with errors"""
        from app.datadog.Metrics.schemas import QueryTimeseriesResponse

        response = QueryTimeseriesResponse(
            data=None,
            errors="Invalid query syntax",
        )

        assert response.data is None
        assert response.errors == "Invalid query syntax"


class TestSimpleQueryResponseSchema:
    """Tests for SimpleQueryResponse schema"""

    def test_simple_query_response(self):
        """Test creating a simple query response"""
        from app.datadog.Metrics.schemas import SimpleMetricPoint, SimpleQueryResponse

        points = [
            SimpleMetricPoint(timestamp=1704067200000, value=45.5),
            SimpleMetricPoint(timestamp=1704067500000, value=50.2),
            SimpleMetricPoint(timestamp=1704067800000, value=48.8),
        ]

        response = SimpleQueryResponse(
            query="avg:system.cpu.user{*}",
            points=points,
            totalPoints=3,
        )

        assert response.query == "avg:system.cpu.user{*}"
        assert len(response.points) == 3
        assert response.points[0].value == 45.5
        assert response.totalPoints == 3

    def test_empty_simple_query_response(self):
        """Test creating an empty simple query response"""
        from app.datadog.Metrics.schemas import SimpleQueryResponse

        response = SimpleQueryResponse(
            query="avg:system.cpu.user{*}",
            points=[],
            totalPoints=0,
        )

        assert len(response.points) == 0
        assert response.totalPoints == 0


class TestSimpleMetricPointSchema:
    """Tests for SimpleMetricPoint schema"""

    def test_metric_point(self):
        """Test creating a metric point"""
        from app.datadog.Metrics.schemas import SimpleMetricPoint

        point = SimpleMetricPoint(
            timestamp=1704067200000,
            value=45.5,
        )

        assert point.timestamp == 1704067200000
        assert point.value == 45.5

    def test_metric_point_with_none_value(self):
        """Test creating a metric point with None value (gap in data)"""
        from app.datadog.Metrics.schemas import SimpleMetricPoint

        point = SimpleMetricPoint(
            timestamp=1704067200000,
            value=None,
        )

        assert point.timestamp == 1704067200000
        assert point.value is None


class TestEventItemSchema:
    """Tests for EventItem schema"""

    def test_event_item_full(self):
        """Test creating a full EventItem"""
        from app.datadog.Metrics.schemas import EventItem

        event = EventItem(
            id=12345,
            title="Deployment started",
            text="Deploying version 2.0 to production",
            date_happened=1704067200,
            alert_type="info",
            priority="normal",
            source="deployment-pipeline",
            tags=["env:production", "service:api"],
            host="prod-server-01",
            device_name=None,
            url="https://example.com/deploy/123",
        )

        assert event.id == 12345
        assert event.title == "Deployment started"
        assert event.alert_type == "info"
        assert event.priority == "normal"
        assert "env:production" in event.tags

    def test_event_item_minimal(self):
        """Test creating a minimal EventItem"""
        from app.datadog.Metrics.schemas import EventItem

        event = EventItem(
            id=12345,
            title="Test event",
        )

        assert event.id == 12345
        assert event.title == "Test event"
        assert event.text is None
        assert event.tags is None


class TestEventsSearchResponseSchema:
    """Tests for EventsSearchResponse schema"""

    def test_events_search_response(self):
        """Test creating EventsSearchResponse"""
        from app.datadog.Metrics.schemas import EventItem, EventsSearchResponse

        events = [
            EventItem(id=1, title="Event 1", alert_type="info"),
            EventItem(id=2, title="Event 2", alert_type="warning"),
        ]

        response = EventsSearchResponse(
            events=events,
            totalCount=2,
        )

        assert len(response.events) == 2
        assert response.events[0].title == "Event 1"
        assert response.events[1].alert_type == "warning"
        assert response.totalCount == 2

    def test_empty_events_response(self):
        """Test creating empty EventsSearchResponse"""
        from app.datadog.Metrics.schemas import EventsSearchResponse

        response = EventsSearchResponse(
            events=[],
            totalCount=0,
        )

        assert len(response.events) == 0
        assert response.totalCount == 0


class TestTagsListResponseSchema:
    """Tests for TagsListResponse schema"""

    def test_tags_list_response(self):
        """Test creating TagsListResponse"""
        from app.datadog.Metrics.schemas import TagsListResponse

        response = TagsListResponse(
            tags=["env:production", "env:staging", "service:api", "service:web"],
            tagsByCategory={
                "env": ["production", "staging"],
                "service": ["api", "web"],
            },
            totalTags=4,
        )

        assert len(response.tags) == 4
        assert "env:production" in response.tags
        assert response.tagsByCategory["env"] == ["production", "staging"]
        assert response.tagsByCategory["service"] == ["api", "web"]
        assert response.totalTags == 4

    def test_empty_tags_response(self):
        """Test creating empty TagsListResponse"""
        from app.datadog.Metrics.schemas import TagsListResponse

        response = TagsListResponse(
            tags=[],
            tagsByCategory={},
            totalTags=0,
        )

        assert len(response.tags) == 0
        assert len(response.tagsByCategory) == 0
        assert response.totalTags == 0
