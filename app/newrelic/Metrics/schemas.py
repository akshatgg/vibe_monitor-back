"""
Pydantic schemas for New Relic Metrics API
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ===== Metric Query Schemas =====


class QueryMetricsRequest(BaseModel):
    """Request schema for querying New Relic metrics using NRQL"""

    nrql_query: str = Field(
        ...,
        description="NRQL query string for metrics (e.g., 'SELECT average(duration) FROM Transaction ...')",
    )


class MetricDataPoint(BaseModel):
    """Schema for a single metric data point"""

    timestamp: Optional[int] = Field(None, description="Data point timestamp")
    value: Optional[float] = Field(None, description="Metric value")
    attributes: Optional[Dict[str, Any]] = Field(
        None, description="Additional attributes"
    )


class QueryMetricsResponse(BaseModel):
    """Response schema for metric query results"""

    results: List[Dict[str, Any]] = Field(
        ..., description="Query results as list of metric data points"
    )
    totalCount: int = Field(..., description="Total number of results returned")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Query metadata")


# ===== Time Series Metrics Schemas =====


class GetTimeSeriesRequest(BaseModel):
    """Request schema for getting time series metrics"""

    metric_name: str = Field(
        ..., description="Metric name (e.g., 'apm.service.transaction.duration')"
    )
    startTime: int = Field(..., description="Start time in seconds since epoch")
    endTime: int = Field(..., description="End time in seconds since epoch")
    aggregation: Optional[str] = Field(
        "average", description="Aggregation function: average, sum, min, max, count"
    )
    timeseries: Optional[bool] = Field(
        True, description="Return as time series (default: true)"
    )
    where_clause: Optional[str] = Field(
        None, description="Optional WHERE clause for filtering"
    )


class TimeSeriesDataPoint(BaseModel):
    """Schema for a time series data point"""

    timestamp: int = Field(..., description="Timestamp in seconds")
    value: Optional[float] = Field(
        None, description="Metric value (can be None if no data)"
    )


class GetTimeSeriesResponse(BaseModel):
    """Response schema for time series metrics"""

    metricName: str = Field(..., description="Metric name queried")
    dataPoints: List[TimeSeriesDataPoint] = Field(
        ..., description="Time series data points"
    )
    aggregation: str = Field(..., description="Aggregation function used")
    totalCount: int = Field(..., description="Number of data points")


# ===== Infrastructure Metrics Schemas =====


class GetInfraMetricsRequest(BaseModel):
    """Request schema for getting infrastructure metrics"""

    metric_name: str = Field(
        ...,
        description="Infrastructure metric name (e.g., 'cpuPercent', 'memoryUsedPercent')",
    )
    hostname: Optional[str] = Field(None, description="Filter by hostname")
    startTime: int = Field(..., description="Start time in seconds since epoch")
    endTime: int = Field(..., description="End time in seconds since epoch")
    aggregation: Optional[str] = Field(
        "average", description="Aggregation function: average, sum, min, max"
    )


class GetInfraMetricsResponse(BaseModel):
    """Response schema for infrastructure metrics"""

    metricName: str = Field(..., description="Infrastructure metric name")
    dataPoints: List[TimeSeriesDataPoint] = Field(..., description="Metric data points")
    aggregation: str = Field(..., description="Aggregation function used")
    totalCount: int = Field(..., description="Number of data points")
