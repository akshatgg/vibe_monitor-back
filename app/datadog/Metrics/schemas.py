"""
Pydantic schemas for Datadog Metrics API
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ===== Query Timeseries Schemas =====

class TimeseriesQuery(BaseModel):
    """Schema for a timeseries query"""
    data_source: str = Field(
        "metrics",
        description="Data source (default: 'metrics')"
    )
    query: str = Field(
        ...,
        description="Metrics query string (e.g., 'avg:system.cpu.user{*}')"
    )
    name: Optional[str] = Field(
        None,
        description="Name for this query"
    )


class TimeseriesFormulaAndFunction(BaseModel):
    """Schema for formulas and functions"""
    formula: str = Field(..., description="Formula to apply")
    queries: List[TimeseriesQuery] = Field(..., description="List of queries")


class QueryTimeseriesRequest(BaseModel):
    """
    Request schema for querying timeseries data

    Supports two formats:
    1. Simple format (for single queries):
       {"query": "avg:cpu{*}", "from": ..., "to": ...}

    2. Complex format (for multiple queries with formulas):
       {"data": {"formula": "a+b", "queries": [...]}, "from": ..., "to": ...}
    """
    # Simple format - single query string
    query: Optional[str] = Field(
        None,
        description="Simple single query (e.g., 'avg:system.cpu.user{*}'). Use this for RCA bot."
    )

    # Complex format - multiple queries with formula
    data: Optional[TimeseriesFormulaAndFunction] = Field(
        None,
        description="Formula and function data for complex queries"
    )

    from_timestamp: int = Field(
        ...,
        description="Start time in milliseconds since epoch",
        alias="from"
    )
    to_timestamp: int = Field(
        ...,
        description="End time in milliseconds since epoch",
        alias="to"
    )

    class Config:
        populate_by_name = True

    def __init__(self, **data):
        super().__init__(**data)
        # Validate that exactly one of 'query' or 'data' is provided
        if self.query and self.data:
            raise ValueError("Provide either 'query' (simple) OR 'data' (complex), not both")
        if not self.query and not self.data:
            raise ValueError("Either 'query' or 'data' is required")


class TimeseriesPoint(BaseModel):
    """Schema for a single timeseries point"""
    timestamp: int = Field(..., description="Timestamp in milliseconds")
    value: Optional[float] = Field(None, description="Metric value")


class TimeseriesSeries(BaseModel):
    """Schema for a timeseries series - metadata only, actual data is in times/values arrays"""
    group_tags: Optional[List[str]] = Field(None, description="Group tags")
    query_index: Optional[int] = Field(None, description="Query index")
    unit: Optional[List[Optional[Dict[str, Any]]]] = Field(None, description="Unit information")


class TimeseriesAttributes(BaseModel):
    """Schema for timeseries attributes"""
    series: List[TimeseriesSeries] = Field(..., description="List of series")
    times: Optional[List[int]] = Field(None, description="Timestamps")
    values: Optional[List[List[Optional[float]]]] = Field(None, description="Values")


class TimeseriesData(BaseModel):
    """Schema for timeseries data"""
    type: str = Field("timeseries", description="Data type")
    attributes: TimeseriesAttributes = Field(..., description="Timeseries attributes")


class QueryTimeseriesResponse(BaseModel):
    """Response schema for timeseries query"""
    data: Optional[TimeseriesData] = Field(None, description="Timeseries data")
    errors: Optional[str] = Field(None, description="Error message if query failed")



# ===== Simplified Query Schemas =====

class SimpleQueryRequest(BaseModel):
    """Simplified request schema for querying metrics"""
    query: str = Field(
        ...,
        description="Metrics query (e.g., 'avg:system.cpu.user{*}')"
    )
    from_timestamp: int = Field(
        ...,
        description="Start time in milliseconds since epoch"
    )
    to_timestamp: int = Field(
        ...,
        description="End time in milliseconds since epoch"
    )


class SimpleMetricPoint(BaseModel):
    """Simplified metric point"""
    timestamp: int = Field(..., description="Timestamp in milliseconds")
    value: Optional[float] = Field(None, description="Metric value")


class SimpleQueryResponse(BaseModel):
    """Simplified response schema for metrics query"""
    query: str = Field(..., description="Original query string")
    points: List[SimpleMetricPoint] = Field(..., description="List of data points")
    totalPoints: int = Field(..., description="Total number of points")


# ===== Events Schemas =====

class EventsSearchRequest(BaseModel):
    """Request schema for searching Datadog events"""
    start: int = Field(
        ...,
        description="Start time in seconds since epoch"
    )
    end: int = Field(
        ...,
        description="End time in seconds since epoch"
    )
    tags: Optional[str] = Field(
        None,
        description="Comma-separated list of tags (e.g., 'env:prod,service:api')"
    )


class EventItem(BaseModel):
    """Schema for a single event"""
    id: Optional[int] = Field(None, description="Event ID")
    title: Optional[str] = Field(None, description="Event title")
    text: Optional[str] = Field(None, description="Event text/description")
    date_happened: Optional[int] = Field(None, description="Timestamp when event occurred (seconds)")
    alert_type: Optional[str] = Field(None, description="Alert type: info, warning, error, success")
    priority: Optional[str] = Field(None, description="Event priority: normal or low")
    source: Optional[str] = Field(None, description="Event source")
    tags: Optional[List[str]] = Field(None, description="Event tags")
    host: Optional[str] = Field(None, description="Host associated with event")
    device_name: Optional[str] = Field(None, description="Device name")
    url: Optional[str] = Field(None, description="URL to event in Datadog")


class EventsSearchResponse(BaseModel):
    """Response schema for events search"""
    events: List[EventItem] = Field(..., description="List of events")
    totalCount: int = Field(..., description="Total number of events returned")


# ===== Tags Discovery Schemas =====

class TagsListResponse(BaseModel):
    """Response schema for listing available tags"""
    tags: List[str] = Field(..., description="List of all tags (e.g., ['env:prod', 'service:api'])")
    tagsByCategory: Dict[str, List[str]] = Field(
        ...,
        description="Tags organized by category (e.g., {'env': ['prod', 'staging'], 'service': ['api', 'db']})"
    )
    totalTags: int = Field(..., description="Total number of unique tags")
