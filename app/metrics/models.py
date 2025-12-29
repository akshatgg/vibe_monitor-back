"""
Data models for metrics responses
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class MetricValue(BaseModel):
    """Single metric value with timestamp"""

    timestamp: datetime
    value: float


class MetricSeries(BaseModel):
    """Time series data for a metric"""

    metric: Dict[str, str] = Field(description="Metric labels")
    values: List[MetricValue] = Field(description="Time series values")


class InstantMetricResponse(BaseModel):
    """Response for instant metric queries"""

    status: str = Field(description="Query status")
    data: Dict[str, Any] = Field(description="Query result data")
    metric_name: str = Field(description="Queried metric name")
    result_type: str = Field(
        description="Type of result (vector, matrix, scalar, string)"
    )
    result: List[Dict[str, Any]] = Field(description="Actual metric results")


class RangeMetricResponse(BaseModel):
    """Response for range metric queries"""

    status: str = Field(description="Query status")
    data: Dict[str, Any] = Field(description="Query result data")
    metric_name: str = Field(description="Queried metric name")
    result_type: str = Field(description="Type of result (matrix)")
    result: List[MetricSeries] = Field(description="Time series results")


class MetricTarget(BaseModel):
    """Monitoring target information"""

    discoveredLabels: Dict[str, str] = Field(description="Discovered labels")
    labels: Dict[str, str] = Field(description="Target labels")
    scrapePool: str = Field(description="Scrape pool name")
    scrapeUrl: str = Field(description="Target URL")
    globalUrl: str = Field(description="Global URL")
    lastError: Optional[str] = Field(description="Last scrape error")
    lastScrape: datetime = Field(description="Last scrape time")
    lastScrapeDuration: float = Field(description="Last scrape duration in seconds")
    health: str = Field(description="Target health status")


class TargetsResponse(BaseModel):
    """Response for targets query"""

    status: str = Field(description="Query status")
    data: Dict[str, List[MetricTarget]] = Field(description="Targets data")


class LabelResponse(BaseModel):
    """Response for label queries"""

    status: str = Field(description="Query status")
    data: List[str] = Field(description="List of label names or values")


class TimeRange(BaseModel):
    """Time range specification"""

    start: Union[datetime, str] = Field(
        description="Start time (datetime or relative like 'now-1h')"
    )
    end: Union[datetime, str] = Field(
        description="End time (datetime or relative like 'now')"
    )
    step: Optional[str] = Field(
        default="60s", description="Query resolution step (e.g., '60s', '5m')"
    )


class MetricQueryParams(BaseModel):
    """Parameters for metric queries"""

    service_name: Optional[str] = Field(
        default=None, description="Filter by service name"
    )
    time_range: Optional[TimeRange] = Field(
        default=None, description="Time range for range queries"
    )
    labels: Optional[Dict[str, str]] = Field(
        default=None, description="Additional label filters"
    )
    timeout: Optional[str] = Field(default="30s", description="Query timeout")
